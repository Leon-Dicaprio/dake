"""验证 CLI 与后台共用的范围回放、续跑和资源装配，输入均为合成消息。"""

from dataclasses import replace
from datetime import timedelta

import pytest

from dake.bootstrap import build_service
from dake.config import PROJECT_ROOT, Settings, bound
from dake.domain.models import Message
from dake.services.processing import IncrementalService
from dake.services.replay import ReplayService
from fakes import FakeProvider, FakeSource, MemoryStore


def make_service(tmp_path):
    uid = "synthetic-service-customer"
    settings = replace(Settings(), uid=uid, data_dir=tmp_path, end=bound("2026-11-09"))
    messages = [Message(uid, "301", bound("2026-11-08T00:02:00"), "合成第一轮消息", conversation_id="synthetic-service-room"),
                Message(uid, "302", bound("2026-11-08T00:17:00"), "合成第二轮消息", conversation_id="synthetic-service-room")]
    from test_attribution import candidate as attributed, AttributionProvider
    provider = AttributionProvider({"301": attributed(messages[0]),
        "302": lambda new, context, events: attributed(messages[1], "update", events[0].event_id, [messages[0]])})
    service = IncrementalService(MemoryStore(), FakeSource(messages), provider, settings)
    return service, ReplayService(service)


def test_range_replay_yields_each_completed_window_without_loading_future_input(tmp_path):
    service, replay = make_service(tmp_path)
    results = replay.run_range(service.settings.uid, service.settings.start,
                              bound("2026-11-08T00:30:00"), timedelta(minutes=15))
    assert not service.provider.calls
    first = next(results)
    assert len(first.created) == 1
    assert [m.message_id for m in service.store.messages.values()] == ["301"]
    second = next(results)
    assert second.updated == first.created
    with pytest.raises(StopIteration):
        next(results)


def test_run_next_reuses_cursor_and_explicit_replay_does_not_move_it_back(tmp_path):
    service, replay = make_service(tmp_path)
    uid, start = service.settings.uid, service.settings.start
    end, interval = bound("2026-11-08T00:30:00"), timedelta(minutes=15)
    first = replay.run_next(uid, start, end, interval)
    second = replay.run_next(uid, start, end, interval)
    assert first.window.end == second.window.start
    assert second.updated == first.created
    assert replay.run_next(uid, start, end, interval) is None
    repeated = replay.run_next(uid, start, end, interval, resume=False)
    assert repeated.window == first.window
    assert repeated.created == repeated.updated == []
    assert service.state.read(uid, service.stream)["next_start"] == end.isoformat()


def test_reading_history_uses_saved_changes_without_processing_again(tmp_path):
    service, replay = make_service(tmp_path)
    args = (service.settings.uid, service.settings.start, bound("2026-11-08T00:30:00"), timedelta(minutes=15))
    original = list(replay.run_range(*args))
    list(replay.run_range(*args))
    calls = len(service.provider.calls)
    history = list(replay.history_range(*args))
    assert len(service.provider.calls) == calls
    assert [result.created for result in history] == [result.created for result in original]
    assert [result.updated for result in history] == [result.updated for result in original]


def test_bootstrap_keeps_configured_identity_and_closes_connection_on_failure(monkeypatch):
    stores = []

    class ResourceStore(MemoryStore):
        def __init__(self, **kwargs):
            super().__init__()
            self.closed = False
            stores.append(self)

        def close(self):
            self.closed = True

    monkeypatch.setattr("dake.bootstrap.MySQLStore", ResourceStore)
    settings = replace(Settings(), uid="synthetic-service-customer", data_dir=PROJECT_ROOT / "data")
    with pytest.raises(RuntimeError, match="合成中断"):
        with build_service(settings, offline=True) as service:
            assert service.settings.uid == settings.uid
            assert service.settings.start == bound("2026-11-08")
            assert service.settings.end == bound("2026-11-12", end=True)
            assert service.stream == "stub-v1"
            raise RuntimeError("合成中断")
    assert stores[0].closed
