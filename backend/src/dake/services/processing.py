"""增量分析业务流程，供命令行、接口和后台任务共用，不依赖 Web 框架。"""

from copy import deepcopy
from dataclasses import asdict

from ..analysis.providers import Provider
from ..analysis.updates import snapshot_as_of
from ..analysis.validation import validate_candidates
from ..config import REVIEW, Settings
from ..domain.models import CycleResult, Window
from ..repositories.local_state import LocalState
from .ingestion import IngestionService, Source
from .history_retrieval import HistoryRetriever
from .history_context import HistoryContextService
from .attribution import apply_attributions, preflight_attributions
from .sender_kinds import FILTER_VERSION, kinds_fingerprint, load_sender_kinds, sender_kind
from .sender_identity import confirmed_sender_role, load_sender_roles
from .executions import run_recorded, message_ref


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

    def _run_window(self, uid: str, window: Window, *, observer=None, recorder=None) -> CycleResult:
        """处理一个左闭右开窗口；每个分析版本分别去重，并保留本次变化。"""
        def observe(stage, **payload):
            # 演示显式注入观察者；副本避免观察代码改变匹配输入，记录不表示已提交。
            if observer is not None:
                observer(stage, deepcopy(payload))
            if recorder is not None and stage == "decision":
                recorder.decision(**deepcopy(payload))

        if window.start < self.settings.start:
            raise ValueError("处理窗口不能早于配置的起始时间")
        # 官方接口只有日期精度；回查近期日期，容纳晚于发送时间入库的消息。
        kinds = load_sender_kinds(self.settings.data_dir)
        roles = load_sender_roles(self.settings.data_dir)
        configure = getattr(self.provider, "configure_sender_kinds", None)
        if configure is not None:
            configure(kinds)
        configure_roles = getattr(self.provider, "configure_sender_roles", None)
        if configure_roles is not None:
            configure_roles(roles)
        fetch_start = max(self.settings.start, window.start - self.settings.ingest_lookback)
        messages = self.ingestion.load_window(uid, fetch_start, window.end)
        result = CycleResult(uid, self.stream, window)
        if recorder is not None:
            result.attempt_id = recorder.attempt_id
            recorder.record("ingestion", message_versions=[message_ref(m) for m in messages])
        with self.store.transaction(uid):
            result.ingested = self.store.upsert_messages(messages)
            # 用已处理摘要找新增；只比较最大时间会漏掉较早时间的迟到消息。
            pending = self.store.pending_messages(uid, self.settings.start, window.end, self.stream)
            events = []
            if pending and self.store.has_future_event_revision(uid, self.stream, window.end):
                raise ValueError("该处理流已有更晚的事件；请在当前窗口处理迟到消息，或使用新的分析版本回放")
            context_start = max(self.settings.start, window.start - self.settings.context_lookback)
            context = self.store.context_messages(uid, context_start, window.end)
            pending_keys = {message.key for message in pending}
            context = [message for message in context if message.key not in pending_keys]
            groups = {}
            for message in pending:
                if not message.conversation_id:
                    result.review.append(dict(review_flag=REVIEW, type=None,
                        message_ids=[message.message_id], possible_event_ids=[],
                        reason="缺少稳定群 ID，不能进行本群事件匹配"))
                    continue
                groups.setdefault((message.source, message.conversation_id), []).append(message)
            for scope, batch in groups.items():
                group_context = [m for m in context if (m.source, m.conversation_id) == scope]
                chunks, current, size = [], [], 0
                for message in batch:
                    cost = len(message.content) + 256
                    if current and size + cost > self.settings.group_batch_chars:
                        chunks.append(current)
                        current, size = [], 0
                    current.append(message)
                    size += cost
                if current:
                    chunks.append(current)
                previous = []
                for chunk in chunks:
                    events = self._analyze_batch(uid, window, chunk, group_context + previous, events,
                        result, kinds, roles, observe, recorder, observer)
                    previous.extend(chunk)
            if not pending and recorder is not None:
                recorder.input([], [], [])
                for stage in ("history", "history_context", "extraction"):
                    recorder.record(stage, "skipped", reason="no_eligible_new_messages")
                recorder.extracted([])
            self.store.mark_processed(pending, self.stream)
            result.processed = len(pending)
            latest = self.store.latest_message(uid, window.end, self.stream)
            result.watermark = dict(
                next_start=window.end.isoformat(),
                last_send_time=latest.sent_at.isoformat() if latest else None,
                last_message_id=latest.message_id if latest else None,
            )
            result.events = [snapshot for event in events if (snapshot := snapshot_as_of(event, window.end))]
            result.snapshot_scope = "related_events"
            result.event_count = self.store.event_count(uid, self.stream)
            if recorder is not None:
                recorder.record("program_result", attributions=result.filter_audit, review=result.review,
                                created=result.created, updated=result.updated)
                recorder.receipt(self.store, result, events, pending)
        if recorder is not None:
            recorder.committed = True
            recorder.repository.confirm_commit(uid, self.stream, recorder.attempt_id)
            recorder.files_started = True
        # 文件只提供恢复便利；正式链路写失败后按原收据恢复展示，不重新分析。
        self.state.snapshot(result)
        self.state.advance(uid, self.stream, result.watermark)
        return result

    def _analyze_batch(self, uid, window, pending, context, events, result, kinds, roles, observe, recorder, observer):
        """分析一个群内批次；调用方保证消息和上下文范围。"""
        fingerprint = kinds_fingerprint(kinds)
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
            history = self.history_retriever.retrieve(uid, self.stream, eligible, window.end, conversation=conversation)
            loaded = self.store.events_by_ids(uid, self.stream, [e.event_id for e in history.events])
            events = list({e.event_id: e for e in [*events, *loaded]}.values())
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
                        customer_keys=customer_keys)
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
            events = apply_attributions(candidates, store=self.store, events=events,
                visible_events=history.events, available=available, pending=pending, eligible=eligible,
                background=background, result=result, settings=self.settings, retrieval=history, observe=observe,
                customer_keys=customer_keys, recorder=recorder)
        return events
