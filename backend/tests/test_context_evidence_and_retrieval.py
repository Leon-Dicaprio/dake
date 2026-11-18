"""验证分条日志证据保留、跨窗口口语指代保底召回与前后群聊上下文只读接口。"""

import asyncio
from dataclasses import replace
from datetime import timedelta
import httpx

from dake.api.app_factory import create_app
from dake.config import Settings
from dake.domain.models import Candidate, Message, Window, parse_time
from dake.services.processing import IncrementalService
from dake.services.queries import QueryService
from fakes import FakeProvider, FakeSource, MemoryStore


UID = "synthetic-ctx-customer"


class AttributionProvider(FakeProvider):
    """支持归属模式与历史上下文注入的测试 Provider。"""

    def configure_history_context(self, background):
        self.background = background


class BoundStoreFactory:
    """复用同一内存仓库的连接工厂。"""

    def __init__(self, store: MemoryStore):
        self.store = store

    def __call__(self, **_kwargs):
        return self.store


def _msg(mid: str, at: str, content: str, *, uid: str = UID, group: str = "grp-main") -> Message:
    return Message(uid=uid, message_id=mid, sent_at=parse_time(at), content=content, conversation_id=group)


def _win(at: str) -> Window:
    start = parse_time(at)
    return Window(start, start + timedelta(minutes=15))


def test_consecutive_log_and_image_messages_in_evidence_ids_are_never_stripped(tmp_path):
    """客户先发原始请求列表/配图、后发口语提问时，未进 changes 引文的前序证据不得被静默删掉。"""
    m_log = _msg(
        "101",
        "2026-11-17 12:08:26",
        "req-alpha-01\nreq-alpha-02\nreq-alpha-03\nreq-alpha-04\nreq-alpha-05\nreq-alpha-06",
    )
    m_img = _msg("102", "2026-11-17 12:09:10", "[图片]")
    m_ask = _msg("103", "2026-11-17 12:09:30", "辛苦帮查一下上面这6个合成请求报错500的问题")
    m_reply = _msg("104", "2026-11-17 12:10:01", "核实中，稍等")

    provider = AttributionProvider(name="stub-v1")
    settings = replace(Settings(), data_dir=tmp_path, uid=UID, provider="stub")
    store = MemoryStore()
    source = FakeSource([m_log, m_img, m_ask, m_reply])
    pipeline = IncrementalService(store, source, provider, settings)

    # 模型将 4 条连续消息全部放入 evidence_ids，但摘要 changes 只引用了文字提问和回复。
    provider.mapping["104"] = Candidate(
        type="排障",
        types=["排障"],
        classification_status="已分类",
        type_evidence={"排障": [{"evidence_ids": [m_ask.key], "quote": "报错500的问题"}]},
        topic_key="api:six-requests-500",
        summary="6个合成请求返回500报错，客服正在核实",
        evidence_ids=[m_log.key, m_img.key, m_ask.key, m_reply.key],
        decision="new",
        decision_reason="首次反馈 6 个合成请求 500 报错",
        basis=[
            {"message_id": m_log.key, "quote": "req-alpha-01"},
            {"message_id": m_ask.key, "quote": m_ask.content},
        ],
        changes=[
            {
                "kind": "progress",
                "text": "6个合成请求返回500报错，客服正在核实",
                "replaces": None,
                "evidence": [
                    {"message_id": m_ask.key, "quote": m_ask.content},
                    {"message_id": m_reply.key, "quote": m_reply.content},
                ],
            }
        ],
    )
    res = pipeline.run_window(UID, _win("2026-11-17 12:00:00"))
    event = store.events[res.created[0]]
    assert [item["message_id"] for item in event.evidence] == ["101", "102", "103", "104"]
    assert event.start_time == m_log.sent_at


