from __future__ import annotations

import json
import warnings

import pytest
from langchain_core.runnables import RunnableConfig

from src.config import settings
from src.graph import build_graph, reset_graph
from src.repository import create_run, get_run, get_run_events
from src.runtime import RunCoordinator
from src.state import create_initial_state


class Snapshot:
    def __init__(self, values):
        self.values = values


class FakeGraph:
    def __init__(self, events, final_state):
        self.events = events
        self.final_state = final_state

    def stream(self, graph_input, *, config, stream_mode):
        yield from self.events

    def get_state(self, config):
        return Snapshot(self.final_state)


@pytest.mark.asyncio
async def test_coordinator_persists_progress_and_completion(isolated_database, monkeypatch):
    create_run("run_complete", "thread_complete", "complete")
    graph = FakeGraph(
        [{"writer": {"status": "completed"}}],
        {
            "status": "completed",
            "current_node": "publisher",
            "iteration": 0,
            "quality_status": "passed",
            "total_cost_usd": 0,
            "errors": [],
            "final_report": "# Complete",
        },
    )
    monkeypatch.setattr("src.runtime.build_graph", lambda: graph)
    coordinator = RunCoordinator()

    assert await coordinator.start("run_complete", "thread_complete", {})
    await coordinator.wait("run_complete")

    run = get_run("run_complete")
    assert run is not None
    assert run.status == "completed"
    events = get_run_events("run_complete")
    assert [event.event_type for event in events] == ["started", "node_completed", "completed"]
    assert json.loads(events[-1].payload_json)["has_report"] is True


@pytest.mark.asyncio
async def test_coordinator_preserves_waiting_human_state(isolated_database, monkeypatch):
    create_run("run_interrupt", "thread_interrupt", "interrupt")
    graph = FakeGraph(
        [{"__interrupt__": ({"value": "review"},)}],
        {"status": "running", "final_report": None},
    )
    monkeypatch.setattr("src.runtime.build_graph", lambda: graph)
    coordinator = RunCoordinator()

    await coordinator.start("run_interrupt", "thread_interrupt", {})
    await coordinator.wait("run_interrupt")

    run = get_run("run_interrupt")
    assert run is not None
    assert run.status == "waiting_human"
    assert [event.event_type for event in get_run_events("run_interrupt")] == [
        "started",
        "interrupt",
    ]


@pytest.mark.asyncio
async def test_coordinator_cancel_is_terminal(isolated_database):
    create_run("run_cancel", "thread_cancel", "cancel")
    coordinator = RunCoordinator()

    await coordinator.cancel("run_cancel")

    run = get_run("run_cancel")
    assert run is not None
    assert run.status == "cancelled"
    assert [event.event_type for event in get_run_events("run_cancel")] == ["cancelled"]


def test_sqlite_checkpoint_survives_graph_rebuild(isolated_database):
    """A fresh compiled graph must recover typed state from the durable checkpoint."""
    reset_graph()
    config: RunnableConfig = {"configurable": {"thread_id": "thread_rebuild"}}
    initial_state = create_initial_state(
        topic="checkpoint recovery",
        run_id="run_rebuild",
        thread_id="thread_rebuild",
    )

    try:
        first_graph = build_graph()
        first_graph.update_state(config, initial_state)
        assert settings.CHECKPOINT_DB.is_file()

        reset_graph()
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            restored = build_graph().get_state(config)

        assert restored.values["run_id"] == "run_rebuild"
        assert restored.values["topic"] == "checkpoint recovery"
        assert restored.values["requirements"].topic == "checkpoint recovery"
    finally:
        reset_graph()
