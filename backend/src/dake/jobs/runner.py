"""本地持久任务执行器：单工作线程、跨进程执行锁、逐周期保存可见进度。"""

from dataclasses import asdict, replace
from datetime import timedelta
import math
import threading
from time import monotonic
from uuid import uuid4

from ..bootstrap import build_service
from ..analysis.providers.xhub import XHubError, XHubTransientError, configured_stream
from ..ingestion.client import TransientChatRecordsError
from ..analysis.attribution import attribution_version
from ..analysis.group_matching import group_matching_version
from ..config import API_MAX_RANGE_DAYS, API_MAX_WINDOWS, HistoryContextSettings, HistoryRetrievalSettings, bound, duration
from ..domain.models import parse_time, windows
from ..ingestion.client import validate_uid
from ..repositories.attempts import AttemptError, AttemptPendingVerification, DeliveryError
from ..services.queries import duration_label
from ..services.replay import ReplayService


class RunInterrupted(RuntimeError):
    """服务关闭或失去执行锁时停止继续处理下一周期。"""


def compact_progress(payload):
    """任务进度只带本轮变化事件；完整历史仍由事件版本、收据和周期快照保存。"""
    changed = set(payload.get("created", [])) | set(payload.get("updated", []))
    return {**payload, "events": [event for event in payload.get("events", [])
                                  if event["event_id"] in changed]}


def prepare_request(settings, values: dict) -> tuple[dict, int]:
    """冻结官方来源请求并限制单次工作量。"""
    mode = values.get("mode", "official")
    if mode != "official":
        raise ValueError("运行模式无效")
    uid = values.get("uid") or settings.uid
    start = bound(values["start"]) if values.get("start") else settings.start
    end = bound(values["end"], end=True) if values.get("end") else settings.end
    interval_value = values.get("interval") or duration_label(settings.interval)
    offline = bool(values.get("offline", True))
    validate_uid(uid)
    try:
        interval = duration(interval_value)
    except OverflowError:
        raise ValueError("处理周期超出支持范围") from None
    if start >= end or end - start > timedelta(days=API_MAX_RANGE_DAYS):
        raise ValueError("一次处理的时间范围须大于零且不能超过本地上限")
    total = math.ceil((end - start) / interval)
    if total > API_MAX_WINDOWS:
        raise ValueError("处理周期数量超过本地上限，请缩小范围或增大周期")
    return dict(mode=mode, uid=uid, start=start.isoformat(), end=end.isoformat(),
                interval=duration_label(interval), offline=offline,
                context_lookback=duration_label(settings.context_lookback),
                match_window=duration_label(settings.match_window),
                closed_grace=duration_label(settings.closed_grace),
                ingest_lookback=duration_label(settings.ingest_lookback),
                history_retrieval=asdict(settings.history_retrieval),
                history_context=asdict(settings.history_context),
                group_batch_chars=settings.group_batch_chars, group_matching_version=group_matching_version(),
                attribution_version=attribution_version() if settings.provider == "xhub" else None,
                default_status=settings.default_status, default_severity=settings.default_severity,
                closed_statuses=list(settings.closed_statuses),
                provider=settings.provider,
                llm_model=settings.llm_model if settings.provider == "xhub" else None,
                llm_max_tokens=settings.llm_max_tokens if settings.provider == "xhub" else None,
                llm_timeout_seconds=settings.llm_timeout_seconds if settings.provider == "xhub" else None,
                analysis_stream=configured_stream(settings)), total


