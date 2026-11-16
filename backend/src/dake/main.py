"""本地启动入口；离线测试应导入无默认配置读取的 api.app_factory。"""

from .api.app_factory import create_app
from .config import Settings

app = create_app(Settings.load())
