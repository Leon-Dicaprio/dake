"""导出或导入本地 MySQL 完整快照（UTF-8 标准 SQL，兼容 mysql 客户端与跨平台无损导入）。

用法示例：
  导出：python scripts/db_snapshot.py export data/exports/dake_aftersales_20261118.sql
  导入：python scripts/db_snapshot.py import data/exports/dake_aftersales_20261118.sql
"""

from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal
import gzip
from pathlib import Path
import sys

import pymysql

from dake.config import PROJECT_ROOT, Settings

STATEMENT_END = ";\n"
BATCH_SIZE = 25


def _connect(settings: Settings):
    if settings.mysql_host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("仅允许连接本机 MySQL，拒绝远程数据库操作。")
    return pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_database,
        charset="utf8mb4",
        autocommit=False,
        connect_timeout=10,
        read_timeout=120,
        write_timeout=120,
    )


def _sql_literal(conn, value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, (bytes, bytearray)):
        return "0x" + bytes(value).hex() if value else "''"
    if isinstance(value, datetime):
        return conn.escape(value.strftime("%Y-%m-%d %H:%M:%S.%f").rstrip("0").rstrip("."))
    if isinstance(value, Decimal):
        return str(value)
    return conn.escape(value)


def _open_text(path: Path, mode: str):
    if path.suffix.lower() == ".gz":
        return gzip.open(path, mode + "t", encoding="utf-8", newline="\n" if "w" in mode else None)
    return path.open(mode, encoding="utf-8", newline="\n" if "w" in mode else None)


def export_sql(output_path: Path) -> None:
    """将当前本机库完整表结构与数据导出为 UTF-8 SQL（或 .sql.gz）文件（默认写入已忽略的 data/exports/）。"""
    settings = Settings.load()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(settings)
    try:
        with conn.cursor() as cur, _open_text(output_path, "w") as out:
            out.write("-- dake-aftersales MySQL UTF-8 Snapshot\n")
            out.write("SET NAMES utf8mb4" + STATEMENT_END)
            out.write("SET TIME_ZONE = '+00:00'" + STATEMENT_END)
            out.write("SET FOREIGN_KEY_CHECKS = 0" + STATEMENT_END)
            out.write("SET UNIQUE_CHECKS = 0" + STATEMENT_END)

            cur.execute("SHOW FULL TABLES WHERE Table_type = 'BASE TABLE'")
            tables = [row[0] for row in cur.fetchall()]

            for table in tables:
                out.write(f"\n-- Table structure for `{table}`\n")
                out.write(f"DROP TABLE IF EXISTS `{table}`" + STATEMENT_END)
                cur.execute(f"SHOW CREATE TABLE `{table}`")
                create_sql = cur.fetchone()[1]
                out.write(create_sql + STATEMENT_END)

                cur.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = DATABASE() AND table_name = %s AND extra NOT LIKE '%%GENERATED%%' "
                    "ORDER BY ordinal_position",
                    (table,),
                )
                col_names = [row[0] for row in cur.fetchall()]
                if not col_names:
                    continue
                cols_sql = ", ".join(f"`{col}`" for col in col_names)
                cur.execute(f"SELECT {cols_sql} FROM `{table}`")

                while True:
                    rows = cur.fetchmany(BATCH_SIZE)
                    if not rows:
                        break
                    values_chunks = []
                    for row in rows:
                        row_list = list(row)
                        # 导出时清空本机瞬时槽位租约 owner，避免队友导入后等待租约过期。
                        if table == "runtime_limits":
                            for idx, cname in enumerate(col_names):
                                if cname in {"owner", "lease_until"}:
                                    row_list[idx] = None
                        literals = ", ".join(_sql_literal(conn, val) for val in row_list)
                        values_chunks.append(f"({literals})")
                    out.write(
                        f"INSERT INTO `{table}` ({cols_sql}) VALUES\n  "
                        + ",\n  ".join(values_chunks)
                        + STATEMENT_END
                    )

            out.write("\nSET UNIQUE_CHECKS = 1" + STATEMENT_END)
            out.write("SET FOREIGN_KEY_CHECKS = 1" + STATEMENT_END)
    finally:
        conn.close()


def import_sql(input_path: Path) -> None:
    """按 UTF-8 流式读取由本脚本或 mysqldump 导出的 SQL 文件并导入当前本机 MySQL。"""
    if not input_path.is_file():
        raise SystemExit(f"找不到 SQL 文件：{input_path}")
    settings = Settings.load()
    conn = _connect(settings)
    executed = 0
    try:
        with conn.cursor() as cur, _open_text(input_path, "r") as src:
            buf: list[str] = []
            for line in src:
                stripped = line.strip()
                if not buf and (not stripped or stripped.startswith("--") or stripped.startswith("/*!")):
                    if stripped.startswith("/*!") and stripped.endswith("*/;"):
                        cur.execute(stripped[:-1])
                        executed += 1
                    continue
                buf.append(line)
                if stripped.endswith(";") and not _in_single_quote("".join(buf)):
                    stmt = "".join(buf).strip()
                    buf.clear()
                    if stmt.endswith(";"):
                        stmt = stmt[:-1].strip()
                    if stmt:
                        cur.execute(stmt)
                        executed += 1
            if buf:
                tail = "".join(buf).strip().rstrip(";").strip()
                if tail:
                    cur.execute(tail)
                    executed += 1
        conn.commit()
        print(f"导入完成：共执行 {executed} 条 SQL 语句 -> 数据库 {settings.mysql_database}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _in_single_quote(sql: str) -> bool:
    """判断当前多行缓冲区末尾是否仍处于未闭合的单引号字符串字面量中。"""
    in_quote = False
    escaped = False
    for ch in sql:
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == "'":
            in_quote = not in_quote
    return in_quote


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="导出或导入本地 MySQL 快照（真实数据仅存放在已忽略的 data/ 下）")
    sub = parser.add_subparsers(dest="command", required=True)

    p_exp = sub.add_parser("export", help="导出当前本机库到 UTF-8 .sql 文件")
    p_exp.add_argument(
        "path",
        nargs="?",
        default=str(PROJECT_ROOT / "data" / "exports" / "dake_aftersales_snapshot.sql"),
        help="输出 SQL 路径（默认 data/exports/dake_aftersales_snapshot.sql）",
    )

    p_imp = sub.add_parser("import", help="将 UTF-8 .sql 文件导入当前本机库")
    p_imp.add_argument("path", help="待导入的 SQL 文件路径")

    args = parser.parse_args(argv)
    target = Path(args.path).expanduser().resolve()
    if args.command == "export":
        export_sql(target)
        size_mb = target.stat().st_size / (1024 * 1024)
        print(f"导出完成：{target} ({size_mb:.2f} MB)")
    else:
        import_sql(target)


if __name__ == "__main__":
    main(sys.argv[1:])
