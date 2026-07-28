"""Background LangGraph execution with replayable progress events."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from src.graph import build_graph
from src.repository import append_run_event, list_runs, update_run_status
from src.services.run_persistence import persist_graph_update, persist_terminal_state
from src.state import CrewState, create_initial_state

GraphInput = CrewState | Command[Any] | None


class RunCoordinator:
    """Own one background graph execution per run and notify SSE subscribers."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._conditions: dict[str, asyncio.Condition] = {}
        self._cancelled: set[str] = set()
        self._guard = asyncio.Lock()

    def is_active(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        return task is not None and not task.done()

    async def wait(self, run_id: str) -> None:
        """Wait for the current execution segment, primarily for graceful callers and tests."""
        task = self._tasks.get(run_id)
        if task is not None:
            await asyncio.shield(task)

    async def start(
        self,
        run_id: str,
        thread_id: str,
        graph_input: GraphInput,
        *,
        event_type: str = "started",
    ) -> bool:
        """Start or resume a graph once; return False when it is already active."""
        async with self._guard:
            if self.is_active(run_id):
                return False
            self._cancelled.discard(run_id)
            await asyncio.to_thread(update_run_status, run_id, "running")
            await self._append_event(
                run_id,
                event_type,
                {"type": event_type, "run_id": run_id},
            )
            self._tasks[run_id] = asyncio.create_task(
                self._drive_graph(run_id, thread_id, graph_input),
                name=f"crewflow-{run_id}",
            )
            return True

    async def cancel(self, run_id: str) -> None:
        """Mark a run cancelled and ignore results from an already-running node."""
        self._cancelled.add(run_id)
        await asyncio.to_thread(update_run_status, run_id, "cancelled")
        await self._append_event(
            run_id,
            "cancelled",
            {"type": "cancelled", "run_id": run_id, "status": "cancelled"},
        )

    async def wait_for_update(self, run_id: str, timeout: float = 15.0) -> bool:
        """Wait until an event is appended; False means heartbeat timeout."""
        condition = self._conditions.setdefault(run_id, asyncio.Condition())
        try:
            async with condition:
                await asyncio.wait_for(condition.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False

    async def recover_incomplete(self) -> None:
        """Resume queued/running runs after process restart when a checkpoint exists."""
        for status in ("queued", "running"):
            runs = await asyncio.to_thread(list_runs, 100, 0, status)
            for run in runs:
                graph = build_graph()
                config: RunnableConfig = {"configurable": {"thread_id": run.thread_id}}
                snapshot = await asyncio.to_thread(graph.get_state, config)
                graph_input = None
                if not snapshot.values:
                    graph_input = create_initial_state(
                        topic=run.topic,
                        run_id=run.id,
                        thread_id=run.thread_id,
                        require_human_approval=run.require_human_approval,
                    )
                await self.start(
                    run.id,
                    run.thread_id,
                    graph_input,
                    event_type="recovered",
                )

    async def shutdown(self) -> None:
        """Cancel coordinator tasks during application shutdown."""
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _drive_graph(
        self,
        run_id: str,
        thread_id: str,
        graph_input: GraphInput,
    ) -> None:
        graph = build_graph()
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def emit(kind: str, value: Any) -> None:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, (kind, value))
            except RuntimeError:
                pass

        def worker() -> None:
            try:
                for event in graph.stream(graph_input, config=config, stream_mode="updates"):
                    emit("event", event)
                emit("done", dict(graph.get_state(config).values))
            except BaseException as exc:
                emit("error", exc)

        worker_task = asyncio.create_task(asyncio.to_thread(worker))
        interrupted = False
        try:
            while True:
                kind, value = await queue.get()
                if kind == "event":
                    if run_id not in self._cancelled:
                        interrupted = await self._process_event(run_id, value) or interrupted
                    continue
                if kind == "error":
                    raise value
                if kind == "done":
                    if run_id in self._cancelled:
                        return
                    if interrupted:
                        return
                    status = self._terminal_status(value)
                    await asyncio.to_thread(persist_terminal_state, run_id, value, status)
                    await self._append_event(
                        run_id,
                        status,
                        {
                            "type": status,
                            "run_id": run_id,
                            "status": status,
                            "has_report": bool(value.get("final_report")),
                        },
                    )
                    return
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            if run_id not in self._cancelled:
                await asyncio.to_thread(update_run_status, run_id, "failed")
                await self._append_event(
                    run_id,
                    "error",
                    {"type": "error", "run_id": run_id, "error": str(exc)},
                )
        finally:
            if not worker_task.done():
                worker_task.cancel()
            await asyncio.gather(worker_task, return_exceptions=True)

    async def _process_event(self, run_id: str, event: Mapping[str, Any]) -> bool:
        interrupted = False
        for node_name, update in event.items():
            if node_name == "__interrupt__":
                interrupted = True
                await asyncio.to_thread(
                    update_run_status,
                    run_id,
                    "waiting_human",
                    current_node="human_review",
                )
                await self._append_event(
                    run_id,
                    "interrupt",
                    {
                        "type": "interrupt",
                        "node": "human_review",
                        "run_id": run_id,
                        "status": "waiting_human",
                    },
                )
                continue

            if not isinstance(update, dict):
                continue
            await asyncio.to_thread(persist_graph_update, run_id, node_name, update)
            payload: dict[str, Any] = {
                "type": "node_completed",
                "node": node_name,
                "run_id": run_id,
                "status": update.get("status", "running"),
            }
            review = update.get("review")
            if review:
                payload["review_verdict"] = review.verdict
                payload["review_scores"] = {
                    "factuality": review.factuality_score,
                    "citation": review.citation_score,
                    "coverage": review.coverage_score,
                    "structure": review.structure_score,
                }
            if errors := [error for error in update.get("errors") or [] if error]:
                payload["errors"] = errors
            await self._append_event(run_id, "node_completed", payload)
        return interrupted

    async def _append_event(self, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        await asyncio.to_thread(append_run_event, run_id, event_type, payload)
        condition = self._conditions.setdefault(run_id, asyncio.Condition())
        async with condition:
            condition.notify_all()

    @staticmethod
    def _terminal_status(state: Mapping[str, Any]) -> str:
        status = state.get("status")
        if status in {"completed", "failed", "cancelled"}:
            return str(status)
        if state.get("final_report"):
            return "completed"
        return "failed"


run_coordinator = RunCoordinator()
