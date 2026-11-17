"""隔离 MySQL 验收专用工具；不读取应用配置，不提供业务库连接缺省值。"""

from dataclasses import dataclass, field
import os
from pathlib import Path
import re

from dake.config import Settings
from dake.repositories.mysql import MySQLStore
from dake.repositories.runs import RunRepository


ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class TestDatabase:
    """仅接受明确的临时实例和专用账号，密码不进入错误或对象文本。"""

    __test__ = False
    host: str
    port: int
    database: str
    user: str
    password: str = field(repr=False)

    def __post_init__(self):
        if self.host != "127.0.0.1" or type(self.port) is not int or not 1024 <= self.port <= 65535 or self.port in {3306, 3307, 8000, 8001}:
            raise ValueError("须显式指定 127.0.0.1 的独立测试端口，禁止 3306/3307/8000/8001")
        if not re.fullmatch(r"dake_attempt_test_[0-9a-f]{12,32}", self.database):
            raise ValueError("测试库名必须为 dake_attempt_test_ 加 12 至 32 位小写十六进制随机后缀")
        if not re.fullmatch(r"dake_test_[0-9a-f]{12,20}", self.user):
            raise ValueError("必须使用 dake_test_ 加随机后缀的专用测试账号，禁止 root 或业务账号")
        if not self.password:
            raise ValueError("必须提供本次临时测试账号的密码")

    def options(self):
        """所有连接参数显式提供，没有回落到 Settings.load 的路径。"""
        return dict(host=self.host, port=self.port, database=self.database, user=self.user, password=self.password)

    def settings(self, data_dir, **overrides):
        """只构造配置对象，不读取 .env；文件产物限定在本次临时目录。"""
        return Settings(mysql_host=self.host, mysql_port=self.port, mysql_database=self.database,
            mysql_user=self.user, mysql_password=self.password, data_dir=Path(data_dir),
            provider="stub", **overrides)


def read_test_password(path):
    """仅接受 /tmp 内新建的私有测试密码文件，不使用业务密钥或 .env。"""
    path = Path(path).resolve()
    if not path.is_relative_to(Path("/tmp").resolve()) or path.name.startswith(".env"):
        raise ValueError("测试密码文件须位于 /tmp，且不能是 .env")
    if path.stat().st_mode & 0o077:
        raise ValueError("测试密码文件须为私有权限，例如 600")
    if not 1 <= path.stat().st_size <= 256:
        raise ValueError("测试密码文件长度无效")
    return path.read_text(encoding="utf-8").strip()


def install_guard(target):
    """进程级保护只允许该临时端口，阻止私有数据和环境文件读取。"""
    import sys
    private = [ROOT / "data", ROOT / "backend/tests/fixtures/analysis"]

    def guard(event, args):
        if event in {"socket.connect", "socket.getaddrinfo"}:
            address = args[1] if event == "socket.connect" else args[:2]
            if not isinstance(address, tuple) or address[:2] != (target.host, target.port):
                raise RuntimeError("验收仅允许连接显式指定的隔离 MySQL 端口")
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0])).resolve()
            if path.name.startswith(".env") or any(path == base or base in path.parents for base in private):
                raise RuntimeError("验收禁止读取环境文件、真实数据或私有夹具")
    sys.addaudithook(guard)


def validate_grants(rows, database, *, partial_revokes):
    """核对字面库名；未启用 partial_revokes 时下划线必须转义，不能授予模式范围。"""
    if not rows:
        raise ValueError("无法核对测试账号权限，停止验收")
    allowed = {database.replace("_", "\\_")}
    if partial_revokes:
        allowed.add(database)
    for row in rows:
        grant = next(iter(row.values()))
        usage = grant.startswith("GRANT USAGE ON *.* TO ")
        scoped = any(" ON `" + name + "`.* TO " in grant for name in allowed)
        if not (usage or scoped) or "WITH GRANT OPTION" in grant:
            raise ValueError("测试账号存在超出指定测试库的权限或通配授权，停止验收")


def prepare_database(target, data_dir, *, store_factory=MySQLStore):
    """先核对库名、版本、权限及空库，再只在这个测试库创建验收所需四张表。"""
    store = store_factory(**target.options())
    try:
        rows, _ = store._execute("SELECT DATABASE() AS db, VERSION() AS version, @@GLOBAL.partial_revokes AS partial_revokes")
        if not rows or rows[0]["db"] != target.database or not rows[0]["version"].startswith("8.4."):
            raise ValueError("连接目标不是明确指定的 MySQL 8.4 测试库，停止验收")
        partial_revokes = bool(rows[0]["partial_revokes"])
        rows, _ = store._execute("SHOW GRANTS")
        validate_grants(rows, target.database, partial_revokes=partial_revokes)
        rows, _ = store._execute("SHOW TABLES")
        if rows:
            raise ValueError("验收要求全新空测试库，禁止覆盖已有表；请换本次新建的测试库")
        store.init_schema()
        migration = ROOT / "backend/migrations/001_processing_attempts.sql"
        store._execute(migration.read_text(encoding="utf-8"))
        store._execute((ROOT / "backend/migrations/002_event_link_hints.sql").read_text(encoding="utf-8"))
        for statement in (ROOT / "backend/migrations/003_processing_schedules.sql").read_text(encoding="utf-8").split(";"):
            if statement.strip():
                store._execute(statement)
        RunRepository(target.settings(data_dir), store_factory=store_factory).init_schema()
    finally:
        store.close()


class DatabasePlugin:
    """只向专用测试文件提供已核验的目标，不启用旧 RUN_MYSQL_TESTS 入口。"""

    def __init__(self, target):
        self.target = target

    def pytest_configure(self, config):
        config._dake_isolated_mysql = self.target
        self.panel_cases = config._dake_panel_cases = []
