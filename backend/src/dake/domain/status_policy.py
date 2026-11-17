"""事件生命周期状态口径与确定性校验；本地工程缺省，不冒充官方已公布枚举。"""

from copy import deepcopy
from typing import Literal

LIFECYCLE_STATUSES = ("状态未明", "跟进中", "等待中", "已解决", "已取消")
WAITING_REASONS = ("等待客户", "等待内部支撑", "等待其他方")
RESOLVED_RESOLUTIONS = ("客户确认恢复", "支撑声明已修复", "已答复或已交付")
CANCELED_RESOLUTIONS = ("已拒绝", "已撤回", "确认不成立")
RESOLUTIONS = RESOLVED_RESOLUTIONS + CANCELED_RESOLUTIONS
TERMINAL_STATUSES = ("已解决", "已取消")

LifecycleStatus = Literal["状态未明", "跟进中", "等待中", "已解决", "已取消"]
WaitingReason = Literal["等待客户", "等待内部支撑", "等待其他方"]
Resolution = Literal["客户确认恢复", "支撑声明已修复", "已答复或已交付", "已拒绝", "已撤回", "确认不成立"]


def normalize_legacy_status(status: str | None) -> tuple[str, str | None]:
    """保守映射存量状态；自由文本不猜测为跟进中或已解决，保留原文供核对。"""
    if status in LIFECYCLE_STATUSES:
        return status, None
    if status is None or status.strip() in {"", "未知"}:
        return "状态未明", None
    return "状态未明", status


def validate_status_shape(status: str, waiting_reason: str | None, resolution: str | None) -> None:
    """校验主状态、等待原因与结束结果的三层组合约束。"""
    if status not in LIFECYCLE_STATUSES:
        raise ValueError("主状态不在允许的生命周期枚举中")
    if status == "等待中":
        if waiting_reason not in WAITING_REASONS:
            raise ValueError("等待中状态必须提供有效的等待原因")
        if resolution is not None:
            raise ValueError("等待中状态不能同时填写结束结果")
        return
    if waiting_reason is not None:
        raise ValueError("非等待中状态不得填写等待原因")
    if status == "已解决":
        if resolution not in RESOLVED_RESOLUTIONS:
            raise ValueError("已解决状态必须提供有效的解决结果")
    elif status == "已取消":
        if resolution not in CANCELED_RESOLUTIONS:
            raise ValueError("已取消状态必须提供有效的取消结果")
    elif resolution is not None:
        raise ValueError("未结束状态不得填写结束结果")


