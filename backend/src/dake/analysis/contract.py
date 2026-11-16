"""抽取字段的基础合约与证据校验，供正式归属合约复用。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..domain.models import Candidate, Event, Message
from .validation import validate_candidates


class ContractError(ValueError):
    """不携带模型正文或聊天内容的校验错误。"""


class StrictObject(BaseModel):
    """拒绝多余字段与隐式类型转换。"""

    model_config = ConfigDict(extra="forbid", strict=True)


class Fact(StrictObject):
    """附有原文片段及消息引用的字段值。"""

    value: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    quote: str = Field(min_length=1)


class Attribute(Fact):
    """可扩展的类型专属属性，不自造官方枚举。"""

    name: str = Field(min_length=1)


class ExtractedCandidate(StrictObject):
    """模型候选与关联意图；是否真正更新仍由业务匹配器决定。"""

    type: Literal["商机", "流失", "排障", "资源需求", "功能需求", "商务需求"]
    topic_key: str | None
    summary: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    status: Fact | None
    severity: Fact | None
    assignees: list[Fact]
    attributes: list[Attribute]
    extensions: list[Attribute]
    decision: Literal["new", "update", "review"]
    referenced_event_id: str | None
    decision_reason: str = Field(min_length=1)


class ExtractionOutput(StrictObject):
    """版本化的模型输出，不包含由程序生成的时间和事件编号。"""

    schema_version: Literal["1.0"]
    candidates: list[ExtractedCandidate]


def parse_output(content: str, new_messages: list[Message], context: list[Message],
                 existing_events: list[Event], *, output_model=ExtractionOutput) -> list[Candidate]:
    """先验证结构，再验证来源、字段引文和旧事件引用；失败不伪装成空结果。"""
    try:
        output = output_model.model_validate_json(content)
    except (ValidationError, ValueError):
        raise ContractError("模型输出不符合清洗合约") from None
    messages = {message.key: message for message in [*context, *new_messages]}
    uids = {message.uid for message in messages.values()}
    if len(uids) != 1 or any(event.uid not in uids for event in existing_events):
        raise ContractError("清洗输入必须属于同一客户")
    old = {event.event_id: event for event in existing_events}
    candidates = []
    for candidate_index, item in enumerate(output.candidates):
        ids = set(item.evidence_ids)
        if len(ids) != len(item.evidence_ids) or not ids.issubset(messages):
            raise ContractError("证据必须唯一且引用本次输入的完整消息 ID")
        if not item.summary.strip() or not item.decision_reason.strip():
            raise ContractError("概述及关联依据不能为空")
        if item.decision != "review" and not (item.topic_key and item.topic_key.strip()):
            raise ContractError("明确的新建或更新必须有主题")
        explicit = output_model is not ExtractionOutput
        if item.decision in {"update", "duplicate"}:
            event = old.get(item.referenced_event_id)
            if event is None or event.type != item.type:
                raise ContractError("关联必须引用本次候选中同类型的已有事件")
            if not explicit and event.topic_key != item.topic_key:
                raise ContractError("旧版更新必须复用原主题")
        elif item.referenced_event_id is not None:
            raise ContractError("新建或待确认不得指定旧事件")
        for facts in (item.attributes, item.extensions):
            if len({fact.name for fact in facts}) != len(facts):
                raise ContractError("属性名称不得重复")
        facts = [(name, getattr(item, name)) for name in ("status", "severity")]
        facts += [(f"{name}[{index}]", fact) for name in ("attributes", "extensions", "assignees")
                  for index, fact in enumerate(getattr(item, name))]
        errors = []
        for path, fact in facts:
            if fact is None:
                continue
            refs = set(fact.evidence_ids)
            if not refs.issubset(ids) or len(refs) != len(fact.evidence_ids):
                errors.append(f"candidates[{candidate_index}].{path}：字段证据必须是候选证据的无重复子集")
                continue
            quoted = [messages[key] for key in refs if fact.quote in messages[key].content]
            if not quoted:
                errors.append(f"candidates[{candidate_index}].{path}：字段引文无法在所引用消息中核对")
                continue
            is_assignee = any(fact is assignee for assignee in item.assignees)
            if fact.value not in fact.quote and not (
                is_assignee and any(fact.value == message.sender_id for message in quoted)
            ):
                errors.append(f"candidates[{candidate_index}].{path}：字段值必须来自引文或明确认领者标识")
        if errors:
            raise ContractError("；".join(errors))
        candidate = Candidate(
            type=item.type, topic_key=item.topic_key, summary=item.summary,
            evidence_ids=item.evidence_ids,
            status=item.status.value if item.status else None,
            severity=item.severity.value if item.severity else None,
            assignees=[fact.value for fact in item.assignees],
            attributes={fact.name: fact.value for fact in item.attributes},
            extensions={
                "extraction_v1": item.model_dump(exclude={"summary", "evidence_ids", "basis", "possible_event_ids", "changes", "continuity"}),
            },
            ambiguous=item.decision == "review", referenced_event_id=item.referenced_event_id,
            decision=item.decision if explicit else None,
            decision_reason=item.decision_reason if explicit else "",
            basis=[ref.model_dump() for ref in item.basis] if explicit else [],
            possible_event_ids=item.possible_event_ids if explicit else [],
            changes=[change.model_dump() for change in item.changes] if hasattr(item, "changes") else None,
            continuity=item.continuity.model_dump() if getattr(item, "continuity", None) else None,
        )
        candidates.append(candidate)
    try:
        validate_candidates(candidates, new_messages, context)
    except ValueError:
        raise ContractError("候选类型、主题或新增证据未通过业务校验") from None
    return candidates
