"""存储测试只使用自造消息及随机客户 ID，不读写真实客户的测试期望值。"""

from dataclasses import replace
from datetime import timedelta
import os
from pathlib import Path
from threading import Event as ThreadEvent, Thread
from uuid import uuid4

from dotenv import dotenv_values
import pytest

from dake.domain.models import Event, Message, parse_time
from dake.repositories.mysql import MySQLStore, StorageError


def test_remote_database_is_rejected_before_connecting():
    for host in ("10.210.32.31", "example.invalid"):
        with pytest.raises(ValueError, match="仅允许连接本机"):
            MySQLStore(host, 3307, "unused", "unused", "unused")


@pytest.fixture
def mysql_store():
    if os.environ.get("RUN_MYSQL_TESTS") != "1":
        pytest.skip("set RUN_MYSQL_TESTS=1 after starting the project MySQL")
    env = {**dotenv_values(Path(__file__).parents[2] / ".env"), **os.environ}
    options = dict(
        host=env.get("MYSQL_HOST", "127.0.0.1"),
        port=int(env.get("MYSQL_PORT", "3307")),
        user=env.get("MYSQL_USER", "dake"),
        password=env.get("MYSQL_PASSWORD", ""),
        database=env.get("MYSQL_DATABASE", "dake_aftersales"),
    )
    store = MySQLStore(**options)
    store.init_schema()
    uid = "test-store-" + uuid4().hex
    other_uid = uid + "-other"
    try:
        yield store, uid, other_uid, options
    finally:
        # 只删除当前测试生成的随机客户，避免清空数据库或影响真实客户数据。
        cleanup = MySQLStore(**options)
        for owned_uid in (uid, other_uid):
            with cleanup.transaction(owned_uid):
                cleanup._execute("DELETE FROM events WHERE uid=%s", (owned_uid,))
                cleanup._execute("DELETE FROM messages WHERE uid=%s", (owned_uid,))
        cleanup.close()
        store.close()


def fake_message(uid, *, time="2026-11-08T10:00:00+08:00", **overrides):
    values = dict(
        uid=uid,
        message_id=str(uuid4().int),
        sent_at=parse_time(time),
        content="自造测试消息：示例资源需要检查 🧪",
        source="test_store",
        conversation_id="synthetic-room",
        sender_name="合成测试人员",
    )
    values.update(overrides)
    return Message(**values)


def fake_event(uid, message):
    return Event(
        event_id=str(uuid4()), uid=uid, stream="test:v1", type="排障",
        topic_key="synthetic-resource", start_time=message.sent_at,
        end_time=message.sent_at, status="未知", severity="未知",
        summary="自造测试事件", created_on=message.sent_at,
        evidence=[{"message_id": message.message_id, "send_time": message.sent_at.isoformat()}],
        updated_by=[{"action": "created", "message_ids": [message.message_id]}],
    )


@pytest.mark.mysql
def test_upsert_pending_streams_and_changed_message(mysql_store):
    store, uid, _, _ = mysql_store
    message = fake_message(uid)
    start, end = parse_time("2026-11-08"), parse_time("2026-11-09")
    with store.transaction(uid):
        assert store.upsert_messages([message]) == 1
        assert store.upsert_messages([message]) == 0
        assert store.pending_messages(uid, start, end, "test:v1") == [message]
        store.mark_processed([message], "test:v1")
    assert store.pending_messages(uid, start, end, "test:v1") == []
    assert store.pending_messages(uid, start, end, "test:v2") == [message]
    assert store.latest_message(uid, end, "test:v1") == message
    assert store.latest_message(uid, end, "test:v2") is None
    corrected = replace(message, content="自造测试修订：补充范围 🧪")
    with store.transaction(uid):
        assert store.upsert_messages([corrected]) == 1
    assert store.pending_messages(uid, start, end, "test:v1") == [corrected]
    assert store.context_messages(uid, start, end) == [corrected]
    assert store.latest_message(uid, end, "test:v1") is None


@pytest.mark.mysql
def test_half_open_boundaries_sorting_and_uid_isolation(mysql_store):
    store, uid, other_uid, _ = mysql_store
    base = uuid4().int * 100
    first = fake_message(uid, message_id=str(base + 2), time="2026-11-08T10:00:00+08:00")
    second = fake_message(uid, message_id=str(base + 10), time="2026-11-08T10:00:00+08:00")
    end_message = fake_message(uid, time="2026-11-08T10:15:00+08:00")
    outsider = fake_message(other_uid)
    with store.transaction(uid):
        store.upsert_messages([end_message, second, first])
    with store.transaction(other_uid):
        store.upsert_messages([outsider])
    start, end = first.sent_at, end_message.sent_at
    assert store.pending_messages(uid, start, end, "test:v1") == [first, second]
    assert store.context_messages(uid, start, end) == [first, second]
    assert store.latest_message(uid, end) == second
    assert store.latest_message(uid, end + timedelta(seconds=1)) == end_message


@pytest.mark.mysql
def test_event_and_processing_marks_roll_back_together(mysql_store):
    store, uid, _, _ = mysql_store
    message = fake_message(uid)
    event = fake_event(uid, message)
    with store.transaction(uid):
        store.upsert_messages([message])
    with pytest.raises(RuntimeError, match="synthetic failure"):
        with store.transaction(uid):
            store.save_event(event)
            store.mark_processed([message], event.stream)
            raise RuntimeError("synthetic failure")
    assert store.list_events(uid, event.stream) == []
    assert store.pending_messages(uid, parse_time("2026-11-08"), parse_time("2026-11-09"), event.stream) == [message]
    with store.transaction(uid):
        store.save_event(event)
        store.mark_processed([message], event.stream)
    assert store.list_events(uid, event.stream) == [event]
    updated = replace(event, end_time=event.end_time + timedelta(days=3), summary="自造进展")
    with store.transaction(uid):
        store.save_event(updated)
    assert store.list_events(uid, event.stream) == [updated]


@pytest.mark.mysql
def test_collisions_and_transaction_requirements(mysql_store):
    store, uid, other_uid, _ = mysql_store
    message = fake_message(uid)
    event = fake_event(uid, message)
    with pytest.raises(StorageError, match="transaction"):
        store.upsert_messages([message])
    with store.transaction(uid):
        store.upsert_messages([message])
        store.save_event(event)
        with pytest.raises(StorageError, match="嵌套"):
            with store.transaction(uid):
                pass
    with pytest.raises(StorageError, match="其他客户"):
        with store.transaction(other_uid):
            store.upsert_messages([replace(message, uid=other_uid)])
    with pytest.raises(StorageError, match="其他客户"):
        with store.transaction(other_uid):
            store.save_event(replace(event, uid=other_uid))
    assert store.list_events(other_uid, event.stream) == []
    assert store.list_events(uid, "another-stream") == []


@pytest.mark.mysql
def test_customer_lock_serializes_connections(mysql_store):
    store, uid, _, options = mysql_store
    waiting = ThreadEvent()
    entered = ThreadEvent()
    errors = []

    def worker():
        other = MySQLStore(**options)
        try:
            waiting.set()
            with other.transaction(uid):
                entered.set()
        except BaseException as error:
            errors.append(error)
        finally:
            other.close()

    with store.transaction(uid):
        thread = Thread(target=worker)
        thread.start()
        assert waiting.wait(5)
        assert not entered.wait(0.2)
    thread.join(5)
    assert not thread.is_alive()
    assert entered.is_set()
    assert errors == []