def evaluate_status_proposal(
    proposal: dict | None,
    *,
    current_status: str = "状态未明",
    current_waiting_reason: str | None = None,
    current_resolution: str | None = None,
    active_labels: list[str] | tuple[str, ...] = (),
    classification_status: str = "已分类",
    has_customer_recovery: bool = False,
    evidence_roles: set[str] | frozenset[str] = frozenset(),
    evidence_refs: list[dict] | None = None,
    late: bool = False,
    created: bool = False,
) -> dict:
    """结合多标签、待分类边界、发送者身份与时间先后计算确定性状态结果。"""
    if proposal is None:
        return dict(
            adopted=False,
            lifecycle_status=current_status,
            waiting_reason=current_waiting_reason,
            resolution=current_resolution,
            detail=None,
            reopened=False,
            review_items=[],
        )

    target_status = proposal["status"]
    waiting_reason = proposal.get("waiting_reason")
    resolution = proposal.get("resolution")
    completed_labels = proposal.get("completed_labels")
    reason = (proposal.get("reason") or "").strip()
    validate_status_shape(target_status, waiting_reason, resolution)

    refs = deepcopy(evidence_refs or proposal.get("evidence_refs", []))
    reviews: list[dict] = []
    notes: list[str] = []

    # 迟到补证不得把较新的主状态倒退；若与已结束状态冲突则提示待核对。
    if late and not created:
        if current_status in TERMINAL_STATUSES and target_status != current_status:
            reviews.append(dict(
                kind="late_status_conflict",
                field="status",
                summary="迟到消息状态信号与当前结束状态不一致，待核对",
                proposed=dict(status=target_status, waiting_reason=waiting_reason, resolution=resolution),
                evidence_refs=refs,
            ))
        return dict(
            adopted=False,
            lifecycle_status=current_status,
            waiting_reason=current_waiting_reason,
            resolution=current_resolution,
            detail=None,
            reopened=False,
            review_items=reviews,
        )

    # 待分类事项尚无适用类型的完成标准，禁止直接判为已解决。
    if classification_status == "待分类" and target_status == "已解决":
        fallback = current_status if not created and current_status != "状态未明" else "跟进中"
        fallback_wait = current_waiting_reason if fallback == "等待中" else None
        fallback_res = current_resolution if fallback in TERMINAL_STATUSES else None
        reviews.append(dict(
            kind="pending_classification_completion",
            field="status",
            summary="待分类事项缺少明确类型完成标准，暂不进入已解决",
            proposed=dict(status=target_status, waiting_reason=waiting_reason, resolution=resolution),
            evidence_refs=refs,
        ))
        return dict(
            adopted=created or fallback != current_status,
            lifecycle_status=fallback,
            waiting_reason=fallback_wait,
            resolution=fallback_res,
            detail=dict(
                status=fallback,
                waiting_reason=fallback_wait,
                resolution=fallback_res,
                reason=reason or "待分类事项暂保持跟进",
                note="待分类事项未确认适用类型完成标准",
                source="automatic",
                evidence_refs=refs,
            ),
            reopened=False,
            review_items=reviews,
        )

    # 多标签事项遵循“最慢未完责任”原则：任一有效标签尚未完成时，整体不能进已解决。
    labels = list(dict.fromkeys(active_labels))
    if len(labels) > 1 and target_status == "已解决" and completed_labels is not None:
        if not set(labels).issubset(set(completed_labels)):
            unfinished = [label for label in labels if label not in set(completed_labels)]
            target_status = "跟进中"
            waiting_reason = None
            resolution = None
            notes.append(f"多标签事项仍有未完责任（{'、'.join(unfinished)}），保持跟进中")

    # 排障恢复结果与非排障交付结果对齐，防止冒充已确认客户账号验收。
    if target_status == "已解决":
        has_incident = "排障" in labels
        if not has_incident and resolution in {"客户确认恢复", "支撑声明已修复"}:
            resolution = "已答复或已交付"
            notes.append("非排障事项统一归口为已答复或已交付")
        elif resolution == "客户确认恢复" and not has_customer_recovery:
            if "customer" in evidence_roles:
                # 已确认客户账号但未走 continuity.confirm_recovery 时仍保守核验。
                pass
            elif evidence_roles.intersection({"internal", "support"}):
                resolution = "支撑声明已修复"
                notes.append("未获已确认客户账号反馈，按支撑声明已修复记录，不写客户恢复确认")
            else:
                fallback = current_status if not created and current_status not in TERMINAL_STATUSES else "跟进中"
                fallback_wait = current_waiting_reason if fallback == "等待中" else None
                reviews.append(dict(
                    kind="unverified_recovery_actor",
                    field="status",
                    summary="恢复确认发送者身份未核实，状态待核对",
                    proposed=dict(status=target_status, waiting_reason=waiting_reason, resolution=resolution),
                    evidence_refs=refs,
                ))
                return dict(
                    adopted=created or fallback != current_status,
                    lifecycle_status=fallback,
                    waiting_reason=fallback_wait,
                    resolution=None,
                    detail=dict(
                        status=fallback,
                        waiting_reason=fallback_wait,
                        resolution=None,
                        reason=reason,
                        note="恢复确认发送者身份未核实",
                        source="automatic",
                        evidence_refs=refs,
                    ),
                    reopened=False,
                    review_items=reviews,
                )

    reopened = (not created and current_status == "已解决" and target_status in {"跟进中", "等待中"})
    if reopened:
        notes.append("解决后同一事项反馈仍未达成，重开原事件")

    changed = created or (
        (target_status, waiting_reason, resolution) != (current_status, current_waiting_reason, current_resolution)
    )
    return dict(
        adopted=changed or bool(refs),
        lifecycle_status=target_status,
        waiting_reason=waiting_reason,
        resolution=resolution,
        detail=dict(
            status=target_status,
            waiting_reason=waiting_reason,
            resolution=resolution,
            reason=reason,
            note="；".join(notes) if notes else None,
            source="automatic",
            reopened=reopened,
            evidence_refs=refs,
        ),
        reopened=reopened,
        review_items=reviews,
    )
