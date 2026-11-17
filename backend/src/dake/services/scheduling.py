"""从选定起点持续编排完整窗口；复用持久队列，不在此执行分析或事件写入。"""

from dataclasses import replace
from datetime import datetime, timedelta

from ..config import bound, SCHEDULE_INTERVAL, SCHEDULE_RETRY_DELAYS
from ..analysis.group_matching import group_matching_version
from ..domain.models import TZ, parse_time
from ..jobs.runner import prepare_request, restore_settings
from ..repositories.schedules import ScheduleRepository
from .scheduled_customers import FileCustomerSource


def window_end(start, now, interval):
    """窗口由原始起点连续推进，未满一个周期时等待，不额外延迟取数。"""
    end = start + interval
    return end if end <= now else None


def completion(schedule, run, attempt, now, retry_delays=SCHEDULE_RETRY_DELAYS):
    """纯状态转换便于故障注入；收据不明绝不自动重跑，业务待确认不算失败。"""
    if run["status"] in {"queued", "running"}:
        return {}
    request = run["request"]
    if ((run["uid"], request.get("analysis_stream"), request.get("schedule_id"), request["start"]) !=
            (schedule["uid"], schedule["stream"], schedule["schedule_id"], schedule["next_start"])):
        return dict(status="paused", error="任务范围与调度进度不一致，须人工检查")
    base = dict(active_run_id=None, last_run_id=run["run_id"])
    if attempt.get("outcome") in {"running", "commit_unknown"}:
        return dict(base, status="needs_verification", retry_attempt_id=attempt.get("attempt_id"),
                    retry_at=None, error="执行提交结果待核实，已暂停该客户")
    if run["status"] == "succeeded" and run["completed_windows"] == 1:
        if attempt.get("outcome") != "committed" or not attempt.get("receipt"):
            return dict(base, status="needs_verification", retry_at=None,
                        retry_attempt_id=attempt.get("attempt_id"), error="完成记录缺少已确认提交收据，须核实")
        return dict(base, next_start=request["end"], retry_count=0, retry_at=None,
                    retry_attempt_id=None, error=None, last_success=now.isoformat())
    kind = request.get("execution_error_kind", "unknown")
    if not attempt and kind == "interrupted":
        return dict(base, retry_at=None, error=None)
    delivery = attempt.get("outcome") == "committed" and bool(attempt.get("receipt"))
    retryable = delivery or (kind == "transient" and attempt.get("outcome") == "not_committed")
    retry_count = schedule["retry_count"]
    if retryable and retry_count < len(retry_delays):
        finished = parse_time(run["finished_at"]) if run.get("finished_at") else now
        return dict(base, retry_count=retry_count + 1,
                    retry_at=(finished + timedelta(seconds=retry_delays[retry_count])).isoformat(),
                    retry_attempt_id=attempt["attempt_id"],
                    error="业务已提交，等待恢复展示" if delivery else "临时错误，等待有限重试")
    return dict(base, status="paused", retry_at=None,
                retry_attempt_id=attempt.get("attempt_id") or schedule.get("retry_attempt_id"),
                error="有限重试次数已用尽，等待处理" if retryable else "处理遇到非临时错误，等待检查配置或数据")


