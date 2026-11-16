"""复用已确认账号身份；展示回退与业务确认依据分开。"""

import json
from pathlib import Path
from typing import get_args

from ..domain.models import SenderRole

SenderRoles = dict[tuple[str, str, str], SenderRole]


def load_sender_roles(data_dir: Path) -> SenderRoles:
    """读取私有账号配置；按客户、来源和账号 ID 隔离，避免昵称重名误认。"""
    path = data_dir / "config" / "sender_roles.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        raise ValueError("本地发送者身份配置无法读取") from None
    if not isinstance(value, dict) or not isinstance(value.get("accounts"), list):
        raise ValueError("本地发送者身份配置格式无效")
    roles: SenderRoles = {}
    for account in value["accounts"]:
        if not isinstance(account, dict):
            raise ValueError("本地发送者身份配置格式无效")
        key = tuple(account.get(name) for name in ("uid", "source", "sender_id"))
        role = account.get("role")
        if not all(isinstance(part, str) and part.strip() for part in key) or role not in get_args(SenderRole):
            raise ValueError("本地发送者身份配置包含无效账号或角色")
        if key in roles:
            raise ValueError("本地发送者身份配置存在重复账号")
        roles[key] = role
    return roles


def sender_role(payload: dict, roles: SenderRoles | None = None) -> SenderRole:
    """已确认账号优先，其余按用户要求沿用原来的内部／客户展示规则。"""
    key = tuple(str(payload.get(name) or "") for name in ("uid", "source", "sender_id"))
    if roles and key in roles:
        return roles[key]
    hint = payload.get("internal_hint")
    # 官方标记语义仍待确认；这里兼容原有展示，不作为跟进人或归属核验依据。
    if type(hint) is int:
        if hint == 1:
            return "internal"
        if hint == 0:
            return "customer"
    return "unknown"


def confirmed_sender_role(payload: dict, roles: SenderRoles | None = None) -> SenderRole:
    """业务判断只接受已确认账号配置，不使用昵称或含义未确认的原始标记。"""
    key = tuple(str(payload.get(name) or "") for name in ("uid", "source", "sender_id"))
    return (roles or {}).get(key, "unknown")
