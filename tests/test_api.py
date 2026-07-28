from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from src.api import app
from src.repository import append_run_event, create_run, get_run, update_run_status
from src.runtime import run_coordinator


@pytest.fixture
def api_client(isolated_database, monkeypatch):
    monkeypatch.setattr(run_coordinator, "recover_incomplete", AsyncMock())
    monkeypatch.setattr(run_coordinator, "shutdown", AsyncMock())
    with TestClient(app) as client:
        yield client


def test_create_run_starts_background_execution(api_client, monkeypatch):
    start = AsyncMock(return_value=True)
    monkeypatch.setattr(run_coordinator, "start", start)

    response = api_client.post(
        "/api/v1/runs",
        json={
            "topic": "Reliable agents",
            "purpose": "Architecture review",
            "max_sources": 12,
            "require_human_approval": False,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "running"
    run = get_run(body["run_id"])
    assert run is not None
    assert run.target_words == 2500
    assert start.await_count == 1


def test_sse_replays_persisted_events_without_starting_graph(api_client):
    create_run("run_sse", "thread_sse", "SSE")
    append_run_event("run_sse", "started", {"type": "started"})
    append_run_event("run_sse", "completed", {"type": "completed"})
    update_run_status("run_sse", "completed")

    response = api_client.get("/api/v1/runs/run_sse/events", headers={"Last-Event-ID": "1"})

    assert response.status_code == 200
    assert "id: 2" in response.text
    assert "event: completed" in response.text
    assert '"type": "started"' not in response.text
    assert "data: [DONE]" in response.text


def test_list_runs_uses_database_count_for_filtered_pagination(api_client):
    for index in range(3):
        create_run(f"run_page_{index}", f"thread_page_{index}", f"topic {index}")
        update_run_status(f"run_page_{index}", "completed" if index < 2 else "failed")

    response = api_client.get("/api/v1/runs?status=completed&limit=1&offset=0")

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    assert body["pagination"]["total"] == 2
    assert body["pagination"]["has_more"] is True


def test_review_resumes_in_background(api_client, monkeypatch):
    create_run("run_review", "thread_review", "Review")
    update_run_status("run_review", "waiting_human")
    start = AsyncMock(return_value=True)
    monkeypatch.setattr(run_coordinator, "start", start)

    response = api_client.post(
        "/api/v1/runs/run_review/review",
        json={"action": "approve", "feedback": "ship it"},
    )

    assert response.status_code == 200
    assert response.json()["new_status"] == "running"
    assert start.await_count == 1


def test_revise_requires_feedback(api_client):
    create_run("run_revise", "thread_revise", "Revise")
    update_run_status("run_revise", "waiting_human")

    response = api_client.post(
        "/api/v1/runs/run_revise/review",
        json={"action": "revise", "feedback": ""},
    )

    assert response.status_code == 400


def test_readiness_checks_database(api_client):
    response = api_client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
