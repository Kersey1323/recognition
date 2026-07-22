#!/usr/bin/env python3
"""
一次性主业务库迁移脚本：PostgreSQL -> MySQL。

用途：
- 从旧 PostgreSQL 主业务库读取核心表
- 写入新的 MySQL coronavirusdb
- 适用于向空 MySQL 库做一次性迁移
"""

from __future__ import annotations

import os
from collections import OrderedDict
from urllib.parse import quote_plus

from sqlalchemy import MetaData, Table, create_engine, func, select, text


SOURCE_POSTGRES_HOST = os.getenv("SOURCE_POSTGRES_HOST", "127.0.0.1")
SOURCE_POSTGRES_PORT = os.getenv("SOURCE_POSTGRES_PORT", "5432")
SOURCE_POSTGRES_USER = os.getenv("SOURCE_POSTGRES_USER", "root")
SOURCE_POSTGRES_PASSWORD = os.getenv("SOURCE_POSTGRES_PASSWORD", "change_me")
SOURCE_POSTGRES_DATABASE = os.getenv("SOURCE_POSTGRES_DATABASE", "zcsf")

TARGET_MYSQL_HOST = os.getenv("TARGET_MYSQL_HOST", os.getenv("MAIN_DB_HOST", "127.0.0.1"))
TARGET_MYSQL_PORT = os.getenv("TARGET_MYSQL_PORT", os.getenv("MAIN_DB_PORT", "3306"))
TARGET_MYSQL_USER = os.getenv("TARGET_MYSQL_USER", os.getenv("MAIN_DB_USER", "root"))
TARGET_MYSQL_PASSWORD = os.getenv(
    "TARGET_MYSQL_PASSWORD",
    os.getenv("MAIN_DB_PASSWORD", "change_me"),
)
TARGET_MYSQL_DATABASE = os.getenv(
    "TARGET_MYSQL_DATABASE",
    os.getenv("MAIN_DB_DATABASE", "coronavirusdb"),
)

POSTGRES_SOURCE_DSN = (
    f"postgresql+psycopg2://{SOURCE_POSTGRES_USER}:{quote_plus(SOURCE_POSTGRES_PASSWORD)}"
    f"@{SOURCE_POSTGRES_HOST}:{SOURCE_POSTGRES_PORT}/{SOURCE_POSTGRES_DATABASE}"
)
MYSQL_TARGET_DSN = (
    f"mysql+pymysql://{TARGET_MYSQL_USER}:{quote_plus(TARGET_MYSQL_PASSWORD)}"
    f"@{TARGET_MYSQL_HOST}:{TARGET_MYSQL_PORT}/{TARGET_MYSQL_DATABASE}"
)

CORE_TABLES = OrderedDict(
    [
        ("item_info", "item_info"),
        ("item_relation", "item_relation"),
        ("zcsf_parts_files", "zcsf_parts_files"),
        ("zcsf_parts_tables", "zcsf_parts_tables"),
        ("sgo_item_image_info", "sgo_item_image_info"),
        ("segmented_image_info", "segmented_image_info"),
        ("search_history", "search_history"),
        ("search_review_ticket", "search_review_ticket"),
        ("reconstruction_records", "reconstruction_records"),
    ]
)


def _reflect_source_table(metadata: MetaData, engine, table_name: str) -> Table:
    return Table(table_name, metadata, schema="parts", autoload_with=engine)


def _reflect_target_table(metadata: MetaData, engine, table_name: str) -> Table:
    return Table(table_name, metadata, autoload_with=engine)


def _assert_target_table_empty(engine, table: Table) -> None:
    with engine.begin() as conn:
        count = conn.execute(select(func.count()).select_from(table)).scalar_one()
    if count != 0:
        raise RuntimeError(
            f"target table `{table.name}` is not empty; rerun only against empty coronavirusdb"
        )


def _normalize_row(row: dict) -> dict:
    normalized = {}
    for key, value in row.items():
        if hasattr(value, "dict"):
            normalized[key] = value.dict()
        elif hasattr(value, "model_dump"):
            normalized[key] = value.model_dump(mode="json")
        else:
            normalized[key] = value
    return normalized


def _normalize_row_for_table(table_name: str, row: dict) -> dict:
    normalized = _normalize_row(row)
    if table_name == "item_info":
        normalized["item_type"] = normalized.get("item_type") or "real"
        normalized["parent_num"] = normalized.get("parent_num") or 0
        normalized["son_num"] = normalized.get("son_num") or 0
        normalized["image_index_num"] = normalized.get("image_index_num") or 0
        normalized["feature_index_num"] = normalized.get("feature_index_num") or 0
    return normalized


def migrate_table(source_engine, target_engine, table_name: str) -> int:
    source_metadata = MetaData()
    target_metadata = MetaData()
    source_table = _reflect_source_table(source_metadata, source_engine, table_name)
    target_table = _reflect_target_table(target_metadata, target_engine, table_name)

    _assert_target_table_empty(target_engine, target_table)

    with source_engine.connect() as source_conn:
        rows = source_conn.execute(select(source_table)).mappings().all()

    if not rows:
        return 0

    payload = []
    target_columns = set(target_table.columns.keys())
    for row in rows:
        normalized = _normalize_row_for_table(table_name, dict(row))
        payload.append({key: value for key, value in normalized.items() if key in target_columns})

    with target_engine.begin() as target_conn:
        target_conn.execute(target_table.insert(), payload)

    return len(payload)


def main() -> None:
    source_engine = create_engine(POSTGRES_SOURCE_DSN, pool_pre_ping=True)
    target_engine = create_engine(MYSQL_TARGET_DSN, pool_pre_ping=True)

    migrated_counts: list[tuple[str, int]] = []
    try:
        with target_engine.begin() as conn:
            conn.execute(text("SELECT 1"))

        for table_name in CORE_TABLES.values():
            count = migrate_table(source_engine, target_engine, table_name)
            migrated_counts.append((table_name, count))
            print(f"{table_name}: migrated {count} rows")
    finally:
        source_engine.dispose()
        target_engine.dispose()

    print("migration finished")
    for table_name, count in migrated_counts:
        print(f"{table_name}={count}")


if __name__ == "__main__":
    main()