def restore_settings(settings, request):
    """从已冻结请求还原执行配置；旧策略须显式迁移，不能补用当前缺省。"""
    if request["mode"] != "official":
        raise ValueError("该运行模式已移除")
    if request.get("group_matching_version") != group_matching_version():
        raise XHubError("本群归属策略已变化，请重新提交任务")
    frozen = replace(settings, uid=request["uid"],
        start=parse_time(request.get("business_start", request["start"])),
        end=parse_time(request["end"]), interval=duration(request["interval"]),
        chat_retries=0 if request.get("schedule_id") else settings.chat_retries,
        group_batch_chars=request["group_batch_chars"], provider=request["provider"],
        llm_model=request["llm_model"] or settings.llm_model,
        llm_max_tokens=request["llm_max_tokens"] or settings.llm_max_tokens,
        llm_timeout_seconds=request["llm_timeout_seconds"] or settings.llm_timeout_seconds,
        context_lookback=duration(request["context_lookback"]), match_window=duration(request["match_window"]),
        closed_grace=duration(request["closed_grace"]), ingest_lookback=duration(request["ingest_lookback"]),
        history_retrieval=HistoryRetrievalSettings(**request["history_retrieval"]),
        history_context=HistoryContextSettings(**request["history_context"]),
        default_status=request["default_status"], default_severity=request["default_severity"],
        closed_statuses=tuple(request["closed_statuses"]))
    if frozen.provider == "xhub" and request["attribution_version"] != attribution_version():
        raise XHubError("增量归属策略已变化，请重新提交任务；原分析范围及已处理消息保持不变")
    if request["analysis_stream"] != configured_stream(frozen):
        raise XHubError("提示词或输出合约已变化，请重新提交任务")
    return frozen


