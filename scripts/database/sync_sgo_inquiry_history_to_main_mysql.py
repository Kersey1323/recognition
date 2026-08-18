#!/usr/bin/env python3
"""将 SGO 询码结果同步到主业务 MySQL 的 item_inquiry_history。"""

from __future__ import annotations

import argparse
import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import asyncmy
import psycopg2
from bfrcommon.db import get_id
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env", override=False)

HISTORY_COLUMNS = (
    "item_id",
    "item_code",
    "inquiry_id",
    "inquiry_num",
    "vehicle_batch",
    "vehicle",
    "train_no",
    "car_num",
    "inquiry_item_name",
    "subordinate_component",
    "remark",
    "return_item_name",
    "return_item_code",
    "inquiry_time",
    "source",
)
INSERT_COLUMNS = (
    "id",
    "created_by",
    "updated_by",
    "time_created",
    "time_updated",
) + HISTORY_COLUMNS


def _clean_text(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    value = value.strip()
    return value or None


def normalize_vehicle_batch(vehicle: str | None) -> str | None:
    vehicle = _clean_text(vehicle)
    if vehicle is None:
        return None
    return vehicle.split("_", 1)[0].strip() or None


def history_payload_from_source_row(row: dict[str, Any], *, item_id: int | None) -> dict[str, Any]:
    return_item_code = _clean_text(row.get("return_item_code"))
    vehicle = _clean_text(row.get("vehicle"))
    inquiry_item_name = _clean_text(row.get("inquiry_item_name"))

    return {
        "item_id": item_id,
        "item_code": return_item_code,
        "inquiry_id": _clean_text(row.get("inquiry_id")),
        "inquiry_num": _clean_text(row.get("inquiry_num")),
        "vehicle_batch": normalize_vehicle_batch(vehicle),
        "vehicle": vehicle,
        "train_no": _clean_text(row.get("train_no")),
        "car_num": _clean_text(row.get("car_num")),
        "inquiry_item_name": inquiry_item_name,
        "subordinate_component": _clean_text(row.get("subordinate_component")),
        "remark": _clean_text(row.get("remark")),
        "return_item_name": _clean_text(row.get("return_item_name")),
        "return_item_code": return_item_code,
        "inquiry_time": row.get("inquiry_time"),
        "source": "sgo",
    }


def build_history_upsert_sql() -> str:
    columns = ", ".join(f"`{column}`" for column in INSERT_COLUMNS)
    placeholders = ", ".join("%s" for _ in INSERT_COLUMNS)
    updates = ", ".join(
        f"`{column}` = new.`{column}`"
        for column in INSERT_COLUMNS
        if column
        not in {
            "id",
            "time_created",
            "time_updated",
            "inquiry_id",
            "return_item_code",
            "source",
        }
    )
    return (
        f"INSERT INTO `item_inquiry_history` ({columns}) VALUES ({placeholders}) AS new "
        f"ON DUPLICATE KEY UPDATE {updates}, `time_updated` = CURRENT_TIMESTAMP"
    )


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"缺少环境变量: {name}")
    return value


