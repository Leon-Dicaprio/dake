"""定时处理的独立 MySQL 验收，禁止默认配置、真实客户和外部模型。"""

from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from dake.domain.models import Candidate, Message, parse_time
from dake.ingestion.client import TransientChatRecordsError
from dake.jobs.runner import RunRunner
from dake.repositories.attempts import AttemptRepository
from dake.repositories.mysql import MySQLStore, StorageError
from dake.repositories.schedules import ScheduleRepository
from dake.services.processing import IncrementalService
from dake.services.scheduled_customers import ScheduledCustomer
from dake.services.scheduling import SchedulingService
from fakes import FakeProvider, FakeSource
from test_execution_mysql import explicit_isolation

pytestmark = pytest.mark.isolated_mysql


@pytest.fixture
def scheduled(explicit_isolation, tmp_path, monkeypatch):
    target = explicit_isolation
    clock = [parse_time("2038-06-01T01:00:00")]
    settings = target.settings(tmp_path, uid="synthetic-scheduler", start=parse_time("2038-06-01"),
                               end=parse_time("2038-06-02"))
    customers = [ScheduledCustomer("synthetic-mysql-schedule-" + uuid4().hex) for _ in range(2)]
    original_uids = {c.uid for c in customers}
    class Source:
        failed = False
        def load(self):
            if self.failed:
                raise ValueError("合成名单失败")
            return list(customers)
    upstream = Source()
    repository = ScheduleRepository(settings)
    service = SchedulingService(settings, repository=repository, customer_source=upstream)
    messages, provider = FakeSource(), FakeProvider(name="stub-v1")
    @contextmanager
    def factory(configuration, **kwargs):
        store = MySQLStore(**target.options())
        try:
            yield IncrementalService(store, messages, provider, configuration, attempts=AttemptRepository(configuration))
        finally:
            store.close()
    runner = RunRunner(settings, repository, service_factory=factory)
    monkeypatch.setattr("dake.repositories.runs._now", lambda: clock[0].replace(tzinfo=None))
    service.configure("2038-06-01")
    def run_one():
        run = repository.claim_next(runner.runner_id)
        assert run is not None
        runner.execute(run)
        return repository.get(run["run_id"], internal=True)
    try:
        yield SimpleNamespace(settings=settings, customers=customers, upstream=upstream, repository=repository,
                              service=service, clock=clock, messages=messages, provider=provider, runner=runner,
                              run_one=run_one, factory=factory, target=target)
    finally:
        with repository.connection() as store:
            for uid in original_uids | {c.uid for c in customers}:
                store._execute("DELETE FROM processing_schedules WHERE uid=%s", (uid,))
                store._execute("DELETE FROM processing_runs WHERE uid=%s", (uid,))


def test_round_robin_empty_windows_restart_and_duplicate_tick(scheduled):
    env = scheduled
    assert env.service.tick(env.clock[0]) == 2
    assert env.service.tick(env.clock[0]) == 0
    a, b = env.run_one(), env.run_one()
    assert a["uid"] != b["uid"] and a["cycles"][0]["processed"] == 0
    assert a["status"] == b["status"] == "succeeded"
    env.service.tick(env.clock[0])
    cursor = [r["next_start"] for r in env.repository.schedules()]
    assert cursor == ["2038-06-01T00:15:00+08:00"] * 2
    restarted = SchedulingService(env.settings, repository=ScheduleRepository(env.settings), customer_source=env.upstream)
    restarted.configure("2038-06-01")
    assert restarted.tick(env.clock[0]) == 2
    assert {r["request"]["start"] for r in (env.run_one(), env.run_one())} == set(cursor)
    assert not env.provider.calls


def test_late_and_edited_message_before_task_start_is_processed_once(scheduled):
    env = scheduled
    env.service.tick(env.clock[0]); env.run_one(); env.run_one(); env.service.tick(env.clock[0])
    uid = env.customers[0].uid
    msg = Message(uid, "synthetic-late", parse_time("2038-06-01T00:10:00"), "虚构事项需要排查")
    env.messages.messages.append(msg)
    env.provider.mapping[msg.message_id] = Candidate("排障", "synthetic-late", "虚构排查事项", [msg.message_id])
    env.service.tick(env.clock[0])
    results = [env.run_one(), env.run_one()]
    late = next(r for r in results if r["uid"] == uid)
    assert late["cycles"][0]["processed"] == 1 and len(late["cycles"][0]["created"]) == 1
    env.service.tick(env.clock[0]); env.service.tick(env.clock[0])
    repeat = [env.run_one(), env.run_one()]
    assert all(r["cycles"][0]["processed"] == 0 for r in repeat)
    env.messages.messages[0] = replace(msg, content="虚构事项补充新的排查信息")
    env.service.tick(env.clock[0]); env.service.tick(env.clock[0])
    edited = [env.run_one(), env.run_one()]
    assert next(r for r in edited if r["uid"] == uid)["cycles"][0]["processed"] == 1


