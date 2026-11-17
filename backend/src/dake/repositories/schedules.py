"""定时状态与队列关联持久化；提交任务和绑定进度使用同一数据库事务。"""

from contextlib import contextmanager
from datetime import datetime, timedelta
import hashlib
import json
from uuid import uuid4

from ..domain.models import TZ
from .runs import RunConflict, RunRepository, _encoded


class ScheduleRepository(RunRepository):
    """与手动任务共用提交锁；编排锁只保护短事务，不覆盖模型处理时间。"""

    @contextmanager
    def orchestration(self):
        """多个定时触发器只允许一个编排者；连接异常仍由原子队列绑定防重。"""
        with self.connection() as store:
            name = self.submit_lock + ":schedule"
            rows, _ = store._execute("SELECT GET_LOCK(%s,0) AS ok", (name,))
            acquired = bool(rows and rows[0]["ok"] == 1)
            try:
                yield acquired
            finally:
                if acquired:
                    store._execute("SELECT RELEASE_LOCK(%s)", (name,))

    @staticmethod
    def row(value):
        """内部模板不通过状态接口公开；日期统一返回带时区文本。"""
        item = dict(value)
        if isinstance(item.get("template"), (str, bytes)):
            item["template"] = json.loads(item["template"])
        item["enabled"] = bool(item.get("enabled", True))
        for key in ("last_turn", "last_tick"):
            if isinstance(item.get(key), datetime):
                item[key] = item[key].replace(tzinfo=TZ).isoformat()
        if item.get("start_date"):
            item["start_date"] = str(item["start_date"])
        return item

    def control(self):
        """调度表须显式迁移，查询不隐式建表。"""
        with self.connection() as store:
            rows, _ = store._execute("SELECT * FROM scheduler_control WHERE id=1")
        return self.row(rows[0]) if rows else None

    def configure(self, start_date, template):
        """首次固定起点及执行策略，重复启动不重置客户进度或切换分析版本。"""
        with self.connection() as store, store.transaction("scheduler-control"):
            rows, _ = store._execute("SELECT * FROM scheduler_control WHERE id=1 FOR UPDATE")
            if rows:
                current = self.row(rows[0])
                if current["start_date"] != start_date or current["template"] != template:
                    raise ValueError("已配置的起点或分析策略不同；不能通过重新启动重置历史进度")
            else:
                store._execute("INSERT INTO scheduler_control (id,start_date,template) VALUES (1,%s,%s)",
                               (start_date, _encoded(template)))

    def sync(self, customers, control):
        """完整名单事务同步；消失的客户停用，原进度、暂停和重试状态始终保留。"""
        template = control["template"]
        fingerprint = hashlib.sha256(_encoded(sorted((c.uid, c.enabled) for c in customers)).encode()).hexdigest()
        if control.get("customer_fingerprint") == fingerprint:
            return
        with self.connection() as store, store.transaction("scheduler-control"):
            store._execute("UPDATE processing_schedules SET enabled=FALSE")
            for customer in customers:
                store._execute("""INSERT INTO processing_schedules
                    (schedule_id,uid,stream,enabled,business_start,next_start,template)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE enabled=VALUES(enabled)""",
                    (str(uuid4()), customer.uid, template["analysis_stream"], customer.enabled,
                     template["business_start"], template["business_start"], _encoded(template)))
            store._execute("UPDATE scheduler_control SET source_error=NULL,customer_fingerprint=%s WHERE id=1", (fingerprint,))

    def observed(self, now, error=None):
        """记录定时器存活及名单读取结果，失败不会改写启用范围。"""
        with self.connection() as store:
            store._execute("UPDATE scheduler_control SET last_tick=%s,source_error=%s WHERE id=1",
                           (now.replace(tzinfo=None), error))

    def schedules(self, ready_at=None):
        """按上次实际入队时间轮转；停用及暂停记录也保留供查询与恢复。"""
        with self.connection() as store:
            if ready_at is None:
                rows, _ = store._execute("SELECT * FROM processing_schedules ORDER BY last_turn,schedule_id")
            else:
                rows, _ = store._execute("SELECT * FROM processing_schedules WHERE active_run_id IS NOT NULL OR "
                    "(enabled=TRUE AND status='active' AND (retry_at IS NULL OR retry_at<=%s) AND next_start<=%s) "
                    "ORDER BY last_turn,schedule_id LIMIT 128", (ready_at.isoformat(), (ready_at - timedelta(minutes=15)).isoformat()))
        return [self.row(row) for row in rows]

    def get_schedule(self, schedule_id):
        with self.connection() as store:
            rows, _ = store._execute("SELECT * FROM processing_schedules WHERE schedule_id=%s", (schedule_id,))
        return self.row(rows[0]) if rows else None

    def update(self, schedule_id, *, expected_run=None, **fields):
        """只允许编排字段，处理终态采用任务 ID 条件更新以承受重复对账。"""
        allowed = {"status", "next_start", "active_run_id", "last_run_id", "retry_attempt_id", "retry_count",
                   "retry_at", "error", "last_success"}
        if not fields or set(fields) - allowed:
            raise ValueError("无效调度状态字段")
        condition = "schedule_id=%s" + (" AND active_run_id=%s" if expected_run is not None else "")
        with self.connection() as store:
            _, count = store._execute("UPDATE processing_schedules SET " + ",".join(key + "=%s" for key in fields)
                + " WHERE " + condition, (*fields.values(), schedule_id, *((expected_run,) if expected_run is not None else ())))
        return count

    def enqueue(self, schedule, request, now):
        """任务插入与 active_run_id 同事务：崩溃只可能两者皆有或两者皆无。"""
        run_id = str(uuid4())
        with self.connection() as store:
            rows, _ = store._execute("SELECT GET_LOCK(%s,1) AS ok", (self.submit_lock,))
            if not rows or rows[0]["ok"] != 1:
                return None
            try:
                with store.transaction("scheduler-queue"):
                    rows, _ = store._execute("SELECT * FROM processing_schedules WHERE schedule_id=%s FOR UPDATE",
                                             (schedule["schedule_id"],))
                    current = self.row(rows[0]) if rows else None
                    if (not current or not current["enabled"] or current["status"] != "active"
                            or current["active_run_id"] or current["next_start"] != schedule["next_start"]):
                        return None
                    try:
                        self.insert_queued(store, request, 1, run_id, now.replace(tzinfo=None))
                    except RunConflict:
                        return None
                    store._execute("UPDATE processing_schedules SET active_run_id=%s,last_turn=%s WHERE schedule_id=%s",
                                   (run_id, now.replace(tzinfo=None), current["schedule_id"]))
            finally:
                store._execute("SELECT RELEASE_LOCK(%s)", (self.submit_lock,))
        return run_id

    def attempt(self, schedule, run):
        """失败恢复必须找到原任务窗口的真实执行，不按相同时间猜重试关系。"""
        with self.connection() as store:
            rows, _ = store._execute("SELECT attempt_id,outcome,receipt,error_type FROM processing_attempts "
                "WHERE uid=%s AND stream=%s AND run_id=%s AND window_index=0 "
                "ORDER BY created_at DESC,attempt_id DESC LIMIT 1", (schedule["uid"], schedule["stream"], run["run_id"]))
            unresolved, _ = store._execute("SELECT attempt_id FROM processing_attempts WHERE uid=%s AND stream=%s "
                "AND outcome IN ('running','commit_unknown') LIMIT 1", (schedule["uid"], schedule["stream"]))
        item = dict(rows[0]) if rows else {}
        if unresolved:
            item.update(outcome="commit_unknown", attempt_id=unresolved[0]["attempt_id"])
        return item