def _chunks(values: list[Any], size: int) -> Iterable[list[Any]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _connect_kingbase():
    return psycopg2.connect(
        host=os.getenv("SGO_KINGBASE_HOST", "127.0.0.1"),
        port=int(os.getenv("SGO_KINGBASE_PORT", "54321")),
        user=os.getenv("SGO_KINGBASE_USER", "system"),
        password=_required_env("SGO_KINGBASE_PASSWORD"),
        dbname=os.getenv("SGO_KINGBASE_DATABASE", "mdpdb"),
        connect_timeout=10,
    )


async def _connect_main_mysql():
    return await asyncmy.connect(
        host=_required_env("MAIN_DB_HOST"),
        port=int(os.getenv("MAIN_DB_PORT", "3306")),
        user=_required_env("MAIN_DB_USER"),
        password=_required_env("MAIN_DB_PASSWORD"),
        database=os.getenv("MAIN_DB_DATABASE", "coronavirusdb").strip() or "coronavirusdb",
        charset="utf8mb4",
        autocommit=False,
    )


def fetch_source_rows(*, limit: int | None = None) -> list[dict[str, Any]]:
    sql = """
        SELECT
            q."id" AS inquiry_id,
            q."inquiry_num" AS inquiry_num,
            q."vehicle" AS vehicle,
            q."train_no" AS train_no,
            q."car_num" AS car_num,
            q."item_name" AS inquiry_item_name,
            q."subordinate_component" AS subordinate_component,
            q."remark" AS remark,
            r."item_name" AS return_item_name,
            r."item_code" AS return_item_code,
            COALESCE(q."create_time", q."submission_date"::timestamp) AS inquiry_time
        FROM public."sgo_code_inquiry" q
        JOIN public."sgo_code_inquiry_return" r ON r."inquiry_id" = q."id"
        WHERE NULLIF(TRIM(r."item_code"), '') IS NOT NULL
        ORDER BY q."create_time" NULLS LAST, q."id", r."item_code"
    """
    if limit is not None:
        sql += " LIMIT %s"

    connection = _connect_kingbase()
    try:
        with connection.cursor() as cursor:
            if limit is None:
                cursor.execute(sql)
            else:
                cursor.execute(sql, (limit,))
            column_names = [desc[0] for desc in cursor.description]
            return [dict(zip(column_names, row)) for row in cursor.fetchall()]
    finally:
        connection.close()


async def fetch_item_id_map(connection, item_codes: set[str], *, batch_size: int) -> dict[str, int]:
    result: dict[str, int] = {}
    async with connection.cursor(asyncmy.cursors.DictCursor) as cursor:
        for batch in _chunks(sorted(item_codes), batch_size):
            placeholders = ", ".join("%s" for _ in batch)
            await cursor.execute(
                f"SELECT `id`, `item_code` FROM `item_info` WHERE `item_code` IN ({placeholders})",
                tuple(batch),
            )
            for row in await cursor.fetchall():
                result[str(row["item_code"])] = int(row["id"])
    return result


async def upsert_history_rows(connection, payloads: list[dict[str, Any]], *, batch_size: int) -> int:
    if not payloads:
        return 0
    statement = build_history_upsert_sql()
    inserted = 0
    async with connection.cursor() as cursor:
        for batch in _chunks(payloads, batch_size):
            rows = []
            for payload in batch:
                now = datetime.now()
                insert_payload = {
                    "id": get_id(),
                    "created_by": 0,
                    "updated_by": 0,
                    "time_created": now,
                    "time_updated": now,
                    **payload,
                }
                rows.append(tuple(insert_payload[column] for column in INSERT_COLUMNS))
            # 一次询码可能返回多个编码，业务唯一键使用 inquiry_id + return_item_code + source。
            await cursor.executemany(statement, rows)
            inserted += len(rows)
    await connection.commit()
    return inserted


async def sync_inquiry_history(*, batch_size: int, limit: int | None = None) -> int:
    source_rows = fetch_source_rows(limit=limit)
    item_codes = {
        item_code
        for row in source_rows
        if (item_code := _clean_text(row.get("return_item_code"))) is not None
    }

    target_connection = await _connect_main_mysql()
    try:
        item_id_map = await fetch_item_id_map(
            target_connection,
            item_codes,
            batch_size=batch_size,
        )
        payloads = [
            history_payload_from_source_row(
                row,
                item_id=item_id_map.get(str(_clean_text(row.get("return_item_code")))),
            )
            for row in source_rows
        ]
        return await upsert_history_rows(target_connection, payloads, batch_size=batch_size)
    except Exception:
        await target_connection.rollback()
        raise
    finally:
        target_connection.close()


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--limit", type=int, help="仅同步前 N 条，便于联调验证")
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error("--batch-size 必须大于 0")
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit 必须大于 0")
    return args


def main() -> None:
    args = parse_args()
    synced = asyncio.run(sync_inquiry_history(batch_size=args.batch_size, limit=args.limit))
    print(f"item_inquiry_history 已处理 {synced} 行")


if __name__ == "__main__":
    main()
