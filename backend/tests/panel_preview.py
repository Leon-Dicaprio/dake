"""隔离验收的只读网页装配；复用正式查询，不包含分析器、任务执行器或模拟剧情。"""

from html import escape
import json
import os
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from dake.api.dependencies import AppServices
from dake.api.routes.events import router
from dake.repositories.mysql import MySQLStore, StorageError
from dake.repositories.runs import RunRepository
from dake.services.queries import QueryService
from mysql_acceptance import ROOT, TestDatabase, validate_grants


BANNER = "隔离验收：全部为虚构测试数据 · 假模型返回 · 只读 · 不代表真实分析准确率"


def validate_port(port, mysql_port):
    """监听只允许独立端口，禁止覆盖业务 API、网页或测试数据库端口。"""
    if type(port) is not int or not 1024 <= port <= 65535 or port in {3306, 3307, 8000, 8001, mysql_port}:
        raise ValueError("只读服务必须显式指定独立端口，禁止 3306/3307/8000/8001 和 MySQL 端口")


def validate_manifest_path(value, *, new=False):
    """仅在临时目录读写本次索引，不接受私有数据路径，不覆盖已有文件。"""
    path = Path(value).resolve()
    if not path.is_relative_to(Path('/tmp')) or path.name.startswith('.env'):
        raise ValueError("案例索引必须位于 /tmp 且不是环境文件")
    if new and (path.exists() or not path.parent.is_dir()):
        raise ValueError("案例索引必须是已有临时目录中的新文件，不能覆盖已有索引")
    return path


def write_manifest(path, target, cases):
    """仅由专用验收入口在全部用例通过后写入案例身份，不含消息或连接密码。"""
    if not cases:
        raise ValueError("没有实际通过的面板案例，拒绝生成服务索引")
    path = validate_manifest_path(path, new=True)
    value = dict(version=1, synthetic=True, suite="execution-panel-mysql", database=target.database,
                 host=target.host, port=target.port, cases=cases)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w', encoding='utf-8') as output:
        json.dump(value, output, ensure_ascii=False, indent=2)


def read_manifest(path, target):
    """索引与数据库必须一致；入口只接受新造的测试客户和明确分析范围。"""
    path = validate_manifest_path(path)
    if path.stat().st_size > 128 * 1024:
        raise ValueError("案例索引大小异常")
    value = json.loads(path.read_text(encoding='utf-8'))
    if (value.get('version') != 1 or value.get('synthetic') is not True or
            value.get('suite') != 'execution-panel-mysql' or
            (value.get('host'), value.get('port'), value.get('database')) != (target.host, target.port, target.database)):
        raise ValueError("案例索引不是当前明确指定的隔离库验收结果")
    cases = value.get('cases')
    if not isinstance(cases, list) or not cases:
        raise ValueError("案例索引没有可查看的事件")
    for case in cases:
        if (not isinstance(case, dict) or not str(case.get('uid', '')).startswith('synthetic-mysql-') or
                case.get('stream') != 'stub-v1' or not case.get('event_id') or not case.get('label')):
            raise ValueError("索引包含未明确标示的虚构案例")
    return value


def validate_reader_grants(rows, database, *, partial_revokes):
    """只读服务必须使用独立的 SELECT 账号，不能使用验收写入账号。"""
    validate_grants(rows, database, partial_revokes=partial_revokes)
    selects = []
    for row in rows:
        grant = next(iter(row.values()))
        if not (grant.startswith('GRANT USAGE ON *.* TO ') or grant.startswith('GRANT SELECT ON ')):
            raise ValueError("只读服务账号只能拥有该测试库的 SELECT 权限")
        selects.append(grant.startswith('GRANT SELECT ON '))
    if not any(selects):
        raise ValueError("只读账号缺少该测试库的 SELECT 权限")