class RunRunner:
    """任务始终串行处理；只有拥有 MySQL 命名锁的实例可以恢复和领取任务。"""

    def __init__(self, settings, repository, *, service_factory=build_service, poll_interval=0.25):
        self.settings = settings
        self.repository = repository
        self.service_factory = service_factory
        self.poll_interval = poll_interval
        self.runner_id = str(uuid4())
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = None
        self._keeper = None
        self.scheduler = None
        self._schedule_tick = 0

    def start(self):
        """启动一个本地工作线程；数据库执行锁防止多 API 实例重复工作。"""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="dake-runner", daemon=True)
        self._thread.start()

    def notify(self):
        """提交后唤醒本实例，其他实例提交的任务由短轮询发现。"""
        self._wake.set()

    def stop(self):
        """在当前周期完成后停止，不中断数据库事务；下一次启动会标记异常中断。"""
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _wait(self):
        self._wake.wait(self.poll_interval)
        self._wake.clear()

    def _leader_alive(self):
        if self._keeper is None:
            return False
        rows, _ = self._keeper._execute("SELECT IS_USED_LOCK(%s)=CONNECTION_ID() AS ok", (self.repository.worker_lock,))
        return bool(rows and rows[0]["ok"] == 1)

    def _loop(self):
        while not self._stop.is_set():
            try:
                with self.repository.connection() as keeper:
                    rows, _ = keeper._execute("SELECT GET_LOCK(%s,0) AS ok", (self.repository.worker_lock,))
                    if not rows or rows[0]["ok"] != 1:
                        self._wait()
                        continue
                    self._keeper = keeper
                    # 只有新取得执行锁的实例恢复中断，旁观实例不触碰别人的 running。
                    self.repository.recover_interrupted()
                    while not self._stop.is_set() and self._leader_alive():
                        if self.scheduler is not None and monotonic() >= self._schedule_tick:
                            self._schedule_tick = monotonic() + self.settings.schedule_poll_seconds
                            try:
                                self.scheduler.tick()
                            except Exception:
                                # 定时编排失败不吞掉手动队列；页面可从最近触发时间发现停止。
                                import logging
                                logging.getLogger(__name__).warning("定时编排未完成，请检查迁移、名单与本地数据库")
                        run = self.repository.claim_next(self.runner_id)
                        if run is None:
                            self._wait()
                        else:
                            self.execute(run)
            except Exception:
                # 数据库暂时不可达时保留持久状态；重连取得锁后再明确恢复中断。
                if not self._stop.is_set():
                    self._stop.wait(min(1.0, self.poll_interval * 4))
            finally:
                self._keeper = None

    def execute(self, run):
        """每个任务独占业务连接，通过既有 ReplayService 按配置周期处理。"""
        request = run["request"]
        try:
            settings = restore_settings(self.settings, request)
            with self.service_factory(settings, offline=request["offline"]) as service:
                if service.attempts is None:
                    raise AttemptError("后台任务必须配置执行收据存储")
                retry_attempts = {0: request["scheduled_retry_of"]} if request.get("scheduled_retry_of") else {}
                # 仅使用本任务已持久化的进度；不移动业务起点，也不把文件水位当成提交证明。
                start_index = run["completed_windows"]
                if not 0 <= start_index <= run["total_windows"]:
                    raise RunInterrupted()
                task_start = parse_time(request["start"])
                results = ReplayService(service).run_range(settings.uid, task_start, settings.end, settings.interval,
                                                          run_id=run["run_id"], retry_attempts=retry_attempts,
                                                          start_index=start_index)
                for index, window in enumerate(windows(task_start, settings.end, settings.interval)):
                    if index < start_index:
                        continue
                    if self._stop.is_set() or (self._keeper is not None and not self._leader_alive()):
                        raise RunInterrupted()
                    window_value = {"start": window.start.isoformat(), "end": window.end.isoformat()}
                    interrupted = (None if request.get("schedule_id") else
                                   self.repository.interrupted_window(settings.uid, request["mode"], window_value))
                    if interrupted:
                        prior = interrupted.get("request", {})
                        if (prior.get("provider", "stub") != request.get("provider", "stub") or
                                (prior.get("analysis_stream") is not None and
                                 prior["analysis_stream"] != request.get("analysis_stream")) or
                                any(prior.get(key) != request.get(key) for key in
                                    ("attribution_version", "group_matching_version"))):
                            interrupted = None
                    self.repository.begin_window(run["run_id"], self.runner_id, window_value)
                    if interrupted:
                        previous = service.attempts.for_run_window(settings.uid, service.stream,
                            interrupted["run_id"], interrupted["completed_windows"], window)
                        if previous is not None:
                            retry_attempts[index] = previous["attempt_id"]
                    elif index == start_index and run.get("current_window") == window_value:
                        # 显式恢复同一任务也保留失败尝试关系；有收据时仅恢复展示。
                        previous = service.attempts.for_run_window(settings.uid, service.stream,
                            run["run_id"], index, window)
                        if previous is not None:
                            retry_attempts[index] = previous["attempt_id"]
                    result = next(results)
                    if self._keeper is not None and not self._leader_alive():
                        raise DeliveryError(f"执行 {result.attempt_id} 的业务已提交，执行权变化导致进度未保存；请恢复展示")
                    payload = compact_progress(result.to_dict())
                    try:
                        self.repository.complete_window(run["run_id"], self.runner_id, payload)
                    except Exception:
                        try:
                            service.attempts.delivery(settings.uid, service.stream, result.attempt_id,
                                                      "run_progress", "unconfirmed")
                        except Exception:
                            pass
                        raise DeliveryError(f"执行 {result.attempt_id} 的业务已提交，任务进度写入未确认；请恢复展示") from None
                    service.attempts.delivery(settings.uid, service.stream, result.attempt_id, "run_progress", "saved")
                    if interrupted is not None:
                        self.repository.mark_recovered(interrupted["run_id"], run["run_id"])
            if self._keeper is not None and not self._leader_alive():
                raise RunInterrupted()
            self.repository.finish(run["run_id"], self.runner_id)
        except Exception as error:
            if request.get("schedule_id"):
                kind = ("verification" if isinstance(error, AttemptPendingVerification) else
                        "delivery" if isinstance(error, DeliveryError) else
                        "transient" if isinstance(error, (TransientChatRecordsError, XHubTransientError)) else
                        "interrupted" if isinstance(error, RunInterrupted) else "permanent")
                self.repository.record_failure_kind(run["run_id"], self.runner_id, kind)
            message = ("服务已停止，已完成周期保留；可重新提交相同范围"
                       if isinstance(error, RunInterrupted) else
                       str(error) if isinstance(error, (XHubError, AttemptError)) else
                       "处理失败，已完成周期保留；请检查本地缓存、MySQL 或官方取数网络后重试")
            self.repository.finish(run["run_id"], self.runner_id, error=message)
