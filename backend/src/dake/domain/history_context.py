"""仅供分析阅读的旧聊天包，与新增消息及可写入的事件证据分开。"""

from dataclasses import dataclass, field
from datetime import datetime
import json


CONTEXT_VERSION = "local-evidence-context-v1"


@dataclass
class HistoryContextResult:
    """绑定一次输入的只读背景；缺失和预算限制不表示可以新建或合并。"""

    uid: str
    stream: str
    before: datetime
    input_versions: tuple[tuple[str, str], ...]
    context_versions: tuple[tuple[str, str], ...]
    event_ids: tuple[str, ...]
    items: list[dict] = field(default_factory=list, repr=False)
    reasons: set[str] = field(default_factory=set)
    omitted: int = 0
    queries: int = 0

    def to_input(self):
        """保留版本和来源；窗口记录无法证明真实到达时间，不能冒充完整历史还原。"""
        return dict(version=CONTEXT_VERSION, mode="forward_only", before=self.before.isoformat(),
                    visibility="recorded_windows_only", arrival_history_available=False,
                    items=self.items, reasons=sorted(self.reasons), omitted=self.omitted, queries=self.queries,
                    incomplete=bool(self.reasons or self.omitted))

    def chars(self):
        """字符预算包含背景正文、来源、缺失原因和其他序列化开销。"""
        return len(json.dumps(self.to_input(), ensure_ascii=False))

    def add(self, item, limits):
        """保留有界副本；一个超长条目不会阻止后续较短条目获得名额。"""
        self.items.append(item)
        if len(self.items) > limits.max_messages or self.chars() > limits.max_chars:
            self.items.pop()
            self.omitted += 1
            self.reasons.add("context_budget")

    def finish(self, limits):
        """最后再次计入限制元数据，避免刚好贴近预算时越界。"""
        while self.chars() > limits.max_chars and self.items:
            self.items.pop()
            self.omitted += 1
            self.reasons.add("context_budget")
        return self
