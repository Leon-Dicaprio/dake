"""只读合成服务的离线保护检查；不监听端口、不连数据库、不运行浏览器。"""

import importlib.util

import pytest

from dake.config import Settings
from dake.repositories.mysql import MySQLStore, StorageError
from mysql_acceptance import ROOT, TestDatabase
from offline_http import TestClient, offline_only
from panel_preview import (BANNER, ReadOnlyStore, create_preview, read_manifest, validate_manifest_path,
                           validate_port, validate_reader_grants, write_manifest)


def target():
    return TestDatabase('127.0.0.1', 13327, 'dake_attempt_test_0123456789ab', 'dake_test_0123456789ab', 'synthetic-unused')


def cases():
    return [dict(uid='synthetic-mysql-preview', stream='stub-v1', event_id='synthetic-event', label='虚构跨天 <script>不可执行</script>')]


@pytest.mark.parametrize('port', [8000, 8001, 3306, 3307, 13327, 0, 65536])
def test_preview_rejects_business_or_shared_ports_before_any_connection(port):
    with pytest.raises(ValueError):
        validate_port(port, 13327)
    validate_port(18027, 13327)


def test_manifest_is_temporary_new_and_matches_the_explicit_database(tmp_path):
    file = tmp_path / 'panel-cases.json'
    write_manifest(file, target(), cases())
    assert not file.stat().st_mode & 0o077
    value = read_manifest(file, target())
    assert value['synthetic'] and value['cases'] == cases()
    assert 'password' not in file.read_text()
    with pytest.raises(ValueError):
        write_manifest(file, target(), cases())
    with pytest.raises(ValueError):
        read_manifest(file, TestDatabase('127.0.0.1', 13328, target().database, target().user, 'synthetic-unused'))
    with pytest.raises(ValueError):
        validate_manifest_path(ROOT / 'data/panel-cases.json')
    with pytest.raises(ValueError):
        validate_manifest_path(tmp_path / '.env')
    with pytest.raises(ValueError):
        write_manifest(tmp_path / 'empty.json', target(), [])


@pytest.mark.parametrize('privilege', ['ALL PRIVILEGES', 'SELECT, INSERT', 'SELECT, UPDATE', 'CREATE'])
def test_preview_requires_a_select_only_test_account(privilege):
    row = dict(grant=f"GRANT {privilege} ON `{target().database}`.* TO 'synthetic'@'%'")
    with pytest.raises(ValueError, match='SELECT'):
        validate_reader_grants([row], target().database, partial_revokes=True)


def test_read_only_connection_checks_identity_grants_and_session_without_mutating(monkeypatch):
    calls = []
    def connect(self, **options):
        assert options == target().options()
    def execute(self, sql, args=()):
        calls.append(sql)
        if sql.startswith('SELECT DATABASE'):
            return [dict(db=target().database, version='8.4.0', partial_revokes=1)], 1
        if sql == 'SHOW GRANTS':
            return [dict(grant=f"GRANT SELECT ON `{target().database}`.* TO 'synthetic'@'%'")], 1
        assert sql == 'SET SESSION TRANSACTION READ ONLY'
        return [], 0
    monkeypatch.setattr(MySQLStore, '__init__', connect)
    monkeypatch.setattr(MySQLStore, '_execute', execute)
    monkeypatch.setattr(MySQLStore, 'close', lambda self: None)
    store = ReadOnlyStore(**target().options())
    assert calls[-1] == 'SET SESSION TRANSACTION READ ONLY'
    before = list(calls)
    for sql in ('UPDATE events SET payload=NULL', 'CREATE TABLE forbidden(id INT)', 'DELETE FROM messages', 'SET SESSION TRANSACTION READ WRITE'):
        with pytest.raises(StorageError):
            store._execute(sql)
    assert calls == before


def test_read_only_http_reuses_page_but_exposes_no_task_or_write_routes(tmp_path):
    def forbidden(**options):
        pytest.fail('这些静态和拒绝请求不应连接数据库')
    (tmp_path / 'index.html').write_text('<!doctype html><html><head><title>事件页</title></head><body><div id="root"></div></body></html>')
    (tmp_path / 'app.js').write_text('/* 虚构测试静态文件 */')
    settings = Settings(uid=cases()[0]['uid'], data_dir=tmp_path)
    app = create_preview(settings, dict(cases=cases()), store_factory=forbidden, web_dist=tmp_path)
    with TestClient(app) as client:
        index = client.get('/__acceptance__')
        assert index.status_code == 200 and BANNER in index.text
        assert '<script>不可执行</script>' not in index.text and '&lt;script&gt;' in index.text
        page = client.get('/events')
        assert page.status_code == 200 and BANNER in page.text and '【虚构验收】' in page.text
        assert page.headers['X-Dake-Test-Data'] == 'synthetic-only'
        assert "connect-src 'self'" in page.headers['Content-Security-Policy']
        assert client.get('/app.js').status_code == 200
        for path in ('/api/v1/runs', '/api/v1/attempts/verify', '/api/v1/demo/sessions'):
            assert client.post(path, json={}).status_code == 405
            assert client.get(path).status_code == 404
        for method in ('PUT', 'PATCH', 'DELETE'):
            assert client.request(method, '/api/v1/events/synthetic-event').status_code == 405
        assert client.get('/api/v1/events/synthetic-event/changes', params=dict(uid='foreign-customer', stream='stub-v1')).status_code == 400
        assert client.get('/api/v1/events/synthetic-event/changes', params=dict(uid=cases()[0]['uid'], stream='foreign-stream')).status_code == 400
        assert client.get('/.env').status_code == 404
        assert client.get('/docs').status_code == 404


def test_preview_cli_rejects_existing_http_port_before_reading_password(tmp_path, capsys):
    spec = importlib.util.spec_from_file_location('synthetic_preview_entry', ROOT / 'scripts/serve_execution_panel.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.main(['--host', target().host, '--port', str(target().port), '--database', target().database,
        '--user', target().user, '--password-file', str(tmp_path/'nonexistent-password'),
        '--panel-manifest', str(tmp_path/'nonexistent-index'), '--http-port', '8000'])
    assert result == 2 and '未启动' in capsys.readouterr().err
