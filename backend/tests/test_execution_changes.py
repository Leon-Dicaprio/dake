"""真实共享链路的虚构输入及只读执行面板验收，不访问真实数据库或聊天。"""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
import json

import httpx
import pytest
from offline_http import TestClient, offline_only

from dake.analysis.providers.xhub import XHubConfig, XHubProvider
from dake.api.app_factory import create_app
from dake.api.schemas import EventChangesResponse
from dake.domain.execution_links import link_reasons
from dake.repositories.attempts import AttemptError, AttemptPendingVerification, AttemptRepository
from dake.repositories.mysql import StorageError
from dake.services.event_changes import event_changes
from dake.services.execution_changes import execution_changes
from dake.services.processing import IncrementalService
from dake.services.queries import QueryService
from test_api import WakeOnly
from test_attribution import UID, candidate, message, model_output, window
from test_executions import setup
from test_summary_history import change


class ReadAttempts(AttemptRepository):
    """只替换 SQL 连接；保留实际分页和重试关系查询编排。"""

    def __init__(self, records, event_id, *, present=True, broken=False):
        self.records, self.event_id, self.present, self.broken = records, event_id, present, broken
        self.calls = []

    @contextmanager
    def connection(self):
        owner = self
        class Connection:
            def _execute(self, sql, args=()):
                owner.calls.append((sql, args))
                assert sql.startswith("SELECT "), "面板必须只读"
                if owner.broken:
                    raise StorageError("虚构记录查询失败")
                if "information_schema" in sql:
                    return ([dict(present=1)] if owner.present else []), 0
                uid, stream = args[-2:] if " AS related " in sql else args[:2]
                values = [r for r in owner.records.values() if (r["uid"], r["stream"]) == (uid, stream)]
                if " AS related " in sql:
                    # 内存替身使用同一固定时间；显式给出递增测试时钟，避免随机 UUID 代替执行顺序。
                    return [dict(attempt_id=r["attempt_id"], retry_of=r.get("retry_of"),
                                 created_at=f"2038-01-01T00:00:00.{index:06d}",
                                 related=bool(link_reasons(r, owner.event_id))) for index, r in enumerate(values)], 0
                assert "ORDER BY" not in sql
                return [deepcopy(r) for r in values if r["attempt_id"] in args[2:]], 0
        yield Connection()


def project(event, attempts, *, offset=0, limit=20):
    repo = ReadAttempts(attempts.items, event["event_id"])
    page = repo.list_for_event_changes(event["uid"], event["stream"], event["event_id"],
        {r.get("attempt_id") for r in event["updated_by"]}, offset, limit)
    result = event_changes(event, dict(items=[], total=0), 0)
    result.update(execution_changes(event, result["revisions"], page, offset))
    return EventChangesResponse.model_validate(result).model_dump()


def opening(tmp_path):
    service, attempts, store, source, provider, first = setup(tmp_path)
    result = service.run_window(UID, window(1), execution=dict(run_id="synthetic-run", window_index=0))
    return service, attempts, store, source, provider, first, result.created[0]


def test_cross_day_real_pipeline_projects_inputs_basis_suggestions_decisions_and_committed_diff(tmp_path):
    service, attempts, store, source, provider, first, event_id = opening(tmp_path)
    follow = message("ten", 10, "虚构工单上次报告上传问题未好，现已定位参数错误。")
    source.messages.append(follow)
    provider.mapping[follow.message_id] = candidate(follow, "update", event_id, [first], changes=[change(follow)])
    result = service.run_window(UID, window(10))
    saved = deepcopy((store.events, attempts.items, provider.calls))
    data = project(store.events[event_id].to_dict(), attempts)
    current, initial = data["executions"]
    assert current["attempt_id"] == result.attempt_id and current["commit_status"] == "committed"
    assert current["updated"] and current["revision_indexes"] == [1] and initial["revision_indexes"] == [0]
    assert current["inputs"][1]["new_messages"][0]["quote"] == follow.content
    assert current["contexts"][0]["fragments"][0]["text"] == first.content
    assert current["candidates"][0]["event_id"] == event_id
    assert current["suggestions"][0]["action"] == "update" and current["decisions"][0]["event_id"] == event_id
    assert current["decisions"][0]["before"]["summary"] != current["decisions"][0]["after"]["summary"]
    assert (store.events, attempts.items, provider.calls) == saved


