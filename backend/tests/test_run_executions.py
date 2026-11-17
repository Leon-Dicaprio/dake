"""窗口过程投影的合成验收；没有事件也能看见新消息、待确认及实际保存边界。"""

from copy import deepcopy
from offline_http import offline_only

from dake.api.schemas import RunExecution
from dake.services.run_executions import project_run_execution
from test_api import api, TEST_UID, TEST_STREAM
from test_attribution import UID, candidate, message, window
from test_executions import setup, last


def test_review_without_any_event_still_has_input_basis_decision_and_receipt(tmp_path):
    msg = message('unclear', 1, '虚构那个报告的问题仍然存在，具体对象待核实')
    service, attempts, store, source, provider, first = setup(tmp_path, [msg], {
        msg.message_id: candidate(msg, 'review', ambiguous=True)})
    result = service.run_window(UID, window(1), execution=dict(run_id='synthetic-run', window_index=0))
    assert not result.events and result.review
    before = deepcopy(attempts.items)
    value = RunExecution.model_validate(project_run_execution(last(attempts), UID, service.stream))
    assert value.inputs and value.inputs[-1].new_messages[0].quote == msg.content
    assert value.suggestions[0].action == value.decisions[0].action == 'review'
    assert value.suggestions[0].basis[0].quote
    assert value.commit_status == 'committed' and value.processed == 1 and value.writes == []
    assert attempts.items == before and len(provider.calls) == 1


def test_proposed_write_is_not_reported_as_saved_without_receipt(tmp_path):
    service, attempts, *_ = setup(tmp_path)
    service.run_window(UID, window(1), execution=dict(run_id='synthetic-run', window_index=0))
    record = deepcopy(last(attempts))
    record.update(receipt=None, outcome='not_committed')
    value = RunExecution.model_validate(project_run_execution(record, UID, service.stream))
    assert value.suggestions[0].action == 'new' and value.decisions[0].event_id
    assert value.commit_status == 'not_committed' and value.processed is None and not value.writes
    record['receipt'] = {'version': 1, 'kind': 'analysis', 'cycle': {}, 'writes': [], 'processed_versions': []}
    assert project_run_execution(record, UID, service.stream)['commit_status'] == 'invalid'


def test_window_route_requires_matching_customer_stream_and_valid_window(api):
    client, repository, _, app = api
    run = client.post('/api/v1/runs', json={'uid': TEST_UID}).json()
    calls = []
    def query(*args):
        calls.append(args)
        return dict(items=[], available=True, total=0, next_offset=None)
    app.state.services.queries.run_executions = query
    path = f"/api/v1/runs/{run['run_id']}/executions"
    params = dict(uid=TEST_UID, stream=TEST_STREAM, window_index=0)
    assert client.get(path, params=params).status_code == 200
    assert calls == [(run['run_id'], TEST_UID, TEST_STREAM, 0, 0)]
    for field, value in [('uid', 'synthetic-other'), ('stream', 'other'), ('window_index', run['total_windows'])]:
        assert client.get(path, params={**params, field: value}).status_code == 404
    assert client.get(path, params={**params, 'window_index': -1}).status_code == 422
    assert client.get(path, params={'uid': TEST_UID, 'window_index': 0}).status_code == 422
    assert len(calls) == 1


def test_projection_keeps_customer_scope_and_reports_missing_receipt(tmp_path):
    service, attempts, *_ = setup(tmp_path)
    service.run_window(UID, window(1))
    record = deepcopy(last(attempts))
    record['receipt'] = None
    record['outcome'] = 'committed'
    record['stages'] += [
        dict(stage='history', status='completed', payload=dict(candidates=[
            dict(event_id='synthetic-other-event', uid='synthetic-other'),
            dict(event_id='synthetic-current-event', uid=UID)])),
        dict(stage='history_context', status='completed', payload=dict(result=dict(
            uid='synthetic-other', items=[dict(message_id='synthetic-other-message')]))),
        dict(stage='suggestions', status='completed', payload=dict(uid='synthetic-other', suggestions=[
            dict(value=dict(summary='虚构其他客户的建议'))])),
    ]
    before = deepcopy(record)
    value = RunExecution.model_validate(project_run_execution(record, UID, service.stream))
    assert value.commit_status == 'missing' and not value.writes
    assert [c['event_id'] for h in value.histories for c in h.candidates] == ['synthetic-current-event']
    assert not value.contexts
    assert all(s.summary != '虚构其他客户的建议' for s in value.suggestions)
    assert record == before
