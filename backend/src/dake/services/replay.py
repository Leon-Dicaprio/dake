"""按范围回放、读取水位与单周期续跑，供命令行和后台任务共同调用。"""

from datetime import datetime, timedelta
from typing import Iterator

from ..domain.models import CycleResult, Window, parse_time, windows
from .processing import IncrementalService


class ReplayService:
    """只编排多个处理窗口；每个窗口复用同一增量引擎和幂等规则。"""

    def __init__(self, service: IncrementalService):
        self.service = service

    def run_range(self, uid: str, start: datetime, end: datetime,
                  interval: timedelta, *, run_id=None, retry_attempts=None, start_index=0) -> Iterator[CycleResult]:
        """逐窗口执行并立即产出结果，调用方可据此更新进度而无需等待全量完成。"""
        if not isinstance(start_index, int) or start_index < 0:
            raise ValueError("续跑窗口位置必须是非负整数")
        for index, window in enumerate(windows(start, end, interval)):
            if index < start_index:
                continue
            if getattr(self.service, "attempts", None) is None:
                yield self.service.run_window(uid, window)
            else:
                yield self.service.run_window(uid, window, execution=dict(run_id=run_id, window_index=index,
                    retry_of=(retry_attempts or {}).get(index)))

    def next_window(self, uid: str, start: datetime, end: datetime,
                    interval: timedelta, *, resume: bool = True) -> Window | None:
        """默认根据持久水位续跑；显式起点可关闭续跑，已到范围末尾时返回空。"""
        if interval.total_seconds() <= 0:
            raise ValueError("处理周期必须大于零")
        if resume:
            saved = self.service.state.read(uid, self.service.stream)
            if saved.get("next_start"):
                start = max(start, parse_time(saved["next_start"]))
        if start >= end:
            return None
        return Window(start, min(start + interval, end))

    def run_next(self, uid: str, start: datetime, end: datetime,
                 interval: timedelta, *, resume: bool = True) -> CycleResult | None:
        """只执行一个窗口，后续自动调度也应调用此方法以保持同样的续跑语义。"""
        window = self.next_window(uid, start, end, interval, resume=resume)
        return self.service.run_window(uid, window) if window else None

    def history_range(self, uid: str, start: datetime, end: datetime,
                      interval: timedelta) -> Iterator[CycleResult]:
        """只读取已实际执行并保存的快照，不重新分析，也不修改事件或水位。"""
        for window in windows(start, end, interval):
            yield CycleResult.from_dict(self.service.state.load_snapshot(uid, self.service.stream, window))
