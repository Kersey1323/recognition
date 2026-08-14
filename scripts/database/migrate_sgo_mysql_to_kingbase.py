#!/usr/bin/env python3
"""将询码记录相关表从 SGO MySQL 迁移到本机 KingbaseES。"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
from typing import NamedTuple

import asyncmy
import psycopg2
from dotenv import load_dotenv
from psycopg2 import sql
from psycopg2.extras import execute_batch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env", override=False)


class ColumnSpec(NamedTuple):
    name: str
    kingbase_type: str
    primary_key: bool = False


class IndexSpec(NamedTuple):
    name: str
    columns: tuple[str, ...]
    unique: bool = False


def _quote_identifier(value: str) -> str:
    return f'"{value.replace(chr(34), chr(34) * 2)}"'


class TableSpec:
    def __init__(
        self,
        name: str,
        columns: tuple[ColumnSpec, ...],
        indexes: tuple[IndexSpec, ...] = (),
    ) -> None:
        self.name = name
        self.columns = columns
        self.indexes = indexes

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)

    def create_table_sql(self, schema: str) -> str:
        column_definitions = []
        for column in self.columns:
            suffix = " PRIMARY KEY" if column.primary_key else ""
            column_definitions.append(
                f"{_quote_identifier(column.name)} {column.kingbase_type}{suffix}"
            )
        return (
            f"CREATE TABLE IF NOT EXISTS {_quote_identifier(schema)}.{_quote_identifier(self.name)} "
            f"({', '.join(column_definitions)})"
        )

    def create_index_sql(self, schema: str, index: IndexSpec) -> str:
        unique = "UNIQUE " if index.unique else ""
        columns = ", ".join(_quote_identifier(column) for column in index.columns)
        return (
            f"CREATE {unique}INDEX IF NOT EXISTS {_quote_identifier(index.name)} "
            f"ON {_quote_identifier(schema)}.{_quote_identifier(self.name)} ({columns})"
        )

    def insert_sql(self, schema: str) -> str:
        columns = ", ".join(_quote_identifier(column) for column in self.column_names)
        placeholders = ", ".join("%s" for _ in self.columns)
        return (
            f"INSERT INTO {_quote_identifier(schema)}.{_quote_identifier(self.name)} "
            f"({columns}) VALUES ({placeholders})"
        )

    def source_select_sql(self) -> str:
        columns = ", ".join(f"`{column}`" for column in self.column_names)
        return f"SELECT {columns} FROM `{self.name}` ORDER BY `id`"


TABLE_SPECS = {
    "sgo_code_inquiry": TableSpec(
        "sgo_code_inquiry",
        columns=(
            ColumnSpec("id", "VARCHAR(64)", primary_key=True),
            ColumnSpec("inquiry_num", "VARCHAR(13)"),
            ColumnSpec("creater", "VARCHAR(20)"),
            ColumnSpec("creater_account", "VARCHAR(20)"),
            ColumnSpec("creater_org_id", "VARCHAR(64)"),
            ColumnSpec("creater_org_code", "VARCHAR(20)"),
            ColumnSpec("creater_org_name", "VARCHAR(50)"),
            ColumnSpec("item_name", "VARCHAR(200)"),
            ColumnSpec("train_no", "VARCHAR(100)"),
            ColumnSpec("vehicle", "VARCHAR(20)"),
            ColumnSpec("car_num", "VARCHAR(100)"),
            ColumnSpec("parts_model", "VARCHAR(255)"),
            ColumnSpec("subordinate_component", "VARCHAR(50)"),
            ColumnSpec("submission_date", "DATE"),
            ColumnSpec("supplier_code", "VARCHAR(10)"),
            ColumnSpec("supplier_name", "VARCHAR(50)"),
            ColumnSpec("nameplate_photos", "VARCHAR(4000)"),
            ColumnSpec("detailed_photos", "VARCHAR(4000)"),
            ColumnSpec("remark", "VARCHAR(2000)"),
            ColumnSpec("create_time", "TIMESTAMP"),
            ColumnSpec("current_status", "VARCHAR(20)"),
            ColumnSpec("start_inst_id", "VARCHAR(64)"),
            ColumnSpec("supplier_inquiry_num", "VARCHAR(64)"),
            ColumnSpec("tenant_id_", "VARCHAR(64)"),
            ColumnSpec("project_type", "VARCHAR(10)"),
            ColumnSpec("location", "VARCHAR(50)"),
            ColumnSpec("inst_supplier", "VARCHAR(50)"),
            ColumnSpec("create_org_principal", "VARCHAR(20)"),
            ColumnSpec("create_org_principal_name", "VARCHAR(5)"),
            ColumnSpec("green_remark", "VARCHAR(2000)"),
            ColumnSpec("sub_current_status", "VARCHAR(20)"),
            ColumnSpec("admin_remark", "VARCHAR(2000)"),
            # MySQL 中是计算列；迁移后保存源库已经计算出的实际值。
            ColumnSpec("sub_creater_org_code", "VARCHAR(4)"),
        ),
        indexes=(
            IndexSpec("uq_sgo_code_inquiry_inquiry_num", ("inquiry_num",), unique=True),
            IndexSpec("idx_sgo_code_inquiry_status_time", ("current_status", "create_time")),
        ),
    ),
    "sgo_code_inquiry_return": TableSpec(
        "sgo_code_inquiry_return",
        columns=(
            ColumnSpec("id", "VARCHAR(64)", primary_key=True),
            ColumnSpec("inquiry_id", "VARCHAR(64)"),
            ColumnSpec("creater", "VARCHAR(20)"),
            ColumnSpec("creater_account", "VARCHAR(20)"),
            ColumnSpec("creater_org_id", "VARCHAR(64)"),
            ColumnSpec("creater_org_code", "VARCHAR(20)"),
            ColumnSpec("creater_org_name", "VARCHAR(50)"),
            ColumnSpec("item_name", "VARCHAR(255)"),
            ColumnSpec("item_code", "VARCHAR(50)"),
            ColumnSpec("vehicle", "VARCHAR(255)"),
            ColumnSpec("figure_number", "VARCHAR(200)"),
            ColumnSpec("parts_model", "VARCHAR(200)"),
            ColumnSpec("item_unit", "VARCHAR(50)"),
            ColumnSpec("subordinate_component", "VARCHAR(50)"),
            ColumnSpec("supplier_code", "VARCHAR(10)"),
            ColumnSpec("supplier_name", "VARCHAR(50)"),
            ColumnSpec("technical_notice", "VARCHAR(200)"),
            ColumnSpec("technical_brief", "VARCHAR(200)"),
            ColumnSpec("inquiry_from", "VARCHAR(50)"),
            ColumnSpec("technical_annex", "VARCHAR(2000)"),
            ColumnSpec("update_time", "TIMESTAMP"),
            ColumnSpec("create_time", "TIMESTAMP"),
            ColumnSpec("tenant_id_", "VARCHAR(50)"),
            ColumnSpec("material_quality", "VARCHAR(50)"),
            ColumnSpec("strength_level", "VARCHAR(50)"),
            ColumnSpec("remark", "VARCHAR(1000)"),
            ColumnSpec("tec_introduce", "VARCHAR(1000)"),
            ColumnSpec("current_status", "VARCHAR(30)"),
        ),
        indexes=(
            IndexSpec("idx_sgo_code_inquiry_return_inquiry_id", ("inquiry_id",)),
            IndexSpec("idx_sgo_code_inquiry_return_item_code", ("item_code",)),
        ),
    ),
}


class MigrationConfig(NamedTuple):
    source_host: str
    source_port: int
    source_user: str
    source_password: str
    source_database: str
    target_host: str
    target_port: int
    target_user: str
    target_password: str
    target_database: str
    target_schema: str
    target_admin_database: str


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"缺少环境变量: {name}")
    return value


def load_config() -> MigrationConfig:
    return MigrationConfig(
        source_host=_required_env("SGO_MYSQL_HOST"),
        source_port=int(os.getenv("SGO_MYSQL_PORT", "3306")),
        source_user=_required_env("SGO_MYSQL_USER"),
        source_password=_required_env("SGO_MYSQL_PASSWORD"),
        source_database=os.getenv("SGO_MYSQL_DATABASE", "mdpdb").strip() or "mdpdb",
        target_host=os.getenv("KINGBASE_HOST", "127.0.0.1").strip() or "127.0.0.1",
        target_port=int(os.getenv("KINGBASE_PORT", "54321")),
        target_user=os.getenv("KINGBASE_USER", "system").strip() or "system",
        target_password=_required_env("KINGBASE_PASSWORD"),
        target_database=os.getenv("KINGBASE_DATABASE", "mdpdb").strip() or "mdpdb",
        target_schema=os.getenv("KINGBASE_SCHEMA", "public").strip() or "public",
        target_admin_database=os.getenv("KINGBASE_ADMIN_DATABASE", "test").strip() or "test",
    )


def _connect_kingbase(config: MigrationConfig, *, database: str | None = None):
    return psycopg2.connect(
        host=config.target_host,
        port=config.target_port,
        user=config.target_user,
        password=config.target_password,
        dbname=database or config.target_database,
        connect_timeout=10,
    )


def ensure_target_database(config: MigrationConfig) -> None:
    connection = _connect_kingbase(config, database=config.target_admin_database)
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (config.target_database,))
            if cursor.fetchone() is None:
                cursor.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(config.target_database))
                )
                print(f"已创建 Kingbase 数据库: {config.target_database}")
    finally:
        connection.close()


def ensure_target_schema(connection, schema: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema))
        )
        for table in TABLE_SPECS.values():
            cursor.execute(table.create_table_sql(schema))
            for index in table.indexes:
                cursor.execute(table.create_index_sql(schema, index))
    connection.commit()


def target_count(connection, schema: str, table_name: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
                sql.Identifier(schema),
                sql.Identifier(table_name),
            )
        )
        return int(cursor.fetchone()[0])


def prepare_target_tables(connection, schema: str, *, replace: bool) -> None:
    counts = {
        table_name: target_count(connection, schema, table_name)
        for table_name in TABLE_SPECS
    }
    non_empty = {name: count for name, count in counts.items() if count > 0}
    if non_empty and not replace:
        details = ", ".join(f"{name}={count}" for name, count in non_empty.items())
        raise RuntimeError(
            f"Kingbase 目标表已有数据: {details}；确认覆盖时请显式添加 --replace"
        )
    if not non_empty:
        return

    with connection.cursor() as cursor:
        for table_name in reversed(TABLE_SPECS):
            cursor.execute(
                sql.SQL("TRUNCATE TABLE {}.{}").format(
                    sql.Identifier(schema),
                    sql.Identifier(table_name),
                )
            )
    connection.commit()


async def _connect_mysql(config: MigrationConfig):
    return await asyncmy.connect(
        host=config.source_host,
        port=config.source_port,
        user=config.source_user,
        password=config.source_password,
        database=config.source_database,
        charset="utf8mb4",
        cursor_cls=asyncmy.cursors.SSDictCursor,
        autocommit=True,
        connect_timeout=10,
    )


async def source_count(connection, table_name: str) -> int:
    cursor = connection.cursor(asyncmy.cursors.DictCursor)
    try:
        await cursor.execute(f"SELECT COUNT(*) AS `total` FROM `{table_name}`")
        row = await cursor.fetchone()
        return int(row["total"])
    finally:
        await cursor.close()


def _source_row_values(row, column_names: tuple[str, ...]) -> tuple:
    if isinstance(row, dict):
        return tuple(row.get(column_name) for column_name in column_names)

    values = tuple(row)
    if len(values) != len(column_names):
        raise RuntimeError(
            f"源数据列数不匹配: expected={len(column_names)}, actual={len(values)}"
        )
    return values


async def migrate_table(
    source_connection,
    target_connection,
    table: TableSpec,
    schema: str,
    *,
    batch_size: int,
) -> int:
    cursor = source_connection.cursor(asyncmy.cursors.SSDictCursor)
    migrated = 0
    try:
        await cursor.execute(table.source_select_sql())
        while True:
            rows = await cursor.fetchmany(batch_size)
            if not rows:
                break
            # asyncmy 的流式 SSDictCursor 返回元组；列顺序由 source_select_sql 固定。
            payload = [
                _source_row_values(row, table.column_names)
                for row in rows
            ]
            with target_connection.cursor() as target_cursor:
                execute_batch(
                    target_cursor,
                    table.insert_sql(schema),
                    payload,
                    page_size=batch_size,
                )
            target_connection.commit()
            migrated += len(payload)
            print(f"{table.name}: 已迁移 {migrated} 行")
    except Exception:
        target_connection.rollback()
        raise
    finally:
        await cursor.close()
    return migrated


async def run_migration(args) -> None:
    config = load_config()
    if args.create_database:
        ensure_target_database(config)

    target_connection = _connect_kingbase(config)
    source_connection = None
    try:
        ensure_target_schema(target_connection, config.target_schema)
        if args.create_only:
            print("Kingbase 表结构创建完成")
            return

        source_connection = await _connect_mysql(config)
        if not args.verify_only:
            prepare_target_tables(
                target_connection,
                config.target_schema,
                replace=args.replace,
            )
            for table in TABLE_SPECS.values():
                await migrate_table(
                    source_connection,
                    target_connection,
                    table,
                    config.target_schema,
                    batch_size=args.batch_size,
                )

        mismatches = []
        for table_name in TABLE_SPECS:
            source_rows = await source_count(source_connection, table_name)
            target_rows = target_count(target_connection, config.target_schema, table_name)
            status = "一致" if source_rows == target_rows else "不一致"
            print(
                f"校验 {table_name}: MySQL={source_rows}, "
                f"Kingbase={target_rows}, status={status}"
            )
            if source_rows != target_rows:
                mismatches.append(table_name)

        if mismatches:
            raise RuntimeError(f"迁移行数校验失败: {', '.join(mismatches)}")
        print("询码记录表迁移及行数校验完成")
    finally:
        if source_connection is not None:
            await source_connection.ensure_closed()
        target_connection.close()


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=500, help="每批迁移行数")
    parser.add_argument(
        "--create-database",
        action="store_true",
        help="通过 KINGBASE_ADMIN_DATABASE 连接并创建 KINGBASE_DATABASE",
    )
    parser.add_argument("--create-only", action="store_true", help="只创建表结构")
    parser.add_argument("--verify-only", action="store_true", help="只比较源端和目标端行数")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="清空 Kingbase 目标表后重新迁移；默认拒绝覆盖已有数据",
    )
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error("--batch-size 必须大于 0")
    if args.create_only and args.verify_only:
        parser.error("--create-only 和 --verify-only 不能同时使用")
    return args


def main() -> None:
    asyncio.run(run_migration(parse_args()))


if __name__ == "__main__":
    main()
