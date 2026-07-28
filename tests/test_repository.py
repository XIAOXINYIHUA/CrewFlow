from __future__ import annotations

import json

from src.repository import (
    append_run_event,
    count_runs,
    create_run,
    get_run_events,
    list_runs,
    update_run_status,
)


def test_run_filtering_count_and_pagination(isolated_database):
    for index in range(3):
        create_run(f"run_{index}", f"thread_{index}", f"topic {index}")
    update_run_status("run_0", "completed")
    update_run_status("run_1", "failed")

    assert count_runs() == 3
    assert count_runs("completed") == 1
    assert [run.id for run in list_runs(limit=10, status="failed")] == ["run_1"]
    assert len(list_runs(limit=1, offset=1)) == 1


def test_run_events_are_sequenced_and_replayable(isolated_database):
    create_run("run_events", "thread_events", "events")

    first = append_run_event("run_events", "started", {"value": 1})
    second = append_run_event("run_events", "node_completed", {"value": 2})

    assert (first.sequence, second.sequence) == (1, 2)
    replay = get_run_events("run_events", after_sequence=1)
    assert [event.sequence for event in replay] == [2]
    assert json.loads(replay[0].payload_json) == {"value": 2}
