"""工作台客户列表只来自实际记录，配置默认客户不注入展示。"""
import pytest

from dake.config import Settings
from dake.domain.models import Event, parse_time
from dake.services.manual_decisions import ManualDecisionService
from dake.services.queries import QueryService


class EmptyStore:
    def __init__(self, **kwargs): pass
    def _execute(self, sql, args=()): return [], 0
    def close(self): pass


def test_empty_database_does_not_inject_default_customer():
    result = QueryService(Settings(uid='synthetic-default'), store_factory=EmptyStore).config()
    assert result['customers'] == []


def test_real_default_customer_has_no_special_sample_label():
    class RealStore(EmptyStore):
        def _execute(self, sql, args=()):
            if 'FROM messages' in sql and 'GROUP BY uid' in sql:
                return [{'uid': 'synthetic-default', 'total': 1}], 1
            return [], 0
    result = QueryService(Settings(uid='synthetic-default'), store_factory=RealStore).config()
    assert len(result['customers']) == 1
    assert result['customers'][0]['label'] == '客户 synthetic-default'


def test_archived_events_are_counted_and_read_only_within_their_customer(tmp_path):
    uid, archive = 'synthetic-customer', 'xhub-v1-' + 'a' * 20
    stamp = parse_time('2038-01-01 10:00:00')
    event = Event('synthetic-event', uid, archive, '排障', None, stamp, stamp, '未知', '未知', '合成事项', stamp)

    class SavedStore(EmptyStore):
        def _execute(self, sql, args=()):
            if 'FROM messages' in sql and 'GROUP BY uid' in sql:
                return [dict(uid=uid, total=1)], 1
            if 'GROUP BY uid,stream' in sql:
                return [dict(uid=uid, stream=s, total=1, latest_end=stamp) for s in [archive, 'stub-v1']], 2
            return [], 0

        def list_events(self, requested_uid, stream):
            return [event] if (requested_uid, stream) == (uid, archive) else []

    settings = Settings(provider='xhub', uid=uid, data_dir=tmp_path)
    queries = QueryService(settings, store_factory=SavedStore)
    customer = queries.config()['customers'][0]
    assert customer['event_count'] == 0 and customer['archived_event_counts'] == {archive: 1}
    assert queries.events(uid)['total'] == 0
    assert queries.event(event.event_id, uid, archive)['stream'] == archive
    assert queries.event_changes(event.event_id, 'synthetic-other', archive, None) is None
    with pytest.raises(ValueError):
        queries.events(uid, 'stub-v1')
    with pytest.raises(ValueError):
        ManualDecisionService(settings, store_factory=SavedStore).scope(uid, archive)
