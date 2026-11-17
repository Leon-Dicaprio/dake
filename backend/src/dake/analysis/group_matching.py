"""本群归属的程序约束；不把词法相似度当作事件身份。"""

from dataclasses import replace
import hashlib

from .references import EVENT_REFERENCE as _EVENT_REF, MESSAGE_REFERENCE as _MESSAGE_REF
from .contract import ContractError


MATCH_FIELDS = ("产品", "资源标识", "操作", "环境")
GROUP_POLICY = """
history_retrieval.scope=conversation 时，只处理这个群的事项，跨群事件关联由另一模块负责。
明确业务事项按事项拆分；不要把一条消息中的不同事项混成一个候选。
沿用 attributes 表达匹配对象，可使用 产品、资源标识、操作、环境。
只在有逐字原文依据时填写，缺失不猜测；请求号、订单号不自动视为唯一事项编号。
显式 event_id 或完整 message_id 是程序可核验的引用；同产品、同资源、同群或时间相近都不证明同一事项。
仅重复旧事实时返回 duplicate，业务结果归为非业务/无需推进，不更新事件。
关键词零命中不证明独立新建；检索不完整或引用无法定位时返回 review。
"""


def group_matching_version():
    """冻结本群程序规则及模型补充约定，代码规则变化时同步递增版本。"""
    return "conversation-matching-v1-" + hashlib.sha256(GROUP_POLICY.encode()).hexdigest()[:16]


def constrain(candidate, *, retrieval, available, eligible):
    """仅修正可验证引用；恢复边界及新增事实仍由既有证据校验决定。"""
    if retrieval is None or retrieval.conversation is None:
        raise ContractError("同群归属缺少本群检索范围")
    scope = retrieval.conversation
    human = {m.key for m in eligible}
    evidence = [available[key] for key in candidate.evidence_ids if key in human]
    if not evidence or any((m.source, m.conversation_id) != scope for m in evidence):
        raise ContractError("事项证据不能越过本群范围")
    visible = {e.event_id: e for e in retrieval.events}
    ids, message_ids = set(), set()
    # 只读取该事项引用的当前原文片段，不能借同消息另一事项的编号认领目标。
    for ref in candidate.basis:
        if ref["message_id"] not in {m.key for m in evidence}:
            continue
        body = available[ref["message_id"]].content
        if ref["quote"] not in body:
            raise ContractError("匹配引用必须来自本事项的连续原文")
        ids.update(m.group(1).lower() for m in _EVENT_REF.finditer(ref["quote"]))
        message_ids.update(m.group(1) for m in _MESSAGE_REF.finditer(ref["quote"]))
    unresolved = ids - visible.keys()
    for key in message_ids:
        matches = {e.event_id for e in visible.values() if any(
            f"{r['source']}:{r['message_id']}" == key for r in e.evidence)}
        if len(matches) != 1:
            unresolved.add(key)
        ids.update(matches)
    target = next(iter(ids)) if len(ids) == 1 and not unresolved else None
    reason = None
    if unresolved or len(ids) > 1 or (message_ids and retrieval.exact_limited):
        reason = "明确引用无法唯一定位本群旧事件"
    elif target and candidate.referenced_event_id not in (None, target):
        reason = "模型更新目标与原文明确引用冲突"
    elif target and visible[target].type != candidate.type:
        reason = "明确引用与本事项类型冲突"
    elif candidate.decision == "new" and not candidate.continuity and target and not candidate.ambiguous:
        # 原文也可能在说“与该事件无关”；文本编号不是权威绑定，不能强行改成更新。
        reason = "新建建议包含明确旧事件引用，需确认是延续还是对照"
    old = visible.get(candidate.referenced_event_id)
    if old and candidate.decision in {"update", "duplicate"}:
        # 只比较有明确值的对象字段；字段缺失不构成冲突，相似也不直接合并。
        if any(candidate.attributes.get(key) and old.attributes.get(key)
               and candidate.attributes[key] != old.attributes[key] for key in MATCH_FIELDS):
            reason = "新旧事项的明确对象字段冲突，不能自动更新"
    if candidate.decision == "new" and retrieval.metadata()["incomplete"]:
        reason = "本群历史检索不完整，不能据零命中或有限候选直接新建"
    if reason:
        possible = sorted(set(candidate.possible_event_ids) | (ids & visible.keys()) |
                          ({old.event_id} if old else set()) | ({candidate.continuity["previous_event_id"]}
                          if candidate.continuity and candidate.continuity.get("previous_event_id") in visible else set()))
        continuity = (dict(kind="uncertain", previous_event_id=None, evidence=candidate.continuity["evidence"])
                      if candidate.continuity else None)
        candidate = replace(candidate, decision="review", referenced_event_id=None,
                            possible_event_ids=possible, ambiguous=True, decision_reason=reason, continuity=continuity)
    return candidate, dict(version=group_matching_version(),
                           matched_by="explicit_reference" if target else "semantic",
                           reason=reason)
