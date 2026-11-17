"""测试夹具显式使用隔离验收允许的临时目录，兼容 macOS 的系统临时目录设置。"""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest


@pytest.fixture
def acceptance_tmp_path():
    """验收文件只放 /tmp；不依赖 pytest 默认临时目录所在位置。"""
    with TemporaryDirectory(prefix="dake-acceptance-", dir="/tmp") as directory:
        yield Path(directory)
