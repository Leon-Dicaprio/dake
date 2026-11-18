"""增量分析业务流程，供命令行、接口和后台任务共用，不依赖 Web 框架。"""

from copy import deepcopy
from dataclasses import asdict

from ..analysis.providers import Provider
from ..analysis.updates import snapshot_as_of
from ..analysis.validation import validate_candidates
from ..config import REVIEW, Settings
from ..domain.models import CycleResult, Window, message_order, parse_time
from ..repositories.local_state import LocalState
from ..repositories.mysql import StorageError
from .ingestion import IngestionService, Source
from .history_retrieval import HistoryRetriever
from .history_context import HistoryContextService
from .attribution import apply_attributions, preflight_attributions
from .sender_kinds import FILTER_VERSION, kinds_fingerprint, load_sender_kinds, sender_kind
from .sender_identity import confirmed_sender_role, load_sender_roles
from .executions import run_recorded, message_ref
from .late import classify_pending


class _WindowPlan:
    """模型阶段只暂存事件和归属；核对输入及租约后才写业务事务。"""

    def __init__(self):
        self.writes = {}
        self.attributions = []
        self.related = set()

    def save_event(self, event):
        self.writes[event.event_id] = event
        self.related.add(event.event_id)

    def record_attributions(self, pending, stream, records):
        self.attributions.append((pending, stream, records))


def _load_customer_profile(store, uid: str) -> dict | None:
    """只读读取已持久化的客户等级资料；缺少客户目录表或未同步时保守返回 None。"""
    reader = getattr(store, "customer_profile", None)
    if reader is not None:
        return reader(uid)
    executor = getattr(store, "_execute", None)
    if executor is None:
        return None
    try:
        rows, _ = executor("SELECT uid, level, level_state FROM customer_profiles WHERE uid=%s", (uid,))
        return dict(rows[0]) if rows else None
    except StorageError:
        return None


