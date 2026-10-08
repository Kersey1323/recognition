"""Atomically replace five local SGO Kingbase tables from timestamped CSV exports."""

from __future__ import annotations

import argparse
import csv
import re
from datetime import datetime
from pathlib import Path

import psycopg2
from dotenv import dotenv_values
from psycopg2 import sql


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TABLE_NAMES = (
    "sgo_materiel_info",
    "sgo_materiel_info_tree",
    "sgo_materiel_masterplate",
    "sgo_materiel_supplier",
    "sgo_materiel_vehicle",
)
FILE_PATTERN = re.compile(
    r"(?P<table>sgo_materiel_(?:info_tree|info|masterplate|supplier|vehicle))_"
    r"\d{12}\.csv"
)


def inspect_exports(paths: list[Path]) -> dict[str, tuple[Path, list[str], int]]:
    exports = {}
    for path in paths:
        match = FILE_PATTERN.fullmatch(path.name)
        if match is None or not path.is_file():
            raise ValueError(f"不是预期的 SGO CSV 导出文件: {path}")
        table = match.group("table")
        if table in exports:
            raise ValueError(f"重复提供了 {table} 的导出文件")
        with path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.reader(source, strict=True)
            columns = next(reader)
            if not columns or columns[0] != "id" or len(columns) != len(set(columns)):
                raise ValueError(f"{path.name} 的表头无效")
            row_count = 0
            seen_ids = set()
            for row in reader:
                row_count += 1
                if len(row) != len(columns) or not row[0] or row[0] in seen_ids:
                    raise ValueError(f"{path.name} 第 {row_count + 1} 行字段数或 ID 无效")
                seen_ids.add(row[0])
            if row_count == 0:
                raise ValueError(f"{path.name} 没有数据行")
        exports[table] = path, columns, row_count
    if set(exports) != set(TABLE_NAMES):
        raise ValueError(f"必须提供五张表，当前缺少: {sorted(set(TABLE_NAMES) - set(exports))}")
    return exports


def table_columns(cursor, table: str) -> list[str]:
    cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s "
        "ORDER BY ordinal_position",
        (table,),
    )
    return [row[0] for row in cursor.fetchall()]


def count_rows(cursor, table: str) -> int:
    cursor.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table)))
    return cursor.fetchone()[0]


def replace(exports: dict[str, tuple[Path, list[str], int]]) -> dict[str, tuple[int, int, str]]:
    config = dotenv_values(PROJECT_ROOT / ".env")
    host = config.get("SGO_KINGBASE_HOST")
    if config.get("SGO_DATABASE_TYPE") != "kingbase" or host not in {
        "127.0.0.1", "localhost", "::1"
    }:
        raise ValueError("只允许替换本机 Kingbase 副本")

    connection = psycopg2.connect(
        host=host,
        port=int(config["SGO_KINGBASE_PORT"]),
        user=config["SGO_KINGBASE_USER"],
        password=config["SGO_KINGBASE_PASSWORD"],
        dbname=config["SGO_KINGBASE_DATABASE"],
        connect_timeout=10,
    )
    backup_suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
    results = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_schema()")
            if cursor.fetchone()[0] != "public":
                raise ValueError("当前 Kingbase schema 不是 public")

            # Stage every export before touching the live source tables.
            for table in TABLE_NAMES:
                path, columns, expected = exports[table]
                existing = table_columns(cursor, table)
                if not existing or set(existing) - set(columns):
                    raise ValueError(f"{table} 的原表列不在 CSV 中")
                extra = [column for column in columns if column not in existing]
                if extra and table != "sgo_materiel_masterplate":
                    raise ValueError(f"{table} 出现未预期的新列: {extra}")
                stage = f"stage_{table}"
                cursor.execute(
                    sql.SQL("CREATE TEMP TABLE {} (LIKE {} INCLUDING DEFAULTS INCLUDING CONSTRAINTS)")
                    .format(sql.Identifier(stage), sql.Identifier(table))
                )
                for column in extra:
                    cursor.execute(
                        sql.SQL("ALTER TABLE {} ADD COLUMN {} TEXT").format(
                            sql.Identifier(stage), sql.Identifier(column)
                        )
                    )
                with path.open(encoding="utf-8-sig", newline="") as source:
                    cursor.copy_expert(
                        sql.SQL(
                            "COPY {} ({}) FROM STDIN WITH (FORMAT CSV, HEADER TRUE, NULL '')"
                        ).format(
                            sql.Identifier(stage),
                            sql.SQL(", ").join(map(sql.Identifier, columns)),
                        ).as_string(connection),
                        source,
                    )
                actual = count_rows(cursor, stage)
                if actual != expected:
                    raise ValueError(f"{table} 临时表行数 {actual} != CSV {expected}")
                print(f"staged {table}: {actual} rows, {len(extra)} new columns", flush=True)

            # Backups retain the old table structure and data even when the new
            # masterplate export adds columns to the active table.
            for table in TABLE_NAMES:
                backup = f"{table}_bak_{backup_suffix}"
                if len(backup) > 63:
                    raise ValueError(f"备份表名过长: {backup}")
                before = count_rows(cursor, table)
                cursor.execute(
                    sql.SQL("CREATE TABLE {} (LIKE {} INCLUDING ALL)").format(
                        sql.Identifier(backup), sql.Identifier(table)
                    )
                )
                cursor.execute(
                    sql.SQL("INSERT INTO {} SELECT * FROM {}").format(
                        sql.Identifier(backup), sql.Identifier(table)
                    )
                )
                if count_rows(cursor, backup) != before:
                    raise ValueError(f"{table} 备份行数不一致")
                results[table] = before, exports[table][2], backup
                print(f"backed up {table}: {before} rows -> {backup}", flush=True)

            masterplate = "sgo_materiel_masterplate"
            for column in exports[masterplate][1]:
                if column not in table_columns(cursor, masterplate):
                    cursor.execute(
                        sql.SQL("ALTER TABLE {} ADD COLUMN {} TEXT").format(
                            sql.Identifier(masterplate), sql.Identifier(column)
                        )
                    )

            cursor.execute(
                sql.SQL("TRUNCATE TABLE {}").format(
                    sql.SQL(", ").join(map(sql.Identifier, TABLE_NAMES))
                )
            )
            for table in TABLE_NAMES:
                columns = exports[table][1]
                column_list = sql.SQL(", ").join(map(sql.Identifier, columns))
                cursor.execute(
                    sql.SQL("INSERT INTO {} ({}) SELECT {} FROM {}").format(
                        sql.Identifier(table), column_list, column_list,
                        sql.Identifier(f"stage_{table}"),
                    )
                )
                if count_rows(cursor, table) != exports[table][2]:
                    raise ValueError(f"{table} 正式表行数与 CSV 不一致")
                cursor.execute(sql.SQL("ANALYZE {}").format(sql.Identifier(table)))
                print(f"replaced {table}: {exports[table][2]} rows", flush=True)

        connection.commit()
        return results
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_files", type=Path, nargs="+")
    args = parser.parse_args()
    exports = inspect_exports(args.csv_files)
    for table in TABLE_NAMES:
        print(f"validated {table}: {exports[table][2]} CSV rows", flush=True)
    results = replace(exports)
    for table, (before, after, backup) in results.items():
        print(f"committed {table}: {before} -> {after}, backup={backup}")


if __name__ == "__main__":
    main()
