"""接收其他模块产出的完整客户名单；不实现客户发现、等级判断或 UID 推断。"""

from dataclasses import dataclass
import json
from typing import Protocol

from ..ingestion.client import validate_uid


@dataclass(frozen=True)
class ScheduledCustomer:
    """上游已确认的客户范围，停用必须以明确状态表达。"""

    uid: str
    enabled: bool = True


class CustomerSource(Protocol):
    """上游适配器一次交付完整快照；失败须抛异常，不能返回伪空名单。"""

    def load(self) -> list[ScheduledCustomer]:
        """读取本次已确认名单，不在调度层执行发现或筛选。"""
        ...


class FileCustomerSource:
    """本地交接适配器；生产接口到位后替换此边界，真实 UID 仅留在 data 内。"""

    def __init__(self, data_dir):
        self.path = data_dir / "config/scheduled_customers.json"

    def load(self):
        """全量校验后才交付；缺文件、截断或冲突不会停用既有客户。"""
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if (not isinstance(value, dict) or value.get("schema_version") != 1
                or value.get("complete") is not True or not isinstance(value.get("customers"), list)):
            raise ValueError("客户名单须为明确标记完整的版本 1 快照")
        result, seen = [], set()
        for item in value["customers"]:
            if not isinstance(item, dict) or not {"uid", "enabled"} <= item.keys():
                raise ValueError("客户名单须包含 uid 与 enabled")
            validate_uid(item["uid"])
            if type(item["enabled"]) is not bool or item["uid"] in seen:
                raise ValueError("客户名单存在重复或无效启停状态")
            seen.add(item["uid"])
            result.append(ScheduledCustomer(item["uid"], item["enabled"]))
        return result
