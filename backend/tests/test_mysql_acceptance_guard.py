"""不连接数据库地验证隔离验收入口会拒绝业务目标、过大权限和已有表。"""

from dataclasses import replace
import importlib.util
from pathlib import Path

import pytest

from offline_http import offline_only
from mysql_acceptance import ROOT, TestDatabase, prepare_database, read_test_password, validate_grants


def target(**changes):
    value = TestDatabase("127.0.0.1", 13317, "dake_attempt_test_abcdef123456", "dake_test_abcdef123456", "synthetic-unused")
    return replace(value, **changes)


@pytest.mark.parametrize("changes", [
    dict(host="localhost"), dict(host="192.0.2.1"), dict(port=3306), dict(port=3307), dict(port=8000), dict(port=8001), dict(port=0),
    dict(database="dake_aftersales"), dict(database="dake_attempt_test_"),
    dict(user="root"), dict(user="dake"), dict(password=""),
])
def test_unsafe_or_incomplete_target_is_rejected_without_connection(changes):
    with pytest.raises(ValueError):
        target(**changes)


def test_explicit_target_never_uses_application_defaults(tmp_path):
    configured = target()
    settings = configured.settings(tmp_path, uid="synthetic-only")
    assert settings.store_kwargs() == configured.options()
    assert "synthetic-unused" not in repr(configured) and "synthetic-unused" not in repr(settings)
    assert settings.data_dir == tmp_path and settings.provider == "stub"


@pytest.mark.parametrize("problem", ["database", "version", "global_grant", "other_database_grant", "existing_tables", "no_grants"])
def test_preflight_stops_before_any_ddl_when_target_is_not_safe(tmp_path, problem):
    configured = target()
    calls = []
    class Store:
        def __init__(self, **options):
            assert options == configured.options()
        def _execute(self, sql, args=()):
            calls.append(sql)
            if sql.startswith("SELECT DATABASE"):
                return [dict(db="wrong_database" if problem == "database" else configured.database,
                             version="8.0.0" if problem == "version" else "8.4.0", partial_revokes=1)], 1
            if sql == "SHOW GRANTS":
                grants = ["GRANT USAGE ON *.* TO 'synthetic'@'%'", f"GRANT ALL PRIVILEGES ON `{configured.database}`.* TO 'synthetic'@'%'"]
                if problem == "global_grant": grants.append("GRANT ALL PRIVILEGES ON *.* TO 'synthetic'@'%'")
                if problem == "other_database_grant": grants.append("GRANT SELECT ON `other_database`.* TO 'synthetic'@'%'")
                return ([dict(grant=g) for g in grants] if problem != "no_grants" else []), 1
            if sql == "SHOW TABLES":
                return ([dict(table="already_exists")] if problem == "existing_tables" else []), 0
            pytest.fail("未核实隔离性前不得建表或执行迁移")
        def init_schema(self):
            pytest.fail("未核实隔离性前不得建表")
        def close(self):
            calls.append("closed")
    with pytest.raises(ValueError):
        prepare_database(configured, tmp_path, store_factory=Store)
    assert calls[-1] == "closed"


def test_password_file_must_be_explicit_private_and_temporary(acceptance_tmp_path):
    tmp_path = acceptance_tmp_path
    path = tmp_path / "test-password"
    path.write_text("synthetic-unused", encoding="utf-8")
    path.chmod(0o600)
    assert read_test_password(path) == "synthetic-unused"
    path.chmod(0o644)
    with pytest.raises(ValueError, match="私有权限"):
        read_test_password(path)
    with pytest.raises(ValueError):
        read_test_password(ROOT / ".env")
    with pytest.raises(ValueError):
        read_test_password(tmp_path / ".env")


def test_command_requires_all_connection_arguments_and_has_no_default(capsys):
    path = ROOT / "scripts/verify_execution_mysql.py"
    spec = importlib.util.spec_from_file_location("synthetic_mysql_entry", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(SystemExit) as result:
        module.parser().parse_args([])
    assert result.value.code == 2
    assert "--database" in capsys.readouterr().err


@pytest.mark.parametrize("partial_revokes,escaped", [(False, False), (False, True), (True, False), (True, True)])
def test_database_underscore_cannot_silently_grant_other_database_patterns(partial_revokes, escaped):
    database = target().database
    grant_name = database.replace("_", "\\_") if escaped else database
    rows = [dict(grant=f"GRANT ALL PRIVILEGES ON `{grant_name}`.* TO 'synthetic'@'%'")]
    if not partial_revokes and not escaped:
        with pytest.raises(ValueError, match="通配授权"):
            validate_grants(rows, database, partial_revokes=partial_revokes)
    else:
        validate_grants(rows, database, partial_revokes=partial_revokes)
