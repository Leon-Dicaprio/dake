"""模型实现与业务流程之间的可替换协议。"""

from typing import Protocol
from ...domain.models import Candidate, Event, Message


class Provider(Protocol):
    """真实模型接入时实现此协议，核心流程无需依赖特定模型服务。"""

    # name 标识事件与消息消费范围；增量策略另记版本，不因升级自动重洗已有消息。
    name: str

    def extract(self, new_messages: list[Message], context: list[Message],
                existing_events: list[Event]) -> list[Candidate]:
        """仅从新增消息产出候选，历史消息和已有事件只提供理解上下文。"""
        ...
