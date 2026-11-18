"""显式初始化迁移后的空库，不删除数据，不调用取数或模型。"""

from contextlib import closing

from dake.config import PROJECT_ROOT, Settings
from dake.repositories.mysql import MySQLStore
from dake.repositories.pipeline import apply_statements
from dake.repositories.runs import RunRepository
from dake.repositories.tasks import TaskRepository


def main():
    settings = Settings.load()
    with closing(MySQLStore(**settings.store_kwargs())) as store:
        rows, _ = store._execute("SELECT COUNT(*) AS n FROM information_schema.tables WHERE table_schema=DATABASE()")
        if rows[0]["n"]:
            raise SystemExit("数据库已包含表，停止初始化；请先核实目标库，不会清空已有数据。")
        store.init_schema()
        for name in ("001_processing_attempts.sql", "002_event_link_hints.sql", "003_customer_directory.sql",
                     "006_event_group_links.sql"):
            apply_statements(store, PROJECT_ROOT / "backend/migrations" / name)
    RunRepository(settings).init_schema()
    TaskRepository(settings).init_schema()
    print("空库初始化完成，尚未创建任务或调用外部接口。")


if __name__ == "__main__":
    main()