def test_snapshot_failure_and_explicit_disable_preserve_progress(scheduled):
    env = scheduled
    env.upstream.failed = True
    assert env.service.tick(env.clock[0]) == 0
    assert all(r["enabled"] for r in env.repository.schedules())
    assert env.service.status()["source_error"]
    env.upstream.failed = False
    env.customers[0] = replace(env.customers[0], enabled=False)
    assert env.service.tick(env.clock[0]) == 1
    rows = env.repository.schedules()
    disabled = next(r for r in rows if not r["enabled"])
    assert disabled["next_start"] == disabled["business_start"] and not disabled["active_run_id"]


def test_transient_retry_budget_is_durable_and_other_customer_continues(scheduled, monkeypatch):
    env = scheduled
    failed_uid = env.customers[0].uid
    original = env.messages.load_day
    def fail(uid, day):
        if uid == failed_uid:
            raise TransientChatRecordsError("虚构临时连接失败")
        return original(uid, day)
    monkeypatch.setattr(env.messages, "load_day", fail)
    for index in range(4):
        env.service.tick(env.clock[0])
        while True:
            run = env.repository.claim_next(env.runner.runner_id)
            if run is None:
                break
            env.runner.execute(run)
        env.service.tick(env.clock[0])
        row = next(r for r in env.repository.schedules() if r["uid"] == failed_uid)
        assert row["next_start"] == row["business_start"]
        if index < 3:
            assert row["retry_count"] == index + 1 and row["status"] == "active"
            env.clock[0] = parse_time(row["retry_at"])
        else:
            assert row["status"] == "paused" and row["retry_count"] == 3
    restarted = SchedulingService(env.settings, repository=ScheduleRepository(env.settings), customer_source=env.upstream)
    restarted.tick(env.clock[0] + timedelta(days=1))
    paused = next(r for r in env.repository.schedules() if r["uid"] == failed_uid)
    assert paused["status"] == "paused" and paused["retry_count"] == 3
    other = next(r for r in env.repository.schedules() if r["uid"] != failed_uid)
    assert other["next_start"] > other["business_start"]


def test_queue_binding_is_atomic_when_schedule_update_fails(scheduled, monkeypatch):
    env = scheduled
    original = MySQLStore._execute
    def fail(self, sql, args=()):
        if sql.startswith("UPDATE processing_schedules SET active_run_id="):
            raise StorageError("虚构绑定失败")
        return original(self, sql, args)
    monkeypatch.setattr(MySQLStore, "_execute", fail)
    with pytest.raises(StorageError):
        env.service.tick(env.clock[0])
    with env.repository.connection() as store:
        rows, _ = store._execute("SELECT run_id FROM processing_runs WHERE uid=%s", (env.customers[0].uid,))
    assert rows == []
    assert all(r["active_run_id"] is None for r in env.repository.schedules())


def test_committed_progress_failure_restores_without_calling_provider_again(scheduled, monkeypatch):
    env = scheduled
    msg = Message(env.customers[0].uid, "synthetic-committed", parse_time("2038-06-01T00:01:00"), "虚构需排查事项")
    env.messages.messages.append(msg)
    env.provider.mapping[msg.message_id] = Candidate("排障", "synthetic-committed", "虚构需排查事项", [msg.message_id])
    original = env.repository.complete_window
    def fail(run_id, runner_id, cycle):
        if cycle["uid"] == msg.uid:
            raise StorageError("虚构进度保存失败")
        return original(run_id, runner_id, cycle)
    monkeypatch.setattr(env.repository, "complete_window", fail)
    env.service.tick(env.clock[0]); env.run_one(); env.run_one(); env.service.tick(env.clock[0])
    row = next(r for r in env.repository.schedules() if r["uid"] == msg.uid)
    calls = len(env.provider.calls)
    assert row["retry_attempt_id"] and row["retry_at"]
    monkeypatch.setattr(env.repository, "complete_window", original)
    env.clock[0] = parse_time(row["retry_at"])
    env.service.tick(env.clock[0])
    while True:
        run = env.repository.claim_next(env.runner.runner_id)
        if run is None:
            break
        env.runner.execute(run)
    env.service.tick(env.clock[0])
    assert len(env.provider.calls) == calls
    recovered = next(r for r in env.repository.schedules() if r["uid"] == msg.uid)
    assert recovered["next_start"] == "2038-06-01T00:15:00+08:00"


