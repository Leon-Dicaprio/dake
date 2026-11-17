"""与数据来源无关的消息、候选事件和事件合约；业务缺省不代表官方枚举。"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
import hashlib
import json
from typing import Any, Literal
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
EVENT_TYPES = ("商机", "流失", "排障", "资源需求", "功能需求", "商务需求")

# 人员角色用于聊天展示；业务判断仅接受已确认账号，不属于官方事件状态枚举。
SenderRole = Literal["internal", "support", "customer", "external", "unknown"]
# 技术身份轴，不属于官方事件状态或人员内外部角色。
SenderKind = Literal["human", "bot", "unknown"]


def parse_time(value: str | datetime) -> datetime:
    """统一为上海时区；接口不带时区的时间按上海本地时间解释。"""
    result = datetime.fromisoformat(value) if isinstance(value, str) else value
    return result.replace(tzinfo=TZ) if result.tzinfo is None else result.astimezone(TZ)


def json_value(value: Any) -> Any:
    """将嵌套时间转换为带时区的文本，供数据库 JSON 和本地快照保存。"""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


@dataclass(frozen=True)
class Message:
    """适配后的统一消息；internal_hint 只保留原始提示，不断言人员身份。"""
    uid: str
    message_id: str
    sent_at: datetime
    content: str
    source: str = "official_chat"
    conversation_id: str = ""
    conversation_name: str = ""
    sender_id: str = ""
    sender_name: str = ""
    internal_hint: int | None = None
    markers: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        """返回可持久化结构，其中正文仅可写入受保护的本地数据存储。"""
        return json_value(asdict(self))

    @classmethod
    def from_dict(cls, value: dict) -> "Message":
        """恢复数据库消息，保持发送时间的时区及附件标记。"""
        value = dict(value)
        value["sent_at"] = parse_time(value["sent_at"])
        value["markers"] = tuple(value.get("markers", ()))
        return cls(**value)

    @property
    def key(self) -> str:
        """来源与原消息 ID 共同定位证据，避免未来不同渠道的 ID 冲突。"""
        return f"{self.source}:{self.message_id}"

    @property
    def digest(self) -> str:
        """检测相同 ID 的消息修订，让修订内容能够重新进入增量分析。"""
        return hashlib.sha256(json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def message_order(message: Message) -> tuple:
    """跨群按发送时间排序；同秒数字 ID 按数值顺序，避免字符串排序歧义。"""
    mid = message.message_id
    return message.sent_at, (0, int(mid)) if mid.isdigit() else (1, mid), message.source


@dataclass(frozen=True)
class Window:
    """业务时间窗口统一使用左闭右开区间，避免相邻周期重复覆盖端点。"""
    start: datetime
    end: datetime

    def __post_init__(self):
        if self.start.tzinfo is None or self.end.tzinfo is None or self.start >= self.end:
            raise ValueError("窗口必须带时区且 start < end")


def windows(start: datetime, end: datetime, interval: timedelta):
    """按任意正周期切分范围；最后一个窗口可短于完整周期。"""
    if interval.total_seconds() <= 0 or start >= end:
        raise ValueError("处理周期须大于零，起始时间须早于结束时间")
    while start < end:
        stop = min(start + interval, end)
        yield Window(start, stop)
        start = stop


@dataclass
class Candidate:
    """Provider 输出的候选；证据必须引用输入消息，主题不明时进入复核。"""
    type: str
    topic_key: str | None
    summary: str
    evidence_ids: list[str]
    status: str | None = None
    severity: str | None = None
    assignees: list[str] = field(default_factory=list)
    attributes: dict = field(default_factory=dict)
    extensions: dict = field(default_factory=dict)
    ambiguous: bool = False
    referenced_event_id: str | None = None
    decision: Literal["new", "update", "duplicate", "review"] | None = None
    decision_reason: str = ""
    basis: list[dict] = field(default_factory=list)
    possible_event_ids: list[str] = field(default_factory=list)
    changes: list[dict] | None = None
    continuity: dict | None = None


@dataclass
class Event:
    """稳定事件身份及当前状态；证据和修订历史随更新追加，不丢失旧版本。"""
    event_id: str
    uid: str
    stream: str
    type: str
    topic_key: str | None
    start_time: datetime
    end_time: datetime
    status: str
    severity: str
    summary: str
    created_on: datetime
    assignees: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    attributes: dict = field(default_factory=dict)
    extensions: dict = field(default_factory=dict)
    updated_by: list[dict] = field(default_factory=list)
    review_flag: str | None = None
    closed_at: datetime | None = None
    schema_version: int = 1
    recovery: dict | None = None
    recurrence_of: dict | None = None

    def to_dict(self) -> dict:
        """导出完整事件，只供数据库和私有快照使用，不直接打印到日志。"""
        return json_value(asdict(self))

    @classmethod
    def from_dict(cls, value: dict) -> "Event":
        """从持久化结构恢复事件及其时间字段。"""
        value = dict(value)
        for key in ("start_time", "end_time", "created_on", "closed_at"):
            if value.get(key) is not None:
                value[key] = parse_time(value[key])
        return cls(**value)


@dataclass
class CycleResult:
    """一次处理的变化和事件快照，供命令行与后续接口复用。"""
    uid: str
    stream: str
    window: Window
    ingested: int = 0
    processed: int = 0
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    review: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    watermark: dict = field(default_factory=dict)
    filter_audit: list[dict] = field(default_factory=list)
    attempt_id: str | None = None
    recovered_from_attempt_id: str | None = None
    snapshot_scope: str = "customer"
    event_count: int | None = None

    def to_dict(self) -> dict:
        """导出周期结果；可能含证据，仅保存在 data/ 内。"""
        result = json_value(asdict(self))
        if self.recovered_from_attempt_id:
            result["recovered_from_history"] = True
        return result

    @classmethod
    def from_dict(cls, value: dict) -> "CycleResult":
        """恢复已保存的演示记录；额外恢复标记不参与本次业务结果。"""
        value = dict(value)
        value.pop("recovered_from_history", None)
        value.pop("counts_complete", None)
        value["window"] = Window(parse_time(value["window"]["start"]), parse_time(value["window"]["end"]))
        return cls(**value)
