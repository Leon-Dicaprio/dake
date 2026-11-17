"""独立 MySQL 的定时增量网页验收，客户与消息全部虚构，禁止访问真实来源。"""

import argparse
from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile


def main():
    """显式连接参数先经隔离保护校验；仅在全新测试库初始化验收表。"""
    parser = argparse.ArgumentParser(description="虚构定时增量验收，不连接业务库或外部模型")
    for name in ("host", "database", "user", "password-file"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--http-port", type=int, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / "backend/src"), str(root / "backend/tests")]
    from mysql_acceptance import TestDatabase, install_guard, prepare_database, read_test_password
    from panel_preview import validate_port
    target = TestDatabase(args.host, args.port, args.database, args.user, read_test_password(args.password_file))
    validate_port(args.http_port, args.port)
    install_guard(target)
    def only_local_listener(event, values):
        if event == "socket.bind" and values[1] != ("127.0.0.1", args.http_port):
            raise RuntimeError("只允许监听显式指定的隔离网页端口")
    sys.addaudithook(only_local_listener)
    with tempfile.TemporaryDirectory(prefix="dake-scheduling-preview-") as directory:
        prepare_database(target, directory)
        from dake.api.app_factory import create_app
        from dake.analysis.providers import StubProvider
        from dake.domain.models import parse_time
        from dake.jobs.runner import RunRunner
        from dake.repositories.attempts import AttemptRepository
        from dake.repositories.mysql import MySQLStore
        from dake.repositories.runs import RunRepository
        from dake.services.processing import IncrementalService
        from dake.services.scheduled_customers import ScheduledCustomer
        from dake.services.scheduling import SchedulingService
        from fakes import FakeSource
        from fastapi.responses import FileResponse, HTMLResponse
        import uvicorn
        settings = target.settings(directory, uid="synthetic-schedule-browser-a", schedule_enabled=True,
                                   schedule_poll_seconds=1, start=parse_time("2038-06-01"), end=parse_time("2038-06-02"))
        class Customers:
            def load(self):
                return [ScheduledCustomer("synthetic-schedule-browser-a"), ScheduledCustomer("synthetic-schedule-browser-b")]
        @contextmanager
        def factory(configuration, **kwargs):
            store = MySQLStore(**target.options())
            try:
                yield IncrementalService(store, FakeSource(), StubProvider(), configuration,
                                         attempts=AttemptRepository(configuration))
            finally:
                store.close()
        runs = RunRepository(settings)
        schedule = SchedulingService(settings, customer_source=Customers(), service_factory=factory,
                                     clock=lambda: parse_time("2038-06-01T00:45:00"))
        runner = RunRunner(settings, runs, service_factory=factory)
        app = create_app(settings, run_repository=runs, runner=runner, scheduling_service=schedule)
        dist = root / "web/dist"
        @app.get("/schedules", response_class=HTMLResponse)
        def page():
            html = (dist / "index.html").read_text()
            return html.replace("<body>", '<body><div style="background:#fef3c7;padding:6px;text-align:center">隔离验收：全部为虚构客户、空消息及占位模型</div>', 1)
        @app.get("/{asset:path}")
        def assets(asset: str):
            path = (dist / asset).resolve()
            if path.is_relative_to(dist.resolve()) and path.is_file() and path.suffix in {".js", ".css", ".woff", ".woff2", ".svg", ".png", ".ico"}:
                return FileResponse(path)
            return HTMLResponse("虚构验收入口没有此资源", status_code=404)
        print(f"隔离虚构验收：http://127.0.0.1:{args.http_port}/schedules", flush=True)
        uvicorn.run(app, host="127.0.0.1", port=args.http_port, access_log=False, log_config=None)


if __name__ == "__main__":
    main()