class IncrementalService:
    """维持一次分析的原子性、可重试性和稳定事件身份。"""

    def __init__(self, store, source: Source, provider: Provider, settings: Settings,
                 state: LocalState | None = None, *, attempts=None):
        self.store = store
        self.source = source
        self.provider = provider
        self.settings = settings
        self.state = state or LocalState(settings.data_dir)
        self.ingestion = IngestionService(store, source)
        self.history_retriever = HistoryRetriever(store, settings.history_retrieval)
        self.history_context = HistoryContextService(store, settings.history_context)
        self.attempts = attempts

    @property
    def stream(self):
        """分析版本是独立处理流，确保 stub 不妨碍后续真实模型重放。"""
        return self.provider.name

    def fetch(self, uid: str, window: Window) -> int:
        """保留共用入口，实际摄入职责交给独立 IngestionService。"""
        return self.ingestion.fetch(uid, window)

    def run_window(self, uid: str, window: Window, *, observer=None, execution=None) -> CycleResult:
        """正式装配记录执行过程；测试可注入内存仓库和观察者。"""
        if self.attempts is not None:
            return run_recorded(self, uid, window, observer=observer, execution=execution)
        return self._run_window(uid, window, observer=observer)

    def _run_window(self, uid, window, *, observer=None, recorder=None):
        """冻结输入、事务外分群分析，再核对版本并原子提交整个窗口。"""
        def observe(stage, **payload):
            if observer is not None:
                observer(stage, deepcopy(payload))
            if recorder is not None and stage == "decision":
                recorder.decision(**deepcopy(payload))

        if window.start < self.settings.start:
            raise ValueError("处理窗口不能早于配置的起始时间")
        kinds = load_sender_kinds(self.settings.data_dir)
        roles = load_sender_roles(self.settings.data_dir)
        for name, value in (("configure_sender_kinds", kinds), ("configure_sender_roles", roles)):
            configure = getattr(self.provider, name, None)
            if configure is not None:
                configure(value)
        fetch_start = max(self.settings.start, window.start - self.settings.ingest_lookback)
        messages = self.ingestion.load_window(uid, fetch_start, window.end)
        result = CycleResult(uid, self.stream, window)
        if recorder is not None:
            result.attempt_id = recorder.attempt_id
            recorder.record("ingestion", message_versions=[message_ref(m) for m in messages])
        pending, context, baseline, withheld = self._preview_window(uid, window, messages, result)
        events = []
        plan = _WindowPlan()
        groups = {}
        for message in pending:
            if not message.conversation_id:
                result.review.append(dict(review_flag=REVIEW, type=None, message_ids=[message.message_id],
                    possible_event_ids=[], reason="缺少稳定群 ID，不能进行本群事件匹配"))
                continue
            groups.setdefault((message.source, message.conversation_id), []).append(message)
        for scope, group in groups.items():
            previous = [m for m in context if (m.source, m.conversation_id) == scope]
            for chunk in self._chunks(group):
                events = self._analyze_batch(uid, window, chunk, previous, events, result,
                                             kinds, roles, observe, recorder, observer, plan)
                previous = previous + chunk
        if not groups:
            events = self._analyze_batch(uid, window, [], [], events, result,
                                         kinds, roles, observe, recorder, observer, plan)
        with self.store.transaction(uid):
            writable = getattr(self.store, "store", self.store)
            previous_suppress = getattr(writable, "suppress_revision", False)
            writable.suppress_revision = True
            try:
                result.ingested = self.store.upsert_messages(messages)
                self._require_same_input(uid, window, pending, withheld, baseline)
                gate = getattr(self, "gate", None)
                if withheld and gate is not None:
                    gate.isolate(self.store, withheld, window)
                for event in plan.writes.values():
                    self.store.save_event(event)
                for batch, stream, records in plan.attributions:
                    self.store.record_attributions(batch, stream, records)
                self.store.mark_processed(pending, self.stream)
                result.processed = len(pending)
                latest = self.store.latest_message(uid, window.end, self.stream)
                result.watermark = dict(next_start=window.end.isoformat(),
                    last_send_time=latest.sent_at.isoformat() if latest else None,
                    last_message_id=latest.message_id if latest else None)
                result.snapshot_scope = "related_events"
                result.event_count = len(set(baseline) | set(plan.writes))
                result.events = [snapshot for event in events if event.event_id in plan.related
                    if (snapshot := snapshot_as_of(event, window.end))]
                if recorder is not None:
                    recorder.record("program_result", attributions=result.filter_audit, review=result.review,
                                    created=result.created, updated=result.updated)
                    recorder.receipt(self.store, result, events, pending)
                if gate is not None:
                    gate.fence(self.store, incomplete=any(item.get("incomplete") for item in result.filter_audit))
            finally:
                writable.suppress_revision = previous_suppress
        if recorder is not None:
            recorder.committed = True
            recorder.repository.confirm_commit(uid, self.stream, recorder.attempt_id)
            recorder.files_started = True
        self.state.snapshot(result)
        self.state.advance(uid, self.stream, result.watermark)
        return result

    def _chunks(self, messages):
        """按字符预算划分完整消息，单条长消息也不截断。"""
        chunk, size = [], 0
        for message in messages:
            cost = len(message.content) + 256
            if chunk and size + cost > self.settings.group_batch_chars:
                yield chunk
                chunk, size = [], 0
            chunk.append(message)
            size += cost
        if chunk:
            yield chunk

    def _preview_window(self, uid, window, messages, result):
        """在事务外冻结本窗输入。严格窗口把迟到和修订隔离开，不混入当前模型输入。"""
        lower = self.settings.start
        incoming = [message for message in messages if lower <= message.sent_at < window.end]
        stored = {message.key: message for message in self.store.context_messages(uid, lower, window.end)}
        pending = {message.key: message for message in self.store.pending_messages(uid, lower, window.end, self.stream)}
        for message in incoming:
            previous = stored.get(message.key)
            if previous is None or previous.digest != message.digest:
                pending[message.key] = message
        pending_list = sorted(pending.values(), key=message_order)
        baseline = self.store.event_revision_heads(uid, self.stream)
        revision_ends = [end for ends in baseline.values() for end in ends]
        later = any(parse_time(end) > window.end for end in revision_ends)
        if later and not getattr(self, "strict_window", False) and pending_list:
            raise ValueError("该处理流已有更晚的事件；请在当前窗口处理迟到消息，或使用新的分析版本回放")
        if later and getattr(self, "strict_window", False):
            raise ValueError("已进入实时或已有更晚结果，旧历史不能倒灌主流")
        isolated = []
        if getattr(self, "strict_window", False):
            revised = self.store.revised_message_keys(uid, self.stream, lower, window.end)
            pending_list, backfill, isolated = classify_pending(
                pending_list, window, (), self.settings.ingest_lookback, revised, revision_ends=revision_ends)
            if backfill:
                result.filter_audit.append(dict(kind="controlled_backfill", count=len(backfill),
                    grace_seconds=int(self.settings.ingest_lookback.total_seconds())))
            if isolated:
                result.filter_audit.append(dict(kind="withheld", count=len(isolated), incomplete=True,
                    reasons=sorted({item["kind"] for item in isolated})))
        context_start = max(self.settings.start, window.start - self.settings.context_lookback)
        context = {message.key: message for message in self.store.context_messages(uid, context_start, window.end)}
        for message in messages:
            if context_start <= message.sent_at < window.end:
                context[message.key] = message
        pending_keys = {message.key for message in pending_list}
        ordered = [message for message in sorted(context.values(), key=message_order) if message.key not in pending_keys]
        return pending_list, ordered, baseline, isolated

    def _analyze_batch(self, uid, window, pending, context, events, result, kinds, roles, observe, recorder, observer, plan):
        """分析一个群内批次；调用方保证消息和上下文范围。"""
        fingerprint = kinds_fingerprint(kinds)
        customer_profile = _load_customer_profile(self.store, uid)
        bot_pending = [m for m in pending if sender_kind(m.to_dict(), kinds) == "bot"]
        bot_keys = {m.key for m in bot_pending}
        eligible = [m for m in pending if m.key not in bot_keys]
        auxiliary = context + bot_pending
        eligible_keys = {m.key for m in eligible}
        customer_keys = {m.key for m in eligible if confirmed_sender_role(m.to_dict(), roles) == "customer"}
        if recorder is not None:
            recorder.input(pending, eligible, auxiliary)
        if observer is not None:
            observe("input", pending=[m.to_dict() | {"key": m.key, "digest": m.digest} for m in pending],
                    context=[m.to_dict() | {"key": m.key, "digest": m.digest} for m in auxiliary])
        candidates = []
        history, background = None, None
        if eligible:
            # 历史候选和补取背景限定本轮可引用的旧事件，明确决定不再按主题预合并。
            conversation = (eligible[0].source, eligible[0].conversation_id)
            history = self.history_retriever.retrieve(uid, self.stream, eligible, window.end,
                conversation=conversation, staged_events=plan.writes.values())
            plan.related.update(e.event_id for e in history.events)
            known = {e.event_id for e in events}
            events = [*events, *self.store.events_by_ids(uid, self.stream,
                [e.event_id for e in history.events if e.event_id not in known])]
            if recorder is not None:
                recorder.record("history", candidates=[c.to_input() for c in history.candidates], metadata=history.metadata())
            if observer is not None:
                observe("history", candidates=[c.to_input() for c in history.candidates],
                        metadata=history.metadata())
            configure_history = getattr(self.provider, "configure_history_retrieval", None)
            if configure_history is not None:
                configure_history(history)
            configure_context = getattr(self.provider, "configure_history_context", None)
            if configure_context is not None:
                # 补取结果走独立只读输入，不加入 pending、available 或事件写入证据。
                background = self.history_context.retrieve(history, eligible, auxiliary, events, kinds)
                configure_context(background)
            if recorder is not None:
                recorder.record("history_context", "completed" if background is not None else "skipped",
                                result=background.to_input() if background is not None else None)
                recorder.record("extraction", "started")
                if not hasattr(self.provider, "configure_execution_observer"):
                    recorder.record("provider_input", new_messages=[m.to_dict() | {"digest": m.digest} for m in eligible],
                        context_messages=[m.to_dict() | {"digest": m.digest} for m in auxiliary])
            configure_validator = getattr(self.provider, "configure_candidate_validator", None)
            if configure_validator is not None:
                def validate_proposals(proposals):
                    available = validate_candidates(proposals, pending, context)
                    accepted = [c for c in proposals if eligible_keys.intersection(c.evidence_ids)]
                    preflight_attributions(accepted, events=events, visible_events=history.events,
                        available=available, pending=pending, eligible=eligible, background=background,
                        result=result, settings=self.settings, retrieval=history,
                        customer_keys=customer_keys, customer_profile=customer_profile, sender_roles=roles)
                configure_validator(validate_proposals)
            try:
                candidates = self.provider.extract(eligible, auxiliary, history.events)
            finally:
                if configure_validator is not None:
                    configure_validator(None)
        if recorder is not None:
            if not eligible:
                for stage in ("history", "history_context", "extraction"):
                    recorder.record(stage, "skipped", reason="no_eligible_new_messages")
            recorder.extracted(candidates)
        if observer is not None:
            observe("extracted", candidates=[asdict(c) for c in candidates])
        available = validate_candidates(candidates, pending, context)
        accepted = []
        for candidate in candidates:
            if any(available[key].key in eligible_keys for key in candidate.evidence_ids):
                accepted.append(candidate)
            else:
                result.filter_audit.append(dict(
                    reason="bot_only_candidate", message_keys=[available[key].key for key in candidate.evidence_ids],
                    policy_version=FILTER_VERSION, identity_config_hash=fingerprint))
        candidates = accepted
        for message in bot_pending:
            result.filter_audit.append(dict(
                reason="confirmed_bot_auxiliary_only" if eligible else "confirmed_bot_without_new_discussion",
                message_keys=[message.key], policy_version=FILTER_VERSION, identity_config_hash=fingerprint))
        if any(candidate.decision is None for candidate in candidates):
            raise ValueError("Provider 必须返回明确的事项归属")
        if candidates:
            events = apply_attributions(candidates, store=plan, events=events,
                visible_events=history.events, available=available, pending=pending, eligible=eligible,
                background=background, result=result, settings=self.settings, retrieval=history, observe=observe,
                customer_keys=customer_keys, customer_profile=customer_profile, sender_roles=roles, recorder=recorder)
        return events

    def _require_same_input(self, uid, window, pending, withheld, baseline):
        """提交前再次读取。模型期间插入或修订的消息不能带着旧结果落库。"""
        current = self.store.pending_messages(uid, self.settings.start, window.end, self.stream)
        expected = {(message.key, message.digest) for message in pending}
        expected.update((item["source"] + ":" + item["message_id"], item["digest"]) for item in withheld)
        actual = {(message.key, message.digest) for message in current}
        if actual != expected:
            raise ValueError("输入已变化，本窗口结果不提交")
        if self.store.event_revision_heads(uid, self.stream) != baseline:
            raise ValueError("事件基线已变化，本窗口结果不提交")
