"""离线 HTTP 测试工具；不监听端口，不加载环境文件，不建立外部连接。"""

import asyncio
import socket

from fastapi.testclient import TestClient as StarletteTestClient
import pytest

from dake.config import Settings


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    """显式配置之外的路径一律失败，避免装配回归读取凭据或连接数据库。"""
    def forbidden(*args, **kwargs):
        raise RuntimeError("离线测试禁止默认配置、环境文件、数据库或网络连接")

    monkeypatch.setattr(Settings, "load", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr("dotenv.dotenv_values", forbidden)
    monkeypatch.setattr("dake.config.dotenv_values", forbidden)
    monkeypatch.setattr("pymysql.connect", forbidden)
    monkeypatch.setattr("dake.repositories.mysql.MySQLStore.__init__", forbidden)


def _loop_factory():
    """沙箱中跨线程唤醒可能不及时；仅测试循环加定时唤醒，不改应用并发逻辑。"""
    loop = asyncio.new_event_loop()

    def tick():
        loop.call_later(0.01, tick)

    tick()
    return loop


def TestClient(app, **kwargs):
    return StarletteTestClient(app, backend_options={"loop_factory": _loop_factory}, **kwargs)
