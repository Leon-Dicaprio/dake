"""可恢复的本地水位与私有快照；是否已处理以 MySQL 事务内的消息标记为准。"""

import hashlib
import fcntl
import json
import os
from pathlib import Path
import tempfile

from ..domain.models import json_value, parse_time


def private_json(path: Path, value: dict):
    """用权限 0600 的临时文件原子替换，避免半写文件或正文被其他用户读取。"""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".write-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(json_value(value), output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class LocalState:
    """管理 data/ 下的辅助状态，水位丢失后可依赖数据库去重重试。"""
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

    def key(self, uid: str, stream: str) -> str:
        """对客户与分析流生成稳定路径键，避免标识中的特殊字符影响文件路径。"""
        return hashlib.sha256(f"{uid}\0{stream}".encode()).hexdigest()[:32]

    def read(self, uid: str, stream: str) -> dict:
        """读取下次起点；不存在时从配置起点重新扫描。"""
        path = self.data_dir / "state" / (self.key(uid, stream) + ".json")
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def write(self, uid: str, stream: str, value: dict):
        """原子保存辅助水位；调用方通过 advance 保证单调推进。"""
        private_json(self.data_dir / "state" / (self.key(uid, stream) + ".json"), value)

    def advance(self, uid: str, stream: str, value: dict):
        """串行比较后推进水位，历史重放不能把下一次处理起点向前挪。"""
        # 数据库提交后仍可能有其他进程完成新窗口；文件锁避免旧水位覆盖新水位。
        path = self.data_dir / "state" / (self.key(uid, stream) + ".lock")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            previous = self.read(uid, stream)
            if not previous.get("next_start") or parse_time(previous["next_start"]) <= parse_time(value["next_start"]):
                self.write(uid, stream, value)

    def snapshot(self, result):
        """保存本窗口结果；空重试保留已保存记录，恢复结果由事务收据提供。"""
        path = self.snapshot_path(result.uid, result.stream, result.window)
        if path.exists() and not (result.processed or result.created or result.updated or result.review):
            return path
        private_json(path, result.to_dict())
        return path

    def snapshot_path(self, uid, stream, window):
        """使用明确的时间边界定位历史记录，不把不同周期的快照混为一份。"""
        start = window.start.strftime("%Y%m%dT%H%M%S%f")
        end = window.end.strftime("%Y%m%dT%H%M%S%f")
        return self.data_dir / "snapshots" / self.key(uid, stream) / f"{start}_{end}.json"

    def load_snapshot(self, uid, stream, window):
        """读取指定周期的历史结果，不重新分析消息。"""
        return json.loads(self.snapshot_path(uid, stream, window).read_text(encoding="utf-8"))
