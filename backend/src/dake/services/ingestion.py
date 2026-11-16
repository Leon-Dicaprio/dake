"""共用的消息摄入流程：按来源取数、筛选业务窗口，再原子保存消息。"""

from datetime import date, datetime, timedelta
from typing import Protocol

from ..domain.models import Message, Window, message_order


class Source(Protocol):
    """来源实现只返回统一消息，官方日期粒度与业务周期由服务衔接。"""

    def load_day(self, uid: str, day: date) -> list[Message]:
        """返回客户该日的消息，不在源内分析业务事件。"""
        ...


class IngestionService:
    """按发送时间过滤当天接口响应，避免未来窗口消息提前入库或被分析。"""

    def __init__(self, store, source: Source):
        self.store = store
        self.source = source

    def load_window(self, uid: str, start: datetime, end: datetime) -> list[Message]:
        """允许重叠取数补漏，统一校验客户并按发送时间全局排序。"""
        day = start.date()
        last_day = (end - timedelta(microseconds=1)).date()
        messages = {}
        while day <= last_day:
            for message in self.source.load_day(uid, day):
                if message.uid != uid:
                    raise ValueError("适配器返回了其他客户的消息")
                if start <= message.sent_at < end:
                    messages[message.key] = message
            day += timedelta(days=1)
        return sorted(messages.values(), key=message_order)

    def fetch(self, uid: str, window: Window) -> int:
        """只取数、适配并保存消息，不推进分析水位，不生成事件。"""
        messages = self.load_window(uid, window.start, window.end)
        with self.store.transaction(uid):
            return self.store.upsert_messages(messages)
