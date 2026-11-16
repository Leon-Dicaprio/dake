"""以独立 SELECT 账号提供虚构变化面板，只监听显式指定的本地测试端口。"""

import argparse
import os
from pathlib import Path
import sys
import tempfile


def parser():
    """没有业务连接或监听端口缺省值，也不加载 .env。"""
    result = argparse.ArgumentParser(description='独立 MySQL 虚构面板只读服务，不启动分析或后台任务')
    for name in ('host', 'database', 'user', 'password-file', 'panel-manifest'):
        result.add_argument('--' + name, required=True)
    result.add_argument('--port', type=int, required=True, help='独立 MySQL 端口')
    result.add_argument('--http-port', type=int, required=True, help='独立网页端口，禁止 8000/8001')
    return result


def main(argv=None):
    """先验证隔离目标、只读账号和案例存在；启动不执行任何建表或业务写入。"""
    args = parser().parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / 'backend/src'), str(root / 'backend/tests')]
    from mysql_acceptance import TestDatabase, install_guard, read_test_password
    from panel_preview import ReadOnlyStore, create_preview, read_manifest, validate_port
    from dake.domain.models import parse_time
    from dake.repositories.mysql import StorageError

    try:
        TestDatabase(args.host, args.port, args.database, args.user, 'validation-only')
        validate_port(args.http_port, args.port)
        target = TestDatabase(args.host, args.port, args.database, args.user, read_test_password(args.password_file))
        install_guard(target)
        def listener_guard(event, values):
            if event == 'socket.bind' and values[1] != ('127.0.0.1', args.http_port):
                raise RuntimeError('只允许监听本次明确指定的本地合成服务端口')
        sys.addaudithook(listener_guard)
        manifest = read_manifest(args.panel_manifest, target)
        if not (root / 'web/dist/index.html').is_file():
            raise ValueError('缺少现有前端构建；请先离线构建，不访问现有网页服务')
        with tempfile.TemporaryDirectory(prefix='dake-panel-preview-') as data_dir:
            os.environ.clear()
            os.environ.update(LLM_PROVIDER='stub', RUN_MYSQL_TESTS='0', DATA_DIR=data_dir)
            settings = target.settings(data_dir, uid=manifest['cases'][0]['uid'],
                start=parse_time('2038-06-01'), end=parse_time('2038-06-16'))
            store = ReadOnlyStore(**target.options())
            try:
                for case in manifest['cases']:
                    if not any(event.event_id == case['event_id'] for event in store.list_events(case['uid'], case['stream'])):
                        raise ValueError('虚构案例已缺失，拒绝用其他事件补造')
            finally:
                store.close()
            app = create_preview(settings, manifest)
            import uvicorn
            print(f'虚构数据只读入口（成功监听后可用）：http://127.0.0.1:{args.http_port}/__acceptance__', flush=True)
            uvicorn.run(app, host='127.0.0.1', port=args.http_port, access_log=False, log_config=None)
            return 0
    except (ValueError, StorageError) as error:
        print(f'只读合成服务未启动：{error}；未回落到其他数据库或端口。', file=sys.stderr)
        return 2
    except OSError as error:
        print(f'只读合成服务未启动（{type(error).__name__}）；未连接其他库或占用其他端口。', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