def test_pause_and_manual_resume_keep_origin_and_do_not_touch_other_customers(scheduled):
    env = scheduled
    row = env.repository.schedules()[0]
    env.service.control_customer(row["schedule_id"], "pause")
    assert env.service.tick(env.clock[0]) == 1
    paused = env.repository.get_schedule(row["schedule_id"])
    assert paused["status"] == "paused" and paused["next_start"] == row["business_start"]
    restarted = SchedulingService(env.settings, repository=ScheduleRepository(env.settings), customer_source=env.upstream)
    restarted.configure("2038-06-01")
    assert restarted.repository.get_schedule(row["schedule_id"])["status"] == "paused"
    restarted.control_customer(row["schedule_id"], "resume")
    assert restarted.tick(env.clock[0]) == 1
    with pytest.raises(ValueError):
        restarted.configure("2038-06-02")


def test_shared_manual_queue_prevents_duplicate_scheduled_customer(scheduled):
    env = scheduled
    row = env.repository.schedules()[0]
    request = dict(row["template"], uid=row["uid"])
    manual = env.repository.create(request, 1)
    assert env.service.tick(env.clock[0]) == 1
    assert env.repository.get_schedule(row["schedule_id"])["active_run_id"] is None
    assert env.repository.get(manual["run_id"])["status"] == "queued"


def test_queue_limit_does_not_starve_customers_that_missed_first_round(scheduled):
    env = scheduled
    env.customers[:] = [ScheduledCustomer("synthetic-mysql-schedule-" + uuid4().hex) for _ in range(36)]
    assert env.service.tick(env.clock[0]) == 32
    waiting = {r["uid"] for r in env.repository.schedules() if r["enabled"] and not r["active_run_id"]}
    assert len(waiting) == 4
    for _ in range(32):
        env.run_one()
    env.clock[0] += timedelta(seconds=1)
    assert env.service.tick(env.clock[0]) == 4
    received = {r["uid"] for r in env.repository.schedules() if r["active_run_id"]}
    assert waiting <= received


def test_unknown_commit_blocks_until_explicit_verification_then_restores_only(scheduled, monkeypatch):
    env = scheduled
    # 用真实已提交收据模拟提交确认丢失；不改变原业务数据或阶段证据。
    from dake.repositories.attempts import AttemptRepository, DeliveryError
    confirm = AttemptRepository.confirm_commit
    failed_uid = env.customers[0].uid
    def fail(self, uid, stream, attempt_id):
        if uid == failed_uid:
            raise DeliveryError("虚构提交确认丢失")
        return confirm(self, uid, stream, attempt_id)
    monkeypatch.setattr(AttemptRepository, "confirm_commit", fail)
    env.service.tick(env.clock[0]); env.run_one(); env.run_one(); env.service.tick(env.clock[0])
    row = next(r for r in env.repository.schedules() if r["uid"] == failed_uid)
    assert row["status"] == "needs_verification" and row["retry_count"] == 0
    env.service.tick(env.clock[0] + timedelta(hours=1))
    assert env.repository.get_schedule(row["schedule_id"])["active_run_id"] is None
    monkeypatch.setattr(AttemptRepository, "confirm_commit", confirm)
    env.service.service_factory = env.factory
    env.service.control_customer(row["schedule_id"], "resume")
    env.service.tick(env.clock[0])
    while True:
        run = env.repository.claim_next(env.runner.runner_id)
        if run is None:
            break
        env.runner.execute(run)
    env.service.tick(env.clock[0])
    restored = env.repository.get_schedule(row["schedule_id"])
    assert restored["next_start"] == "2038-06-01T00:15:00+08:00"