def test_candidate_only_batch_is_related_but_never_claimed_as_an_event_update(tmp_path):
    service, attempts, store, source, provider, _, event_id = opening(tmp_path)
    source.messages.append(message("candidate-only", 10, "虚构工单上次报告上传问题的信息已收到。"))
    result = service.run_window(UID, window(10))
    current = project(store.events[event_id].to_dict(), attempts)["executions"][0]
    assert current["attempt_id"] == result.attempt_id and "candidate" in current["related_by"]
    assert not current["updated"] and not current["created"] and not current["revision_indexes"]
    assert current["decisions"] == [] and len(provider.calls) == 2


def test_snapshot_membership_reason_text_and_same_window_cannot_create_event_link(tmp_path):
    _, attempts, store, _, _, _, event_id = opening(tmp_path)
    original = list(attempts.items.values())[0]
    unrelated = deepcopy(original)
    unrelated.update(attempt_id="synthetic-unrelated", stages=[], retry_of=None)
    unrelated["receipt"]["writes"] = []
    unrelated["receipt"]["cycle"].update(created=[], updated=[], filter_audit=[])
    unrelated["metadata"]["reason"] = event_id
    attempts.items[unrelated["attempt_id"]] = unrelated
    # 全量快照及其 event_versions 仍包含本事件，但没有候选、决定或实际写入。
    data = project(store.events[event_id].to_dict(), attempts)
    assert [r["attempt_id"] for r in data["executions"]] == [original["attempt_id"]]


def test_retry_chain_remains_visible_even_before_new_candidate_stage_and_paginates_after_filter(tmp_path):
    _, attempts, store, _, _, _, event_id = opening(tmp_path)
    parent = list(attempts.items.values())[0]
    for number in range(3):
        child = deepcopy(parent)
        child.update(attempt_id=f"synthetic-retry-{number}", retry_of=parent["attempt_id"], stages=[], receipt=None, outcome="running")
        attempts.items[child["attempt_id"]] = child
        parent = child
    event = store.events[event_id].to_dict()
    first = project(event, attempts, limit=2)
    assert first["total_executions"] == 4 and first["next_execution_offset"] == 2
    assert all(r["commit_status"] == "unconfirmed" and not r["updated"] for r in first["executions"])
    second = project(event, attempts, offset=2, limit=2)
    assert second["next_execution_offset"] is None
    assert {r["attempt_id"] for r in first["executions"]}.isdisjoint(r["attempt_id"] for r in second["executions"])


@pytest.mark.parametrize("committed", [False, True])
def test_unknown_commit_keeps_pending_status_and_reads_do_not_verify_or_retry(tmp_path, committed):
    service, attempts, store, source, provider, first, event_id = opening(tmp_path)
    follow = message("unknown", 2, "虚构工单补充排查参数错误。")
    source.messages.append(follow)
    provider.mapping[follow.message_id] = candidate(follow, "update", event_id, [first], changes=[change(follow)])
    store.commit_fault = "after" if committed else "before"
    with pytest.raises(AttemptPendingVerification):
        service.run_window(UID, window(2))
    saved = deepcopy(attempts.items)
    data = project(store.events[event_id].to_dict(), attempts)["executions"][0]
    assert data["outcome"] == "commit_unknown"
    assert data["commit_status"] == ("committed" if committed else "unconfirmed")
    assert data["updated"] == committed and bool(data["revision_indexes"]) == committed
    assert attempts.items == saved and len(provider.calls) == 2


def test_failed_record_preserves_proposed_diff_without_claiming_commit(tmp_path):
    service, attempts, store, source, provider, first, event_id = opening(tmp_path)
    follow = message("fail", 2, "虚构工单新的排查事实。")
    source.messages.append(follow)
    provider.mapping[follow.message_id] = candidate(follow, "update", event_id, [first], changes=[change(follow)])
    attempts.fail_receipt = True
    with pytest.raises(AttemptError):
        service.run_window(UID, window(2))
    data = project(store.events[event_id].to_dict(), attempts)["executions"][0]
    assert data["decisions"][0]["after"]["summary"] != data["decisions"][0]["before"]["summary"]
    assert data["commit_status"] == "not_committed" and not data["updated"] and data["revision_indexes"] == []


def test_committed_display_recovery_never_claims_second_event_write(tmp_path):
    service, attempts, store, _, provider, _, event_id = opening(tmp_path)
    original = list(attempts.items.values())[0]
    service.run_window(UID, window(1), execution=dict(retry_of=original["attempt_id"]))
    data = project(store.events[event_id].to_dict(), attempts)["executions"][0]
    assert data["receipt_kind"] == "delivery_recovery" and data["retry_of"] == original["attempt_id"]
    assert not data["created"] and not data["updated"] and data["revision_indexes"] == [] and data["processed"] == 0
    assert len(provider.calls) == 1


