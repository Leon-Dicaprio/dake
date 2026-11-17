"""命令行仅负责参数和脱敏展示；处理能力统一调用独立业务服务。"""

import argparse
from dataclasses import replace
import sys
import json
import threading

from .bootstrap import build_service
from .config import Settings, bound, duration
from .ingestion.adapter import AdapterError
from .ingestion.client import ChatRecordsError, validate_uid
from .domain.models import Window, parse_time
from .repositories.mysql import StorageError
from .services.replay import ReplayService
from .repositories.attempts import AttemptError


def parser() -> argparse.ArgumentParser:
    """共享参数采用同一套配置，日期结束值包含整天，时间戳结束值不包含端点。"""
    root = argparse.ArgumentParser(description="大客售后事件增量处理（一期）")
    root.add_argument("--env-file", default=None, help="本地配置文件，默认使用仓库根 .env")
    sub = root.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="在本项目的本地 MySQL 中建立两张表")
    schedule = sub.add_parser("schedule", help="配置、触发、查询或运行持续增量调度")
    actions = schedule.add_subparsers(dest="action", required=True)
    actions.add_parser("start", help="从选定日期开始，读取上游客户名单").add_argument("--start", required=True)
    actions.add_parser("tick", help="外部定时器单次触发，只提交每客户一个窗口")
    actions.add_parser("status", help="查询数据库中的真实进度和暂停原因")
    actions.add_parser("run", help="运行单实例定时编排及既有任务执行器")
    for action in ("pause", "resume"):
        actions.add_parser(action, help="暂停或显式恢复自动任务").add_argument("--id", required=True)
    for name, help_text in (
        ("fetch", "取数、适配并保存消息，不做分析"),
        ("process", "按配置或水位执行一个周期"),
        ("replay", "以配置周期连续回放指定范围"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--uid", help="客户 UID")
        command.add_argument("--start", help="上海时间，日期或 ISO 时间戳")
        command.add_argument("--end", help="日期含当天；ISO 时间戳不含端点")
        command.add_argument("--interval", type=duration, help="处理周期，例如 15m、1h、1d")
        command.add_argument("--offline", action="store_true", help="仅使用已保存的官方原始响应")
        if name == "process":
            command.add_argument("--retry-attempt", help="明确接续当前范围的执行 ID；已提交时只恢复展示")
    return root


def show_result(result):
    """控制台只显示时间、事件标识和计数；原文及摘要保存在私有快照中。"""
    if result.attempt_id:
        print(f"执行 ID：{result.attempt_id}")
    if result.recovered_from_attempt_id:
        print(f"恢复执行 {result.recovered_from_attempt_id} 的已提交结果；以下为原批次计数，本次未重新分析或写入事件。")
    start = result.window.start.strftime("%Y-%m-%d %H:%M")
    end = result.window.end.strftime("%Y-%m-%d %H:%M")
    print(f"[{start} → {end}) 摄入变化={result.ingested} 处理={result.processed} "
          f"新建={len(result.created)} 更新={len(result.updated)} 待确认={len(result.review)} "
          f"事件总数={result.event_count if result.event_count is not None else len(result.events)}")
    for label, ids in (("新建", result.created), ("更新", result.updated)):
        for event_id in ids:
            event = next(event for event in result.events if event["event_id"] == event_id)
            print(f"  {label} {event_id} 类型={event['type']} 证据数={len(event['evidence'])}")


def main(argv=None) -> int:
    """只解释参数和显示结果；装配、取数、续跑和回放均调用共用模块。"""
    args = parser().parse_args(argv)
    try:
        settings = Settings.load(args.env_file)
        if args.command == "schedule":
            from .api.app_factory import create_app
            application = create_app(settings, start_worker=False)
            services = application.state.services
            tasks, runner = services.tasks, services.runner
            if args.action == "start":
                existing = next((task for task in tasks.tasks.list() if task["config"]["name"] == "定时增量（CLI）"), None)
                if existing:
                    if bound(existing["config"]["start"]) != bound(args.start):
                        raise ValueError("已有定时任务起点不同，不能重置其进度")
                    result = existing
                else:
                    task = tasks.create(dict(name="定时增量（CLI）", mode="automatic", start_mode="specified",
                        start=args.start, interval="15m", retries=3, retry_delay="1m"))
                    result = tasks.action(task["task_id"], "resume")
            elif args.action == "tick":
                with services.runs.connection() as keeper:
                    rows, _ = keeper._execute("SELECT GET_LOCK(%s,0) AS ok", (services.runs.worker_lock,))
                    if rows and rows[0]["ok"] == 1:
                        try:
                            tasks.tick(force=True)
                        finally:
                            keeper._execute("SELECT RELEASE_LOCK(%s)", (services.runs.worker_lock,))
                result = dict(tasks=tasks.tasks.list())
            elif args.action == "status":
                result = dict(tasks=services.tasks.tasks.list())
            elif args.action in {"pause", "resume"}:
                result = tasks.action(args.id, args.action)
            else:
                services.runs.init_schema()
                tasks.tasks.init_schema()
                runner.start()
                print("任务中心定时增量运行中；客户独立推进，进度与执行权保存在 MySQL。")
                try:
                    threading.Event().wait()
                except KeyboardInterrupt:
                    pass
                finally:
                    runner.stop()
                return 0
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command != "init-db":
            settings = replace(
                settings, uid=args.uid or settings.uid,
                start=bound(args.start) if args.start else settings.start,
                end=bound(args.end, end=True) if args.end else settings.end,
                interval=args.interval or settings.interval,
            )
            settings.validate()
            validate_uid(settings.uid)
        with build_service(settings, offline=getattr(args, "offline", False)) as service:
            settings = service.settings
            replay = ReplayService(service)
            if args.command == "init-db":
                service.store.init_schema()
                print("本地 MySQL 消息表和事件表已就绪。")
                return 0
            if args.command == "fetch":
                count = service.fetch(settings.uid, Window(settings.start, settings.end))
                print(f"取数完成：新增或修订 {count} 条；已适配保存到本地 MySQL，原始响应位于 data/raw/。")
                return 0
            if settings.provider == "stub":
                print("当前 Provider=stub：仅验证增量链路，不生成真实分析结论，不调用外部模型。")
            if args.command == "process":
                if args.retry_attempt:
                    prior = service.attempts.get(settings.uid, service.stream, args.retry_attempt)
                    if prior is None:
                        raise AttemptError("当前客户和分析范围内未找到前次执行")
                    result = service.run_window(settings.uid, Window(parse_time(prior["window_start"]), parse_time(prior["window_end"])),
                                                execution=dict(retry_of=args.retry_attempt))
                else:
                    result = replay.run_next(settings.uid, settings.start, settings.end, settings.interval,
                                             resume=args.start is None)
                if result is None:
                    print("已处理至配置的结束时间；继续处理时请更新结束时间。")
                    return 0
                show_result(result)
            else:
                for result in replay.run_range(settings.uid, settings.start, settings.end, settings.interval):
                    show_result(result)
            print("本次状态与事件快照已保存在 data/state/、data/snapshots/。")
            return 0
    except (ChatRecordsError, AdapterError, StorageError) as error:
        # 这些异常由项目代码明确脱敏，可直接提供可操作的错误原因。
        print(str(error), file=sys.stderr)
        return 1
    except (ValueError, RuntimeError, OSError):
        # 第三方异常可能夹带输入正文、SQL 参数或路径；命令行不打印异常对象。
        print("执行未完成：请检查本地配置、MySQL、取数网络或缓存及输入格式；须先核实执行记录，不能据此认定可安全重试。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
