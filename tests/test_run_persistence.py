from __future__ import annotations

from src.models import (
    Claim,
    Evidence,
    NodeExecutionRecord,
    ReportVersion,
    ReviewResult,
    Source,
)
from src.repository import create_run, get_report_versions, get_run, get_sources
from src.services.run_persistence import persist_graph_update, persist_terminal_state


def test_graph_update_persists_queryable_artifacts(isolated_database):
    create_run("run_persist", "thread_persist", "persistence")
    source = Source(
        id="S1",
        canonical_url="https://example.com/source",
        title="Source",
        extraction_status="success",
    )
    claim = Claim(
        id="C1",
        text="Supported claim",
        status="supported",
        evidence=[Evidence(source_id="S1", quote="verbatim evidence")],
    )
    version = ReportVersion(
        id="R1",
        run_id="run_persist",
        markdown="# Report",
        created_by_node="writer",
    )
    review = ReviewResult(
        verdict="approved",
        factuality_score=90,
        citation_score=90,
        coverage_score=85,
        structure_score=95,
    )
    record = NodeExecutionRecord(node_name="writer", status="completed")

    persist_graph_update(
        "run_persist",
        "writer",
        {
            "sources": [source],
            "claims": [claim],
            "report_versions": [version],
            "review": review,
            "iteration": 1,
            "node_executions": [record],
        },
    )

    assert [item.id for item in get_sources("run_persist")] == ["S1"]
    assert [item.id for item in get_report_versions("run_persist")] == ["R1"]
    run = get_run("run_persist")
    assert run is not None
    assert run.current_node == "writer"
    assert run.iteration == 1


def test_terminal_state_normalizes_run_metadata(isolated_database):
    create_run("run_terminal", "thread_terminal", "terminal")
    persist_terminal_state(
        "run_terminal",
        {
            "current_node": "publisher",
            "iteration": 2,
            "quality_status": "passed",
            "total_cost_usd": "0.42",
            "errors": [],
        },
        "completed",
    )

    run = get_run("run_terminal")
    assert run is not None
    assert run.status == "completed"
    assert run.completed_at is not None
    assert run.total_cost_usd == 0.42
