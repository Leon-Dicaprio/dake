"""真实模型接入前的无外部调用占位分析器。"""


class StubProvider:
    """占位分析器不调用外部服务，也不为真实聊天捏造事件。"""

    name = "stub-v1"

    def extract(self, new_messages, context, existing_events):
        """返回空候选以验证链路；真实语义效果需在接入获准模型后验证。"""
        return []
