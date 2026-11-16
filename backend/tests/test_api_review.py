"""独立审阅发现的后台恢复边界，只使用自造运行记录与事件。"""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from dake.config import Settings, bound
from dake.domain.models import CycleResult, Event, Window
from dake.jobs.runner import RunRunner
from dake.repositories.local_state import LocalState, private_json


def revision(action, window):
    return {"action": action, "window_start": window.start.isoformat(),
            "window_end": window.end.isoformat(), "message_ids": ["synthetic-message"]}


def event_record(event_id, window, history):
    return Event(event_id=event_id, uid="review-fixture-customer", stream="review-fixture-v1",
                 type="排障", topic_key="synthetic-topic", start_time=window.start,
                 end_time=window.start, status="未知", severity="未知", summary="合成事件记录",
                 created_on=window.start, updated_by=history).to_dict()


@pytest.mark.parametrize("old_action", ["created", "updated"])
@pytest.mark.parametrize("has_journal", [False, True])
def test_retry_with_fresh_changes_also_preserves_previous_committed_changes(tmp_path, old_action, has_journal):
    window = Window(bound("2026-11-09"), bound("2026-11-10"))
    previous_window = Window(bound("2026-11-08"), window.start)
    prior_history = [revision("created", previous_window)] if old_action == "updated" else []
    old_event = event_record("previously-committed", window, prior_history + [revision(old_action, window)])
    new_event = event_record("created-during-retry", window, [revision("created", window)])
    result = CycleResult("review-fixture-customer", "review-fixture-v1", window,
                         processed=1, created=[new_event["event_id"]], events=[old_event, new_event])
    unchanged = deepcopy(result)
    runner = RunRunner(Settings(data_dir=tmp_path), object())
    interrupted = {"run_id": "synthetic-failed-run", "completed_windows": 0,
                   "current_baseline": {old_event["event_id"]: len(prior_history)}}

    if has_journal:
        committed = CycleResult(result.uid, result.stream, window, processed=1, events=[old_event])
        getattr(committed, old_action).append(old_event["event_id"])
        private_json(runner._journal_path(interrupted["run_id"], 0), committed.to_dict())

    before_revisions = {old_event["event_id"]: len(old_event["updated_by"])}
    restored = runner._restore_cycle(result, interrupted, SimpleNamespace(state=LocalState(tmp_path)), before_revisions)
    assert restored["recovered_from_history"] is True
    assert new_event["event_id"] in restored["created"]
    assert old_event["event_id"] in restored[old_action]
    assert set(restored["created"]) == ({old_event["event_id"], new_event["event_id"]}
                                        if old_action == "created" else {new_event["event_id"]})
    assert {event["event_id"] for event in restored["events"]} == {old_event["event_id"], new_event["event_id"]}
    assert result == unchanged


def test_retry_after_precommit_failure_does_not_recover_its_own_new_changes(tmp_path):
    window = Window(bound("2026-11-09"), bound("2026-11-10"))
    new_event = event_record("first-created-on-retry", window, [revision("created", window)])
    result = CycleResult("review-fixture-customer", "review-fixture-v1", window,
                         processed=1, ingested=1, created=[new_event["event_id"]], events=[new_event])
    state = LocalState(tmp_path)
    # 这份快照由本次重试写入，旧失败任务尚未提交任何事件，不能拿它当旧提交凭据。
    state.snapshot(result)
    runner = RunRunner(Settings(data_dir=tmp_path), object())
    interrupted = {"run_id": "failed-before-commit", "completed_windows": 0, "current_baseline": {}}
    restored = runner._restore_cycle(result, interrupted, SimpleNamespace(state=state), {})
    assert restored["created"] == [new_event["event_id"]]
    assert restored["processed"] == restored["ingested"] == 1
    assert not restored.get("recovered_from_history", False)
