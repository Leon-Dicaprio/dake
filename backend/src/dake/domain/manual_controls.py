"""核心管理字段的轻量人工覆盖、锁定与待核对长度治理；不塞入模型提示词。"""

from copy import deepcopy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from .priority_policy import PRIORITIES
from .status_policy import LIFECYCLE_STATUSES, validate_status_shape

CONTROLLED_FIELDS = ("types", "status", "priority", "assignees")
ControlledField = Literal["types", "status", "priority", "assignees"]
MAX_REVIEW_FLAG_CHARS = 120


class ManualFieldAction(BaseModel):
    """单个核心字段的人工覆盖或锁定动作。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    field: ControlledField
    action: Literal["set", "lock", "unlock", "adopt_conflict", "dismiss_conflict"]
    types: list[str] | None = None
    status: str | None = None
    waiting_reason: str | None = None
    resolution: str | None = None
    priority: str | None = None
    assignees: list[str] | None = None
    locked: bool | None = None


class ManualDecisionRequest(BaseModel):
    """针对核心管理字段的原子人工裁定请求。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    uid: str = Field(min_length=1, max_length=128)
    stream: str = Field(min_length=1, max_length=128)
    expected_version: int = Field(ge=0)
    operation_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    operator: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=2000)
    actions: list[ManualFieldAction] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_nonblank(self):
        if not self.operator.strip() or not self.reason.strip():
            raise ValueError("操作人和裁定理由不能为空")
        fields = [item.field for item in self.actions]
        if len(set(fields)) != len(fields):
            raise ValueError("单次请求中同一字段不得重复提交动作")
        return self


class ManualControlState(BaseModel):
    """单个受控字段的人工锁定状态与冲突提示。"""

    field: ControlledField
    locked: bool = False
    operator: str | None = None
    reason: str | None = None
    decided_at: str | None = None
    adopted_value: JsonValue | None = None
    pending_conflict: dict[str, JsonValue] | None = None


class ManualOperationRecord(BaseModel):
    """已提交的人工操作收据，用于幂等重放与历史追溯。"""

    operation_id: str
    request_digest: str
    operator: str
    reason: str
    decided_at: str
    version: int
    actions: list[dict[str, JsonValue]]


def is_locked(event, field_name: ControlledField) -> bool:
    """检查目标核心字段是否处于人工锁定状态。"""
    control = (event.manual_controls or {}).get(field_name)
    return bool(control and control.get("locked"))


def set_field_lock(
    event,
    field_name: ControlledField,
    locked: bool,
    *,
    operator: str = "manual",
    reason: str = "",
    decided_at: str | None = None,
    adopted_value=None,
) -> dict:
    """更新指定核心字段的人工锁定元数据，并清理已处理的锁定冲突。"""
    existing = (event.manual_controls or {}).get(field_name) or {}
    state = dict(
        field=field_name,
        locked=bool(locked),
        operator=operator,
        reason=reason,
        decided_at=decided_at,
        adopted_value=deepcopy(adopted_value) if adopted_value is not None else deepcopy(existing.get("adopted_value")),
        pending_conflict=None,
    )
    event.manual_controls[field_name] = state
    return state


def record_lock_conflict(
    event,
    field_name: ControlledField,
    proposed_value,
    summary: str,
    evidence_refs: list[dict] | None = None,
) -> None:
    """锁定期内出现新证据不同结论时保留人工值，写入待核对冲突。"""
    control = event.manual_controls.setdefault(
        field_name,
        dict(field=field_name, locked=True, operator=None, reason=None, decided_at=None, adopted_value=None, pending_conflict=None),
    )
    conflict = dict(
        proposed_value=deepcopy(proposed_value),
        summary=summary,
        evidence_refs=deepcopy(evidence_refs or []),
    )
    control["pending_conflict"] = conflict
    upsert_review_item(
        event,
        kind="locked_field_conflict",
        field=field_name,
        summary=summary,
        proposed=proposed_value,
        evidence_refs=evidence_refs or [],
    )


def upsert_review_item(
    event,
    *,
    kind: str,
    field: str,
    summary: str,
    proposed=None,
    evidence_refs: list[dict] | None = None,
) -> None:
    """按类型与字段幂等维护结构化待核对项，避免重复堆叠完全相同的提示。"""
    for item in event.review_items:
        if item.get("status", "open") == "open" and item.get("kind") == kind and item.get("field") == field:
            item.update(
                summary=summary,
                proposed=deepcopy(proposed),
                evidence_refs=deepcopy(evidence_refs or []),
            )
            return
    event.review_items.append(dict(
        kind=kind,
        field=field,
        summary=summary,
        status="open",
        proposed=deepcopy(proposed),
        evidence_refs=deepcopy(evidence_refs or []),
    ))


def resolve_review_items(event, *, field: str, kinds: tuple[str, ...] | None = None) -> None:
    """指定字段冲突解除或人工裁定后关闭对应待核对项。"""
    for item in event.review_items:
        if item.get("field") == field and item.get("status", "open") == "open":
            if kinds is None or item.get("kind") in kinds:
                item["status"] = "resolved"


def compose_review_flag(
    review_items: list[dict],
    extra_flags: list[str] | tuple[str, ...] = (),
    max_chars: int = MAX_REVIEW_FLAG_CHARS,
) -> str | None:
    """合成并安全截断表列 review_flag，确保严格不超出 MySQL VARCHAR(128)。"""
    segments: list[str] = []
    for text in extra_flags:
        cleaned = (text or "").strip()
        if cleaned and cleaned not in segments:
            segments.append(cleaned)
    for item in review_items:
        if item.get("status", "open") != "open":
            continue
        cleaned = (item.get("summary") or "").strip()
        if cleaned and cleaned not in segments:
            segments.append(cleaned)
    if not segments:
        return None
    joined = "；".join(segments)
    if len(joined) <= max_chars:
        return joined
    suffix = f"…等{len(segments)}项待核对"
    budget = max(16, max_chars - len(suffix))
    return joined[:budget].rstrip("；、 ") + suffix


def validate_manual_value(action: ManualFieldAction, allowed_labels: tuple[str, ...]) -> None:
    """校验人工填写的核心字段取值合法性。"""
    if action.field == "types":
        if action.types is None:
            raise ValueError("分类裁定须提供标签列表（待分类传空列表）")
        if len(set(action.types)) != len(action.types) or any(t not in allowed_labels for t in action.types):
            raise ValueError("分类标签包含重复或不允许的类型")
    elif action.field == "status":
        if action.status is None or action.status not in LIFECYCLE_STATUSES:
            raise ValueError("状态裁定须提供有效的主状态")
        validate_status_shape(action.status, action.waiting_reason, action.resolution)
    elif action.field == "priority":
        if action.priority is None or action.priority not in PRIORITIES:
            raise ValueError("优先级裁定须提供有效的优先级档位")
    elif action.field == "assignees":
        if action.assignees is None or any(not isinstance(item, str) or not item.strip() for item in action.assignees):
            raise ValueError("跟进人裁定须提供有效的字符串列表")
