"""变化面板离线验收；全部消息、事件和任务均为虚构，不连接数据库。"""

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime

import pytest
from offline_http import TestClient, offline_only

from dake.api.app_factory import create_app
from dake.api.schemas import EventChangesResponse
from dake.analysis.providers.xhub import configured_stream
from dake.config import Settings
from test_api import TEST_UID, TEST_STREAM
from dake.domain.models import Event
from dake.repositories.runs import RunRepository, CHANGE_RUN_PAGE_SIZE
from dake.services.event_changes import event_changes
from dake.services.queries import QueryService
from fakes import MemoryStore
from test_api import event_value, WakeOnly


def panel_fixture():
    """首日创建、第十日跟进和提交后进度失败的独立合成记录。"""
    event = event_value()
    event.update(start_time="2038-06-01T09:00:00+08:00", end_time="2038-06-01T09:00:00+08:00",
                 created_on="2038-06-01T00:00:00+08:00")
    event["evidence"][0]["send_time"] = event["start_time"]
    first = dict(action="created", window_start="2038-06-01T00:00:00+08:00",
                 window_end="2038-06-02T00:00:00+08:00", message_ids=["1"], revision_no=1,
                 snapshot=deepcopy(event), summary_changed=True, changes=[])
    event["summary"] = "虚构第十日排查已确认参数错误"
    event["end_time"] = "2038-06-10T09:00:00+08:00"
    second = dict(action="updated", window_start="2038-06-10T00:00:00+08:00",
                  window_end="2038-06-11T00:00:00+08:00", message_ids=[], revision_no=2,
                  snapshot=deepcopy(event), summary_changed=True, changes=[])
    event["updated_by"] = [first, second]
    ref = dict(message_id="synthetic:2", source="synthetic", id="2", digest="synthetic-v2",
               conversation_id="synthetic-room", send_time="2038-06-10T09:00:00+08:00")
    record = dict(kind="event_attribution", action="update", requested_action="update", event_id=event["event_id"],
        possible_event_ids=[], reason="虚构明确引用支持更新", revision_no=2,
        basis=[dict(ref, role="new", quote="虚构第十日上次问题还没好"),
               dict(ref, id="1", message_id="synthetic:1", role="history", digest="synthetic-v1",
                    send_time="2038-06-01T09:00:00+08:00", quote="虚构首日报告上传失败")], new_evidence=[ref])
    cycle = dict(uid=event["uid"], stream=event["stream"], window=dict(start=second["window_start"], end=second["window_end"]),
                 created=[], updated=[event["event_id"]], processed=1, events=[deepcopy(event)], filter_audit=[record])
    run = dict(run_id="synthetic-task", uid=event["uid"], mode="official", status="succeeded", request={"analysis_stream": TEST_STREAM},
               total_windows=1, completed_windows=1, current_window=None, cycles=[cycle],
               created_at="2038-06-10T10:00:00+08:00")
    return event, run


def project(event, *runs):
    return event_changes(event, dict(items=list(runs), total=len(runs)), 0)


def test_saved_receipts_distinguish_suggestion_decision_history_and_versions():
    event, run = panel_fixture()
    saved = deepcopy((event, run))
    data = EventChangesResponse.model_validate(project(event, run)).model_dump()
    batch = data["batches"][0]
    assert batch["revision_indexes"] == [1]
    receipt = batch["attributions"][0]
    assert receipt["requested_action"] == "update" and receipt["action"] == "update"
    assert receipt["basis"][1]["role"] == "history" and receipt["basis"][1]["message_id"] == "1"
    assert receipt["new_evidence"][0]["message_id"] == "2"
    assert receipt["new_evidence"][0]["quote"] == "虚构第十日上次问题还没好"
    assert data["revisions"][0]["snapshot"]["summary"] != data["revisions"][1]["snapshot"]["summary"]
    assert (event, run) == saved


@pytest.mark.parametrize("digest", [None, "another-synthetic-version"])
def test_input_reference_does_not_borrow_quote_from_unknown_or_different_version(digest):
    event, run = panel_fixture()
    record = run["cycles"][0]["filter_audit"][0]
    record["new_evidence"][0]["digest"] = digest
    result = project(event, run)
    assert result["batches"][0]["attributions"][0]["new_evidence"][0]["quote"] is None