class SchedulingService:
    """名单适配器可以注入；API、命令行和内置触发器共用相同编排入口。"""

    def __init__(self, settings, *, repository=None, customer_source=None, clock=None, service_factory=None):
        self.settings = settings
        self.repository = repository or ScheduleRepository(settings)
        self.customer_source = customer_source or FileCustomerSource(settings.data_dir)
        self.clock = clock or (lambda: datetime.now(TZ))
        self.service_factory = service_factory

    def configure(self, start_date):
        """只接收一个开始日期，后续结束时间随完整窗口移动；先验证上游名单。"""
        start = bound(start_date)
        if len(start_date) != 10 or start.strftime("%Y-%m-%d") != start_date:
            raise ValueError("开始日期必须为 YYYY-MM-DD")
        try:
            customers = self.customer_source.load()
        except (OSError, ValueError, TypeError):
            raise ValueError("客户名单尚未就绪或不完整，请先对接名单再开始定时处理") from None
        interval = SCHEDULE_INTERVAL
        frozen = replace(self.settings, start=start, end=start + interval, interval=interval)
        template, _ = prepare_request(frozen, dict(start=start.isoformat(), end=(start + interval).isoformat(),
                                                 offline=False))
        template.pop("uid")
        template.update(business_start=start.isoformat(), schedule_retry_delays=list(self.settings.schedule_retry_delays))
        with self.repository.orchestration() as acquired:
            if not acquired:
                raise ValueError("调度正在同步，请稍后重试")
            self.repository.configure(start_date, template)
            self.repository.sync(customers, self.repository.control())
        return self.status()

    def tick(self, now=None):
        """每次只为每个可用客户排入一个窗口；队列满后保留顺序，下一次继续。"""
        now = now or self.clock()
        if now.tzinfo is None:
            raise ValueError("调度时间须带时区")
        now = now.astimezone(TZ)
        enqueued = 0
        with self.repository.orchestration() as acquired:
            if not acquired:
                return 0
            control = self.repository.control()
            if not control:
                return 0
            try:
                customers = self.customer_source.load()
            except (OSError, ValueError, TypeError):
                # 上游失败保留旧状态，但暂停新增任务；已提交的任务仍正常执行和对账。
                self.repository.observed(now, "客户名单读取失败或不完整，本轮未新增任务；原进度已保留")
                customers = None
            else:
                self.repository.sync(customers, control)
                self.repository.observed(now)
            for schedule in self.repository.schedules(ready_at=now):
                if schedule["active_run_id"]:
                    run = self.repository.get(schedule["active_run_id"], internal=True)
                    if not run:
                        self.repository.update(schedule["schedule_id"], status="paused", error="关联任务缺失，须人工检查")
                        continue
                    changes = completion(schedule, run, self.repository.attempt(schedule, run), now,
                                         tuple(schedule["template"]["schedule_retry_delays"]))
                    if changes:
                        self.repository.update(schedule["schedule_id"], expected_run=run["run_id"], **changes)
                    # 已完成的客户本轮不抢先续排，让上一轮尚未入队的客户先获得机会。
                    continue
                if customers is None or not schedule["enabled"] or schedule["status"] != "active":
                    continue
                if schedule["template"].get("group_matching_version") != group_matching_version():
                    self.repository.update(schedule["schedule_id"], status="paused", error="处理策略已变化，请迁移调度配置后再恢复")
                    continue
                if schedule["retry_at"] and parse_time(schedule["retry_at"]) > now:
                    continue
                start = parse_time(schedule["next_start"])
                end = window_end(start, now, SCHEDULE_INTERVAL)
                if end is None:
                    continue
                request = dict(schedule["template"], uid=schedule["uid"], start=start.isoformat(), end=end.isoformat(),
                               schedule_id=schedule["schedule_id"], scheduled_retry_of=schedule["retry_attempt_id"])
                if self.repository.enqueue(schedule, request, now):
                    enqueued += 1
        return enqueued

    def status(self):
        """状态读取无取数、重试或模型副作用，空客户也能显示独立调度进度。"""
        control = self.repository.control()
        rows = self.repository.schedules()
        items = [{k: v for k, v in row.items() if k not in {"template", "retry_attempt_id"}} for row in rows]
        now = self.clock()
        for item in items:
            item["pending_windows"] = max(0, (now - parse_time(item["next_start"])) // SCHEDULE_INTERVAL)
            item["phase"] = ("disabled" if not item["enabled"] else item["status"] if item["status"] != "active" else
                             "queued" if item["active_run_id"] else "retry_wait" if item["retry_at"] else
                             "catching_up" if item["pending_windows"] else "waiting")
        return dict(configured=bool(control), start_date=control["start_date"] if control else None,
                    last_tick=control.get("last_tick") if control else None,
                    source_error=control.get("source_error") if control else None,
                    worker_enabled=self.settings.schedule_enabled, items=items)

    def control_customer(self, schedule_id, action):
        """暂停或显式恢复；恢复待核实执行先复用原核实入口，不发送模型请求。"""
        with self.repository.orchestration() as acquired:
            if not acquired:
                raise ValueError("调度正在同步，请稍后重试")
            row = self.repository.get_schedule(schedule_id)
            if row is None:
                raise ValueError("未找到客户调度记录")
            if action == "pause":
                self.repository.update(schedule_id, status="paused", error="已手动暂停")
            elif action == "resume":
                if row["template"].get("group_matching_version") != group_matching_version():
                    raise ValueError("处理策略已变化，请先迁移调度配置")
                if row["status"] == "needs_verification":
                    if not row["retry_attempt_id"]:
                        raise ValueError("执行记录缺失，不能自动解除核实状态")
                    from ..bootstrap import build_service
                    from .executions import verify_attempt
                    request = dict(row["template"], uid=row["uid"], schedule_id=schedule_id,
                        start=row["next_start"], end=(parse_time(row["next_start"]) + SCHEDULE_INTERVAL).isoformat())
                    settings = restore_settings(self.settings, request)
                    with (self.service_factory or build_service)(settings, offline=False) as service:
                        verify_attempt(service, row["uid"], row["retry_attempt_id"])
                self.repository.update(schedule_id, status="active", retry_count=0, retry_at=None, error=None)
            else:
                raise ValueError("无效调度操作")
        return self.status()
