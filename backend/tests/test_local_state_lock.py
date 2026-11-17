"""用合成水位验证跨进程文件锁在不同系统上保持互斥。"""

import subprocess
import sys

import portalocker

from dake.repositories.local_state import LocalState


def test_other_process_waits_and_cannot_regress_watermark(tmp_path):
    state = LocalState(tmp_path)
    path = tmp_path / "state" / (state.key("synthetic", "test") + ".lock")
    path.parent.mkdir()
    code = """
import sys
from pathlib import Path
from dake.repositories.local_state import LocalState
state = LocalState(Path(sys.argv[1]))
print('ready', flush=True)
state.advance('synthetic', 'test', {'next_start': '2026-11-17T00:15:00+08:00'})
"""
    process = None
    try:
        with path.open("a") as lock:
            portalocker.lock(lock, portalocker.LOCK_EX)
            process = subprocess.Popen([sys.executable, "-c", code, str(tmp_path)], stdout=subprocess.PIPE, text=True)
            assert process.stdout.readline().strip() == "ready"
            try:
                process.wait(timeout=0.3)
            except subprocess.TimeoutExpired:
                pass
            else:
                raise AssertionError("另一个进程提前穿过了文件锁")
            state.write("synthetic", "test", {"next_start": "2026-11-17T00:30:00+08:00"})
        assert process.wait(timeout=10) == 0
        assert state.read("synthetic", "test")["next_start"] == "2026-11-17T00:30:00+08:00"
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdout.close()
