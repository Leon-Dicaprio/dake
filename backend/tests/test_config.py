"""验证周期、日期边界和配置隔离，防止命令行与后续调用入口解释不一致。"""

from datetime import timedelta

import pytest

from dake.cli import parser
from dake.config import PROJECT_ROOT, Settings, bound, duration
from dake.domain.models import CycleResult, Window, windows


@pytest.mark.parametrize("text,seconds", [("15m", 900), ("1h", 3600), ("1d", 86400)])
def test_configurable_intervals(text, seconds):
    assert duration(text).total_seconds() == seconds


@pytest.mark.parametrize("text", ["0m", "-1h", "daily", "1.5h"])
def test_invalid_interval_rejected(text):
    with pytest.raises(ValueError):
        duration(text)


def test_date_end_is_inclusive_but_timestamp_end_is_exclusive():
    assert bound("2026-11-12", end=True) == bound("2026-11-13T00:00:00")
    assert bound("2026-11-12T12:30:00", end=True) == bound("2026-11-12T12:30:00")
    assert bound("2026-11-12T00:00:00Z").hour == 8


def test_env_windows_are_independent_and_password_is_not_in_repr(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    env = tmp_path / ".env"
    env.write_text("PROCESS_INTERVAL=1h\nCONTEXT_LOOKBACK=2d\nMATCH_WINDOW=9d\n"
                   "MYSQL_PASSWORD=synthetic-test-secret\nPROCESS_START=2026-11-08\nPROCESS_END=2026-11-12\n"
                   "API_ALLOWED_HOSTS=localhost, 192.0.2.10\n")
    settings = Settings.load(env)
    assert settings.interval == timedelta(hours=1)
    assert settings.context_lookback == timedelta(days=2)
    assert settings.match_window == timedelta(days=9)
    assert settings.api_allowed_hosts == ("localhost", "192.0.2.10")
    assert "synthetic-test-secret" not in repr(settings)
    assert settings.default_status == settings.default_severity == "未知"


def test_cli_daily_replay_is_an_interval_override():
    args = parser().parse_args(["replay", "--interval", "1d", "--offline"])
    assert args.interval == timedelta(days=1)
    assert args.offline
    assert len(list(windows(bound("2026-11-08"), bound("2026-11-12", end=True), args.interval))) == 5


def test_cycle_snapshot_roundtrip_accepts_recovery_metadata():
    original = CycleResult("synthetic-customer", "stub-v1", Window(bound("2026-11-08"), bound("2026-11-09")))
    payload = original.to_dict()
    payload["recovered_from_history"] = True
    assert CycleResult.from_dict(payload) == original


@pytest.mark.parametrize("directory", ["root", "backend", "outside"])
def test_default_config_and_data_are_independent_of_working_directory(tmp_path, monkeypatch, directory):
    env = tmp_path / "default.env"
    env.write_text("PROCESS_UID=synthetic-default\nMYSQL_PASSWORD=synthetic-secret\nDATA_DIR=data\n")
    monkeypatch.setattr("dake.config.DEFAULT_ENV_FILE", env)
    target = {"root": PROJECT_ROOT, "backend": PROJECT_ROOT / "backend", "outside": tmp_path}[directory]
    monkeypatch.chdir(target)
    settings = Settings.load()
    assert settings.uid == "synthetic-default"
    assert settings.data_dir == PROJECT_ROOT / "data"
    assert Settings().data_dir == PROJECT_ROOT / "data"


def test_explicit_env_file_does_not_fall_back_to_default_secrets(tmp_path, monkeypatch):
    default = tmp_path / "default.env"
    default.write_text("MYSQL_PASSWORD=default-must-not-be-read\nPROCESS_UID=default-customer\n")
    explicit = tmp_path / "selected.env"
    explicit.write_text("PROCESS_UID=selected-customer\n")
    monkeypatch.setattr("dake.config.DEFAULT_ENV_FILE", default)
    monkeypatch.delenv("MYSQL_PASSWORD", raising=False)
    monkeypatch.chdir(tmp_path)
    settings = Settings.load("selected.env")
    assert settings.uid == "selected-customer"
    assert settings.mysql_password == ""
    assert settings.data_dir == PROJECT_ROOT / "data"
