"""定时编排的时间边界、名单完整性与故障状态转换，全部使用虚构数据。"""

from datetime import timedelta
import json

import pytest

from dake.domain.models import parse_time
from dake.services.scheduled_customers import FileCustomerSource
from dake.services.scheduling import completion, window_end


def values():
    start = "2038-06-01T00:00:00+08:00"
    schedule = dict(schedule_id="synthetic-schedule", uid="synthetic-customer", stream="stub-v1",
                    next_start=start, retry_count=0)
    run = dict(run_id="synthetic-run", uid=schedule["uid"], status="failed", completed_windows=0,
               finished_at="2038-06-01T00:15:00+08:00",
               request=dict(analysis_stream="stub-v1", schedule_id=schedule["schedule_id"],
                            start=start, end="2038-06-01T00:15:00+08:00", execution_error_kind="transient"))
    return schedule, run


def test_only_complete_windows_are_ready_without_extra_delay():
    start = parse_time("2038-06-01T00:00:00")
    step = timedelta(minutes=15)
    assert window_end(start, start + step - timedelta(microseconds=1), step) is None
    assert window_end(start, start + step, step) == start + step
    assert window_end(start, start - step, step) is None


@pytest.mark.parametrize("status", ["queued", "running"])
def test_in_flight_window_never_advances(status):
    schedule, run = values()
    run["status"] = status
    assert completion(schedule, run, {}, parse_time(run["finished_at"])) == {}


@pytest.mark.parametrize("count,delay", [(0, 60), (1, 300), (2, 900)])
def test_retry_deadline_is_based_on_original_failure_and_budget(count, delay):
    schedule, run = values()
    schedule["retry_count"] = count
    failed = parse_time(run["finished_at"])
    result = completion(schedule, run, dict(outcome="not_committed", attempt_id="synthetic-attempt"), failed + timedelta(hours=1))
    assert result["retry_count"] == count + 1
    assert parse_time(result["retry_at"]) == failed + timedelta(seconds=delay)
    assert "next_start" not in result
    assert result["retry_attempt_id"] == "synthetic-attempt"


def test_retry_exhaustion_permanent_failure_and_unknown_commit_are_separate():
    schedule, run = values()
    schedule["retry_count"] = 3
    now = parse_time(run["finished_at"])
    attempt = dict(outcome="not_committed", attempt_id="synthetic-attempt")
    assert completion(schedule, run, attempt, now)["status"] == "paused"
    schedule["retry_count"] = 0
    run["request"]["execution_error_kind"] = "permanent"
    assert completion(schedule, run, attempt, now)["status"] == "paused"
    assert completion(schedule, run, dict(outcome="commit_unknown", attempt_id="synthetic-attempt"), now)["status"] == "needs_verification"


def test_success_requires_receipt_and_empty_or_review_windows_advance():
    schedule, run = values()
    run.update(status="succeeded", completed_windows=1, cycles=[dict(processed=0, review=["synthetic-review"])])
    now = parse_time(run["finished_at"])
    assert completion(schedule, run, {}, now)["status"] == "needs_verification"
    result = completion(schedule, run, dict(outcome="committed", receipt={"cycle": {}}), now)
    assert result["next_start"] == run["request"]["end"]
    assert result["retry_count"] == 0 and result["error"] is None


def test_committed_delivery_failure_retries_by_explicit_attempt_instead_of_new_analysis():
    schedule, run = values()
    run["request"]["execution_error_kind"] = "delivery"
    result = completion(schedule, run, dict(outcome="committed", receipt={"cycle": {}}, attempt_id="synthetic-parent"),
                        parse_time(run["finished_at"]))
    assert result["retry_attempt_id"] == "synthetic-parent"
    assert "next_start" not in result and result["retry_count"] == 1


def test_wrong_scope_and_unconfirmed_success_do_not_move_cursor():
    schedule, run = values()
    run["request"]["analysis_stream"] = "synthetic-other-version"
    assert completion(schedule, run, {}, parse_time(run["finished_at"]))["status"] == "paused"


@pytest.mark.parametrize("payload", [
    {}, {"schema_version": 1, "complete": False, "customers": []},
    {"schema_version": 1, "complete": True, "customers": [{"uid": "synthetic", "enabled": "yes"}]},
    {"schema_version": 1, "complete": True, "customers": [{"uid": "synthetic", "enabled": True}] * 2},
])
def test_incomplete_or_conflicting_customer_snapshots_are_rejected(tmp_path, payload):
    directory = tmp_path / "config"
    directory.mkdir()
    (directory / "scheduled_customers.json").write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        FileCustomerSource(tmp_path).load()


def test_customer_snapshot_allows_explicit_empty_and_disabled_without_inferring_uid(tmp_path):
    directory = tmp_path / "config"
    directory.mkdir()
    file = directory / "scheduled_customers.json"
    file.write_text(json.dumps(dict(schema_version=1, complete=True, customers=[])))
    assert FileCustomerSource(tmp_path).load() == []
    file.write_text(json.dumps(dict(schema_version=1, complete=True, customers=[dict(uid="synthetic-customer", enabled=False)])))
    customers = FileCustomerSource(tmp_path).load()
    assert customers[0].enabled is False and customers[0].uid == "synthetic-customer"


def test_cli_orchestration_still_ticks_when_another_worker_owns_execution(monkeypatch):
    """独立运行入口不能因为 API 已占执行锁而永远不提交定时任务。"""
    from dake import cli
    from dake.config import Settings
    calls = []
    class Scheduler:
        def __init__(self, settings):
            pass
        def tick(self):
            calls.append("tick")
    class NonLeader:
        def __init__(self, *args):
            pass
        def start(self):
            calls.append("start")
        def notify(self):
            calls.append("notify")
        def stop(self):
            calls.append("stop")
    class StopAfterTick:
        def wait(self, seconds):
            raise KeyboardInterrupt()
    monkeypatch.setattr(cli.Settings, "load", lambda *args: Settings())
    monkeypatch.setattr("dake.services.scheduling.SchedulingService", Scheduler)
    monkeypatch.setattr("dake.jobs.runner.RunRunner", NonLeader)
    monkeypatch.setattr(cli.threading, "Event", StopAfterTick)
    assert cli.main(["schedule", "run"]) == 0
    assert calls == ["start", "tick", "notify", "stop"]