def test_cross_window_anaphoric_followup_recalls_same_group_recent_event_and_merges(tmp_path):
    """跨 15m 窗口的纯口语指代即使与前序摘要零双字词重合，也应召回同群近期事件并合并到原 event_id。"""
    m1 = _msg("201", "2026-11-17 10:26:14", "合成网关转发链路耗时过久需要排查")
    m2 = _msg("202", "2026-11-17 10:27:40", "GET https://synthetic.example/slow cost=9420ms")
    # 下一窗口口语指代，与“合成网关转发链路耗时过久需要排查”无任何双字词重合！
    m3 = _msg("203", "2026-11-17 10:34:22", "就是上面那个九秒多的")
    m4 = _msg("204", "2026-11-17 10:40:35", "该测试域名解析指向外部节点")

    provider = AttributionProvider(name="stub-v1")
    settings = replace(Settings(), data_dir=tmp_path, uid=UID, provider="stub")
    store = MemoryStore()
    source = FakeSource([m1, m2])
    pipeline = IncrementalService(store, source, provider, settings)

    provider.mapping["202"] = Candidate(
        type="排障",
        types=["排障"],
        classification_status="已分类",
        type_evidence={"排障": [{"evidence_ids": [m1.key], "quote": "耗时过久需要排查"}]},
        topic_key="gateway:slow-forward",
        summary="合成网关转发链路耗时过久需要排查",
        evidence_ids=[m1.key, m2.key],
        decision="new",
        decision_reason="首次提出慢请求排查",
        basis=[{"message_id": m1.key, "quote": m1.content}],
        changes=[
            {
                "kind": "progress",
                "text": "合成网关转发链路耗时过久需要排查",
                "replaces": None,
                "evidence": [{"message_id": m1.key, "quote": m1.content}],
            }
        ],
    )
    r1 = pipeline.run_window(UID, _win("2026-11-17 10:15:00"))
    event_id = r1.created[0]

    # 第二窗口：检查 provider 实际收到的 historical existing_events 必须包含刚创建的 event_id！
    source.messages.extend([m3, m4])
    provider.mapping["204"] = Candidate(
        type="排障",
        types=["排障"],
        classification_status="已分类",
        type_evidence={"排障": [{"evidence_ids": [m4.key], "quote": "域名解析指向外部节点"}]},
        topic_key="gateway:slow-forward",
        summary="补充指明九秒多慢请求，排查域名解析指向外部节点",
        evidence_ids=[m3.key, m4.key],
        decision="update",
        referenced_event_id=event_id,
        decision_reason="同群紧接上一窗口慢请求继续指代补充",
        basis=[
            {"message_id": m2.key, "quote": "cost=9420ms"},
            {"message_id": m3.key, "quote": m3.content},
        ],
        changes=[
            {
                "kind": "progress",
                "text": "排查确认测试域名解析指向外部节点",
                "replaces": None,
                "evidence": [{"message_id": m4.key, "quote": m4.content}],
            }
        ],
    )
    r2 = pipeline.run_window(UID, _win("2026-11-17 10:30:00"))
    _, _, recalled_events = provider.calls[-1]
    assert [e.event_id for e in recalled_events] == [event_id]
    assert r2.updated == [event_id] and not r2.created
    merged = store.events[event_id]
    assert [e["message_id"] for e in merged.evidence] == ["201", "202", "203", "204"]


def test_event_context_endpoint_returns_same_group_neighbors_without_leaking_other_groups(tmp_path):
    """即使旧事件漏收了前 1 分钟的原始参数消息，前后群聊上下文接口也能按同客户同群精确补齐展示。"""
    m_before = _msg("301", "2026-11-17 12:08:26", "合成前序 6 条 request ID 列表", group="grp-target")
    m_other_group = _msg("302", "2026-11-17 12:09:00", "同客户另一群无关讨论", group="grp-other")
    m_other_uid = _msg("303", "2026-11-17 12:09:10", "其他客户无关消息", uid="other-uid", group="grp-target")
    m_ev = _msg("304", "2026-11-17 12:09:30", "辛苦帮查下上面这 6 个合成 request", group="grp-target")

    provider = AttributionProvider(name="stub-v1")
    settings = replace(Settings(), data_dir=tmp_path, uid=UID, provider="stub")
    store = MemoryStore()
    source = FakeSource([m_before, m_other_group, m_ev])
    pipeline = IncrementalService(store, source, provider, settings)

    # 模拟历史流中仅收录了 304 一条消息的情形
    provider.mapping["304"] = Candidate(
        type="排障",
        types=["排障"],
        classification_status="已分类",
        type_evidence={"排障": [{"evidence_ids": [m_ev.key], "quote": "帮查下上面"}]},
        topic_key="api:ctx-test",
        summary="模拟历史事件仅收录提问句",
        evidence_ids=[m_ev.key],
        decision="new",
        decision_reason="新建测试事件",
        basis=[{"message_id": m_ev.key, "quote": m_ev.content}],
        changes=[
            {
                "kind": "progress",
                "text": "模拟历史事件仅收录提问句",
                "replaces": None,
                "evidence": [{"message_id": m_ev.key, "quote": m_ev.content}],
            }
        ],
    )
    event_id = pipeline.run_window(UID, _win("2026-11-17 12:00:00")).created[0]
    with store.transaction("other-uid"):
        store.upsert_messages([m_other_uid])

    # 为 MemoryStore 提供兼容 SQL 查询替身供 enrich_events 使用
    def fake_execute(_sql, args=()):
        if args and args[0] == UID:
            rows = [
                {"source": m.source, "message_id": m.message_id, "payload": m.to_dict()}
                for m in store.messages.values()
                if m.uid == UID
            ]
            return rows, len(rows)
        return [], 0

    store._execute = fake_execute
    factory = BoundStoreFactory(store)
    app = create_app(
        settings,
        store_factory=factory,
        query_service=QueryService(settings, store_factory=factory),
        start_worker=False,
    )

    async def verify():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
            resp = await client.get(
                f"/api/v1/events/{event_id}/context",
                params={"uid": UID, "stream": "stub-v1", "padding_minutes": 15},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert [(i["message_id"], i["is_evidence"]) for i in data["items"]] == [
                ("301", False),
                ("304", True),
            ]
            assert data["items"][0]["content"] == "合成前序 6 条 request ID 列表"

            # 错误客户必须返回 404，绝不越权读取
            r404 = await client.get(
                f"/api/v1/events/{event_id}/context",
                params={"uid": "other-uid", "stream": "stub-v1"},
            )
            assert r404.status_code == 404

    asyncio.run(verify())