def test_snapshot_presence_and_same_window_do_not_create_batch_or_version_link():
    event, run = panel_fixture()
    cycle = run["cycles"][0]
    cycle.update(updated=[], filter_audit=[])
    assert project(event, run)["batches"] == []
    cycle["updated"] = [event["event_id"]]
    data = project(event, run)
    assert data["batches"][0]["revision_indexes"] == []
    assert data["batches"][0]["attributions"] == []


@pytest.mark.parametrize("action", ["review", "duplicate"])
def test_no_revision_receipts_still_visible_without_claiming_event_write(action):
    event, run = panel_fixture()
    cycle = run["cycles"][0]
    cycle["updated"] = []
    record = cycle["filter_audit"][0]
    record.update(action=action, revision_no=None)
    if action == "review":
        record.update(event_id=None, possible_event_ids=[event["event_id"]], requested_action="new")
    result = project(event, run)["batches"][0]
    assert not result["created"] and not result["updated"] and not result["revision_indexes"]
    assert result["attributions"][0]["action"] == action


def test_foreign_tasks_cycles_and_snapshots_never_leak():
    event, good = panel_fixture()
    foreign_customer, foreign_scope = deepcopy(good), deepcopy(good)
    foreign_customer.update(uid="foreign-customer", run_id="foreign-task")
    foreign_scope.update(mode="official", request=dict(analysis_stream="foreign-scope"), run_id="foreign-scope-task")
    foreign_scope["cycles"][0]["stream"] = "foreign-scope"
    # 即使出现混杂的旧周期，明确的外部范围请求也不能混入当前面板。
    foreign_scope["cycles"].append(deepcopy(good["cycles"][0]))
    foreign_cycle = deepcopy(good["cycles"][0])
    foreign_cycle.update(uid="foreign-customer", stream="foreign-scope", processed=987654)
    good["cycles"].append(foreign_cycle)
    event["updated_by"][0]["snapshot"]["stream"] = "foreign-scope"
    result = project(event, good, foreign_customer, foreign_scope)
    assert len(result["tasks"]) == len(result["batches"]) == 1
    assert result["revisions"][0]["snapshot"] is None
    assert "foreign-" not in str(result) and "987654" not in str(result)


def test_failure_after_commit_is_not_reported_as_rollback_or_invented_retry():
    event, failed = panel_fixture()
    failed.update(status="failed", completed_windows=0, current_window=failed["cycles"][0]["window"], cycles=[])
    result = project(event, failed)
    assert result["tasks"] == result["batches"] == []
    assert len(result["revisions"]) == 2
    _, retry = panel_fixture()
    retry["run_id"] = "synthetic-retry"
    retry["cycles"][0].update(recovered_from_history=True, counts_complete=False, filter_audit=[])
    result = project(event, failed, retry)
    assert result["tasks"][0]["recovered_by"] is None
    failed["recovered_by"] = retry["run_id"]
    result = project(event, failed, retry)
    assert [task["run_id"] for task in result["tasks"]] == [retry["run_id"]]
    assert result["batches"][0]["recovered_from_history"] and not result["batches"][0]["counts_complete"]
    assert result["batches"][0]["revision_indexes"] == []
    result = project(event, failed)
    assert result["tasks"] == []


def test_legacy_scope_is_proved_by_cycle_only_and_pagination_remains_explicit():
    event, run = panel_fixture()
    run.update(request={}, current_window=run["cycles"][0]["window"])
    result = event_changes(event, dict(items=[run], total=40), 20)
    assert result["next_offset"] == 21 and result["offset"] == 20
    assert not result["tasks"][0]["current_scope_confirmed"] and result["tasks"][0]["current_window"] is None