@pytest.mark.parametrize("damage", ["snapshot", "digest", "receipt_scope"])
def test_missing_or_mismatched_revision_never_uses_later_event_content(tmp_path, damage):
    _, attempts, store, _, _, _, event_id = opening(tmp_path)
    event = store.events[event_id].to_dict()
    record = list(attempts.items.values())[0]
    if damage == "snapshot": event["updated_by"][0]["snapshot"] = None
    elif damage == "digest": record["receipt"]["event_versions"][0]["digest"] = "synthetic-wrong"
    else: record["receipt"]["cycle"]["uid"] = "foreign-customer"
    data = project(event, attempts)["executions"][0]
    assert data["revision_indexes"] == []
    assert data["commit_status"] == ("invalid" if damage == "receipt_scope" else "committed")


def test_repository_and_projection_reject_foreign_scope_and_hide_foreign_retry_id(tmp_path):
    _, attempts, store, _, _, _, event_id = opening(tmp_path)
    original = list(attempts.items.values())[0]
    for key, field in [("foreign-customer-record", "uid"), ("foreign-scope-record", "stream")]:
        value = deepcopy(original)
        value.update(attempt_id=key)
        value[field] = "foreign-value"
        attempts.items[key] = value
    original["retry_of"] = "foreign-customer-record"
    event = store.events[event_id].to_dict()
    data = project(event, attempts)
    assert len(data["executions"]) == 1 and data["executions"][0]["retry_link_unavailable"]
    assert "foreign-" not in json.dumps(data)
    injected = dict(available=True, items=list(attempts.items.values()), total=3, known_ids=[], related_ids=[])
    assert len(execution_changes(event, event["updated_by"], injected, 0)["executions"]) == 1


