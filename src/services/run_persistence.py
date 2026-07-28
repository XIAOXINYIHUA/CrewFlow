"""Persist LangGraph updates into the queryable application database."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from src.repository import (
    get_run,
    save_claims,
    save_node_execution,
    save_report_version,
    save_review,
    save_sources,
    update_run_status,
)


def persist_graph_update(run_id: str, node_name: str, update: dict[str, Any]) -> None:
    """Persist one node update without treating node completion as run completion."""
    if sources := update.get("sources"):
        save_sources(run_id, sources)
    if claims := update.get("claims"):
        save_claims(run_id, claims)
    for version in update.get("report_versions") or []:
        save_report_version(run_id, version)
    if review := update.get("review"):
        save_review(run_id, int(update.get("iteration", 0)), review)
    for record in update.get("node_executions") or []:
        save_node_execution(run_id, record)

    fields: dict[str, Any] = {"current_node": node_name}
    if "iteration" in update:
        fields["iteration"] = int(update["iteration"])
    if "quality_status" in update:
        fields["quality_status"] = update["quality_status"]
    if "total_cost_usd" in update:
        fields["total_cost_usd"] = float(Decimal(update["total_cost_usd"]))

    errors = [error for error in update.get("errors") or [] if error]
    if errors:
        run = get_run(run_id)
        fields["error_count"] = (run.error_count if run else 0) + len(errors)

    update_run_status(run_id, "running", **fields)


def persist_terminal_state(run_id: str, state: dict[str, Any], status: str) -> None:
    """Persist final artifacts and the normalized terminal run state."""
    if sources := state.get("sources"):
        save_sources(run_id, sources)
    if claims := state.get("claims"):
        save_claims(run_id, claims)
    for version in state.get("report_versions") or []:
        save_report_version(run_id, version)
    if review := state.get("review"):
        save_review(run_id, int(state.get("iteration", 0)), review)

    update_run_status(
        run_id,
        status,
        current_node=state.get("current_node"),
        iteration=int(state.get("iteration", 0)),
        quality_status=state.get("quality_status", "unchecked"),
        total_cost_usd=float(Decimal(state.get("total_cost_usd", 0))),
        error_count=len([error for error in state.get("errors") or [] if error]),
    )
