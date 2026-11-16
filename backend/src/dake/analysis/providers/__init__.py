"""导出可替换的抽取协议与默认占位实现。"""

from .base import Provider
from .stub import StubProvider

__all__ = ["Provider", "StubProvider"]