class ReadOnlyStore(MySQLStore):
    """每个连接都核对目标和只读授权；服务没有建表或业务写入入口。"""

    def __init__(self, **options):
        target = TestDatabase(**options)
        super().__init__(**target.options())
        try:
            rows, _ = self._execute('SELECT DATABASE() AS db, VERSION() AS version, @@GLOBAL.partial_revokes AS partial_revokes')
            if not rows or rows[0]['db'] != target.database or not rows[0]['version'].startswith('8.4.'):
                raise ValueError("只读服务连接目标不是指定的 MySQL 8.4 隔离库")
            grants, _ = self._execute('SHOW GRANTS')
            validate_reader_grants(grants, target.database, partial_revokes=bool(rows[0]['partial_revokes']))
            super()._execute('SET SESSION TRANSACTION READ ONLY')
        except Exception:
            self.close()
            raise

    def _execute(self, statement, args=()):
        if not (statement.startswith('SELECT ') or statement == 'SHOW GRANTS'):
            raise StorageError("合成服务拒绝非查询 SQL")
        return super()._execute(statement, args)


def create_preview(settings, manifest, *, store_factory=ReadOnlyStore, web_dist=None):
    """只注册原有 GET 路由及现有构建文件；不执行正式应用的建表生命周期。"""
    allowed = {case['uid'] for case in manifest['cases']}

    class SyntheticQueries(QueryService):
        def scope(self, uid=None, stream=None):
            if (uid or self.settings.uid) not in allowed:
                raise ValueError("此只读入口只允许案例索引中的虚构客户")
            return super().scope(uid, stream)

        def config(self):
            value = super().config()
            value['customers'] = [dict(c, label='虚构验收客户 · ' + c['uid'])
                                  for c in value['customers'] if c['uid'] in allowed]
            return value

    queries = SyntheticQueries(settings, store_factory)
    runs = RunRepository(settings, store_factory)
    app = FastAPI(title=BANNER, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.services = AppServices(settings, queries, runs, None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])

    @app.middleware('http')
    async def read_only(request: Request, call_next):
        if request.method not in {'GET', 'HEAD'}:
            return JSONResponse(dict(detail='虚构验收服务只读，不允许分析、重试、核实或写入'), status_code=405)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Dake-Test-Data'] = 'synthetic-only'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'self'; connect-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:"
        return response

    @app.exception_handler(ValueError)
    async def invalid_scope(request, error):
        return JSONResponse(dict(detail='虚构案例的客户、范围或配置不匹配'), status_code=400)

    @app.exception_handler(StorageError)
    async def unavailable(request, error):
        return JSONResponse(dict(detail='隔离测试库查询失败，未回落到其他数据库'), status_code=503)

    app.include_router(router)
    dist = Path(web_dist or ROOT / 'web/dist').resolve()

    @app.get('/__acceptance__', response_class=HTMLResponse)
    def cases():
        links = ''.join('<li><a href="/events?' + escape(urlencode(dict(uid=c['uid'], stream=c['stream'], event=c['event_id'])), quote=True)
                        + '">' + escape(c['label']) + '</a></li>' for c in manifest['cases'])
        return '<!doctype html><meta charset="utf-8"><title>虚构面板验收</title><h1>' + BANNER + '</h1><p>直接查询独立 MySQL；只读页面不会推动处理或重试。步骤以已保存记录为准。</p><ul>' + links + '</ul>'

    @app.get('/')
    def landing():
        return RedirectResponse('/__acceptance__')

    @app.get('/{asset:path}')
    def frontend(asset: str):
        if asset == 'events':
            index = dist / 'index.html'
            if not index.is_file():
                return JSONResponse(dict(detail='缺少现有前端构建，请先离线构建'), status_code=503)
            html = index.read_text(encoding='utf-8')
            banner = '<div style="position:fixed;top:0;left:50%;transform:translateX(-50%);z-index:9999;background:#fef3c7;color:#713f12;padding:3px 8px;font:12px sans-serif">' + BANNER + ' · <a href="/__acceptance__">案例目录</a></div>'
            return HTMLResponse(html.replace('<title>', '<title>【虚构验收】', 1).replace('<body>', '<body>' + banner, 1))
        file = (dist / asset).resolve()
        if file.is_relative_to(dist) and not any(part.startswith('.') for part in Path(asset).parts) and file.is_file() and file.suffix in {'.js', '.css', '.svg', '.png', '.ico', '.woff', '.woff2'}:
            return FileResponse(file)
        return JSONResponse(dict(detail='只读合成入口没有此资源'), status_code=404)

    return app