@pytest.mark.parametrize("event_id", [None, "synthetic-current-event"])
def test_scoped_repository_binds_scope_before_pagination_without_db(event_id):
    calls = []

    class FakeConnection:
        def _execute(self, sql, args):
            calls.append((sql, args))
            return ([dict(total=0)] if "COUNT(*)" in sql else []), 0

    class Repository(RunRepository):
        @contextmanager
        def connection(self):
            yield FakeConnection()

    result = Repository(Settings()).list_for_event_changes(TEST_UID, TEST_STREAM, 20, event_id=event_id)
    assert result == dict(items=[], total=0)
    assert all("uid=%s" in sql and "analysis_stream" in sql for sql, _ in calls)
    if event_id:
        assert calls[0][1] == (TEST_UID, TEST_UID, TEST_STREAM, TEST_STREAM, *([event_id] * 5))
        assert "JSON_TABLE" in calls[0][0] and "a.kind='event_attribution'" in calls[0][0]
        assert "$.events" not in calls[0][0]
    else:
        assert calls[0][1][:2] == (TEST_UID, TEST_STREAM)
        assert calls[0][1][-2:] == (CHANGE_RUN_PAGE_SIZE, 20)


def test_repository_sorts_ids_before_loading_large_cycle_payloads():
    _, run = panel_fixture()
    older = deepcopy(run)
    older["run_id"] = "synthetic-older"
    for item in (run, older):
        item["created_at"] = datetime(2038, 6, 10)
    calls = []

    class FakeConnection:
        def _execute(self, sql, args):
            calls.append((sql, args))
            if sql.startswith("SELECT run_id "):
                return [dict(run_id=run["run_id"]), dict(run_id=older["run_id"])], 0
            if "COUNT(*)" in sql:
                return [dict(total=2)], 0
            return [older, run], 0

    class Repository(RunRepository):
        @contextmanager
        def connection(self):
            yield FakeConnection()

    result = Repository(Settings()).list_for_event_changes(TEST_UID, TEST_STREAM)
    assert [item["run_id"] for item in result["items"]] == [run["run_id"], older["run_id"]]
    assert "cycles" not in calls[0][0].split("FROM")[0]
    assert "ORDER BY" not in calls[-1][0] and "uid=%s" in calls[-1][0]
    assert calls[-1][1][-2:] == (run["run_id"], older["run_id"])


def test_endpoint_requires_scope_and_reads_no_message_or_trace(tmp_path):
    event, run = panel_fixture()
    store = MemoryStore()
    store.events[event["event_id"]] = Event.from_dict(event)
    calls = []

    class Runs:
        def init_schema(self):
            pass

        def list_for_event_changes(self, uid, stream, offset, event_id=None):
            calls.append((uid, stream, offset))
            return dict(items=[run], total=1)

    class Attempts:
        def list_for_event_changes(self, *args):
            return dict(available=True, items=[], total=0, known_ids=[], related_ids=[])

    settings = Settings(uid=TEST_UID, data_dir=tmp_path)
    app = create_app(settings, run_repository=Runs(), runner=WakeOnly(),
                     query_service=QueryService(settings, lambda **kwargs: store, attempts=Attempts()), start_worker=False)
    url = f"/api/v1/events/{event['event_id']}/changes"
    with TestClient(app) as client:
        assert client.get(url).status_code == 422
        assert client.get(url, params=dict(uid=TEST_UID, stream="other")).status_code == 400
        assert client.get(url, params=dict(uid="99112233", stream=configured_stream(settings))).status_code == 404
        response = client.get(url, params=dict(uid=TEST_UID, stream=TEST_STREAM))
        assert response.status_code == 200
        assert response.json()["batches"][0]["revision_indexes"] == [1]
        assert response.headers["cache-control"] == "no-store"
        assert client.get(url, params=dict(uid=TEST_UID, stream=TEST_STREAM, offset=-1)).status_code == 422
    assert calls == [(TEST_UID, TEST_STREAM, 0)]


def test_projection_of_actual_synthetic_cross_day_pipeline(tmp_path):
    from test_summary_history import opening, followup
    from test_attribution import message

    setup = opening(tmp_path)
    _, store, _, _, _, event_id = setup
    result = followup(setup, message("day-ten", 10, "虚构第十日引用旧问题，排查确认参数错误。"))
    event, run = panel_fixture()
    event = store.events[event_id].to_dict()
    run.update(uid=event["uid"], mode="official", request=dict(analysis_stream=event["stream"]), cycles=[result.to_dict()])
    data = EventChangesResponse.model_validate(project(event, run)).model_dump()
    assert data["batches"][0]["revision_indexes"] == [1]
    assert data["batches"][0]["attributions"][0]["basis"][-1]["role"] == "history"
    assert "参数错误" in data["revisions"][1]["snapshot"]["summary"]