def test_actual_xhub_request_is_read_from_saved_versions_without_exposing_config(tmp_path):
    service, attempts, store, source, _, first = setup(tmp_path)
    settings = replace(service.settings, provider="xhub")
    provider = XHubProvider(XHubConfig(model=settings.llm_model, api_key="synthetic-private-config", max_tokens=8192), settings,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": model_output(first)}}]})))
    try:
        service = IncrementalService(store, source, provider, settings, attempts=attempts)
        result = service.run_window(UID, window(1))
        data = project(store.events[result.created[0]].to_dict(), attempts)
        request = next(v for v in data["executions"][0]["inputs"] if v["origin"] == "request")
        assert request["new_messages"][0]["digest"] == first.digest and request["new_messages"][0]["quote"] == first.content
        assert "synthetic-private-config" not in json.dumps(data) and "attribution_policy" not in json.dumps(data)
    finally:
        provider.close()


@pytest.mark.parametrize("present,broken", [(True, False), (False, False), (True, True)])
def test_endpoint_is_read_only_and_missing_table_differs_from_query_failure(tmp_path, present, broken):
    service, attempts, store, _, provider, _ = setup(tmp_path)
    provider.name = "stub-v1"
    event_id = service.run_window(UID, window(1)).created[0]
    settings = service.settings
    class Runs:
        def init_schema(self): pass
        def list_for_event_changes(self, uid, stream, offset, event_id=None):
            return dict(items=[], total=0)
    repo = ReadAttempts(attempts.items, event_id, present=present, broken=broken)
    query = QueryService(settings, lambda **kwargs: store, attempts=repo)
    app = create_app(settings, run_repository=Runs(), runner=WakeOnly(), query_service=query, start_worker=False)
    saved = deepcopy((attempts.items, provider.calls))
    with TestClient(app) as client:
        url = f"/api/v1/events/{event_id}/changes"
        assert client.get(url).status_code == 422
        response = client.get(url, params=dict(uid=UID, stream="stub-v1"))
        assert response.status_code == (503 if broken else 200)
        if not broken:
            assert response.json()["execution_records_available"] == present
            if present:
                assert response.json()["executions"][0]["commit_status"] == "committed"
        assert client.get(url, params=dict(uid=UID, stream="wrong")).status_code == 400
        assert client.get(url, params=dict(uid="foreign-customer", stream="stub-v1")).status_code == 404
        assert client.get(url, params=dict(uid=UID, stream="stub-v1", execution_offset=-1)).status_code == 422
    assert (attempts.items, provider.calls) == saved
    assert all(sql.startswith("SELECT ") for sql, _ in repo.calls)


def test_update_attribution_without_new_fact_has_no_proposed_or_committed_revision(tmp_path):
    service, attempts, store, source, provider, first, event_id = opening(tmp_path)
    follow = message("ack", 2, "虚构工单消息已收到。")
    source.messages.append(follow)
    provider.mapping[follow.message_id] = candidate(follow, "update", event_id, [first], changes=[])
    service.run_window(UID, window(2))
    data = project(store.events[event_id].to_dict(), attempts)["executions"][0]
    assert data["suggestions"][0]["action"] == "update"
    # 现行规则保留 update 归属，是否形成修订另行记录，面板不可自行改写成第五类动作。
    assert data["decisions"][0]["action"] == "update"
    assert data["decisions"][0]["contributed_to_revision"] is False
    assert data["decisions"][0]["before"] == data["decisions"][0]["after"]
    assert data["commit_status"] == "committed" and data["processed"] == 1
    assert not data["updated"] and data["revision_indexes"] == []


def test_same_window_later_revision_does_not_replace_the_original_receipt_snapshot(tmp_path):
    service, attempts, store, source, provider, first, event_id = opening(tmp_path)
    follow = message("same-window", 1, "虚构工单当日补充排查结论。")
    source.messages.append(follow)
    provider.mapping[follow.message_id] = candidate(follow, "update", event_id, [first], changes=[change(follow)])
    service.run_window(UID, window(1))
    data = project(store.events[event_id].to_dict(), attempts)
    assert [r["revision_indexes"] for r in data["executions"]] == [[1], [0]]
    assert data["revisions"][0]["snapshot"]["summary"] == first.content


@pytest.mark.parametrize("damage", ["missing_list", "unknown_format", "recovery_with_writes"])
def test_incomplete_receipt_is_not_reported_as_zero_writes_or_recovery_success(tmp_path, damage):
    _, attempts, store, _, _, _, event_id = opening(tmp_path)
    receipt = list(attempts.items.values())[0]["receipt"]
    if damage == "missing_list":
        del receipt["processed_versions"]
    elif damage == "unknown_format":
        receipt["version"] = 999
    else:
        receipt["kind"] = "delivery_recovery"
    data = project(store.events[event_id].to_dict(), attempts)["executions"][0]
    assert data["commit_status"] == "invalid" and data["processed"] is None
    assert not data["created"] and not data["updated"] and data["revision_indexes"] == []


def test_legacy_cycles_are_suppressed_only_when_the_formal_attempt_still_exists(tmp_path):
    _, attempts, store, _, _, _, event_id = opening(tmp_path)
    event = store.events[event_id].to_dict()
    record = list(attempts.items.values())[0]
    run = dict(uid=UID, run_id="synthetic-run", request=dict(analysis_stream=event["stream"]),
        status="succeeded", completed_windows=1, total_windows=1, cycles=[deepcopy(record["receipt"]["cycle"])])
    page = dict(items=[run], total=1)
    assert event_changes(event, page, 0, {record["attempt_id"]})["batches"] == []
    assert len(event_changes(event, page, 0)["batches"]) == 1


def test_large_stage_query_sorts_only_lightweight_heads_without_database():
    """关联表达式查询不做数据库排序，内存顺序与重试链分页保持一致。"""
    from contextlib import contextmanager
    from dake.config import Settings
    from dake.repositories.attempts import AttemptRepository

    queries = []
    class Store:
        def _execute(self, sql, args=()):
            queries.append(sql)
            if 'information_schema' in sql:
                return [{'present': 1}], 0
            if ' AS related ' in sql:
                assert 'ORDER BY' not in sql
                return [dict(attempt_id='a', retry_of=None, created_at='2038-01-01', related=True),
                        dict(attempt_id='c', retry_of='a', created_at='2038-01-02', related=False),
                        dict(attempt_id='b', retry_of=None, created_at='2038-01-03', related=True)], 0
            assert args == ('synthetic-customer', 'synthetic-stream', 'b', 'c')
            return [dict(attempt_id='c'), dict(attempt_id='b')], 0

    class Repository(AttemptRepository):
        @contextmanager
        def connection(self):
            yield Store()

    page = Repository(Settings()).list_for_event_changes(
        'synthetic-customer', 'synthetic-stream', 'synthetic-event', limit=2)
    assert [item['attempt_id'] for item in page['items']] == ['b', 'c']
    assert page['total'] == 3 and len(queries) == 3
