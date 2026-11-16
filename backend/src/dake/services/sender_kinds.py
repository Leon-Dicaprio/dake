"""已确认的人工／机器人身份，独立于内部／外部角色及原消息摘要。"""

import hashlib
import json
from pathlib import Path
from ..domain.models import SenderKind

SenderKinds = dict[tuple[str, str, str, str], SenderKind]
FILTER_VERSION = "confirmed-senders-v1"
BOT_POLICY = """
机器人通知规则：sender_kind 来自本地已确认账号配置，与内部／外部身份无关。
bot 消息只能作为辅助证据，纯告警或恢复通知不能独立创建或更新客户事件。
候选必须由本轮非机器人消息中的明确问题、诉求、影响讨论、排查或处理事实支持。
不能因为同一窗口有人说话、问候或回复收到，就将无关告警转成客户事件。
客户单方明确反馈即可产生事件，不要求内部回复。unknown 不等于机器人，不得直接过滤。
人工讨论确实引用或涉及告警时可以附上相关机器人证据，不能把自动恢复通知当成人工确认恢复。
"""


def load_sender_kinds(data_dir: Path) -> SenderKinds:
    """只接受明确账号及确认依据；格式错误时停止处理，不能悄悄丢弃规则。"""
    try:
        value = json.loads((data_dir / "config" / "sender_kinds.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        raise ValueError("本地人工／机器人配置无法读取") from None
    if not isinstance(value, dict) or not isinstance(value.get("accounts"), list):
        raise ValueError("本地人工／机器人配置格式无效")
    result: SenderKinds = {}
    for account in value["accounts"]:
        if not isinstance(account, dict):
            raise ValueError("本地人工／机器人配置格式无效")
        key = tuple(account.get(name) for name in ("uid", "source", "sender_id"))
        kind = account.get("kind")
        basis = account.get("basis")
        if (not all(isinstance(part, str) and part.strip() for part in key)
                or kind not in ("human", "bot", "unknown")
                or not isinstance(basis, str) or not basis.strip()):
            raise ValueError("人工／机器人配置须包含有效账号、身份和确认依据")
        group = account.get("conversation_id", "")
        if not isinstance(group, str) or ("conversation_id" in account and not group.strip()):
            raise ValueError("机器人配置中的群标识无效")
        key = (*key, group)
        if key in result:
            raise ValueError("人工／机器人配置包含重复账号")
        result[key] = kind
    return result


def sender_kind(payload: dict, kinds: SenderKinds | None = None) -> SenderKind:
    """不使用昵称或 internal_hint 推断身份，未配置即未知。"""
    key = tuple(str(payload.get(name) or "") for name in ("uid", "source", "sender_id"))
    group = str(payload.get("conversation_id") or "")
    configured = kinds or {}
    return configured.get((*key, group), configured.get((*key, ""), "unknown"))


def kinds_fingerprint(kinds: SenderKinds) -> str:
    """保存规则快照指纹供审计，不公开账号清单。"""
    return hashlib.sha256(json.dumps(sorted(kinds.items()), ensure_ascii=False).encode()).hexdigest()
