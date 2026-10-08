"""Refresh SGO-owned item metadata after replacing the local Kingbase snapshot.

Dry-run by default. Apply backs up the business tables before changing item_info.
The regular parts sync must run afterward to add new items and reconcile supplier
and hierarchy snapshots.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime
from pathlib import Path

import asyncmy
import psycopg2
from dotenv import dotenv_values
from psycopg2 import sql


ROOT = Path(__file__).resolve().parents[2]
FIELDS = ("item_name", "parts_model", "drawing_number", "material_quality")
BACKUP_TABLES = ("item_info", "item_supplier_info", "item_hierarchy_relation")
COLUMN_PRIORITY = {"A1": 0, "A3": 1, "A5": 2}


def clean(value: str | None) -> str | None:
    return value.strip() or None if value is not None else None


def source_key(row: tuple) -> tuple[int, int]:
    template_id, column_id = row[:2]
    return COLUMN_PRIORITY[column_id], -(int(template_id) if str(template_id).isdigit() else -1)


def load_source(cursor, suffix: str = "") -> dict[str, tuple[str | None, ...]]:
    masterplate = sql.Identifier(f"sgo_materiel_masterplate{suffix}")
    info = sql.Identifier(f"sgo_materiel_info{suffix}")
    cursor.execute(
        sql.SQL(
            "SELECT m.id, m.column_id, m.\"MATNR\", "
            "COALESCE(NULLIF(BTRIM(m.maktx), ''), NULLIF(BTRIM(i.\"MAKTX\"), '')), "
            "COALESCE(NULLIF(BTRIM(m.wrkst), ''), NULLIF(BTRIM(i.\"WRKST\"), '')), "
            "COALESCE(NULLIF(BTRIM(m.zeinr), ''), NULLIF(BTRIM(i.\"ZEINR\"), '')), "
            "NULLIF(BTRIM(m.material_quality), '') "
            "FROM {} m LEFT JOIN {} i "
            "ON m.materiel_info_id = i.id AND m.\"MATNR\" = i.\"MATNR\" "
            "WHERE m.column_id = ANY(%s)"
        ).format(masterplate, info),
        (list(COLUMN_PRIORITY),),
    )
    chosen: dict[str, tuple[tuple[int, int], tuple[str | None, ...]]] = {}
    for row in cursor:
        code = clean(row[2])
        if code is None:
            continue
        key = code.casefold()
        priority = source_key(row)
        if key not in chosen or priority < chosen[key][0]:
            chosen[key] = priority, tuple(clean(value) for value in row[3:])
    return {code: values for code, (_, values) in chosen.items()}


def plan_updates(
    business_rows: list[tuple],
    old_source: dict[str, tuple[str | None, ...]],
    new_source: dict[str, tuple[str | None, ...]],
) -> tuple[list[tuple], Counter]:
    updates = []
    counts: Counter = Counter()
    for item_id, item_code, *current in business_rows:
        key = clean(item_code)
        if key is None or key.casefold() not in new_source:
            counts["outside_new_source"] += 1
            continue
        key = key.casefold()
        prior = old_source.get(key, (None,) * len(FIELDS))
        fresh = new_source[key]
        target = list(current)
        for index, field in enumerate(FIELDS):
            existing = clean(current[index])
            old_value = prior[index]
            new_value = fresh[index]
            if not new_value or existing == new_value:
                continue
            # A changed value that no longer matches the old source is likely
            # an operator edit; never replace it with the refreshed SGO value.
            if existing is not None and existing != old_value:
                counts[f"preserved_{field}"] += 1
                continue
            target[index] = new_value
            counts[f"changed_{field}"] += 1
        if target != current:
            # The old values form an optimistic concurrency guard at UPDATE time.
            updates.append((*target, item_id, item_code, *current))
    counts["changed_items"] = len(updates)
    return updates, counts


async def business_rows(connection) -> list[tuple]:
    async with connection.cursor() as cursor:
        await cursor.execute(
            "SELECT id, item_code, item_name, parts_model, drawing_number, "
            "material_quality FROM item_info"
        )
        return list(await cursor.fetchall())


async def backup_tables(connection, suffix: str) -> None:
    async with connection.cursor() as cursor:
        for table in BACKUP_TABLES:
            backup = f"{table}_bak_{suffix}"
            await cursor.execute(f"CREATE TABLE `{backup}` LIKE `{table}`")
            await cursor.execute(f"INSERT INTO `{backup}` SELECT * FROM `{table}`")
            await cursor.execute(f"SELECT COUNT(*) FROM `{table}`")
            before = (await cursor.fetchone())[0]
            await cursor.execute(f"SELECT COUNT(*) FROM `{backup}`")
            copied = (await cursor.fetchone())[0]
            if copied != before:
                raise RuntimeError(f"Backup count mismatch for {table}: {copied} != {before}")
            print(f"backup {backup}: {copied}", flush=True)
    # MySQL DDL commits implicitly. Commit copied rows before changing live data
    # so a later UPDATE rollback cannot leave empty backup tables behind.
    await connection.commit()


async def apply_updates(connection, updates: list[tuple]) -> None:
    statement = (
        "UPDATE item_info SET item_name=%s, parts_model=%s, drawing_number=%s, "
        "material_quality=%s WHERE id=%s AND item_code=%s "
        "AND item_name <=> %s AND parts_model <=> %s "
        "AND drawing_number <=> %s AND material_quality <=> %s"
    )
    async with connection.cursor() as cursor:
        for start in range(0, len(updates), 500):
            batch = updates[start:start + 500]
            await cursor.executemany(statement, batch)
            if cursor.rowcount != len(batch):
                raise RuntimeError(
                    f"Concurrent item change in batch {start}: "
                    f"updated {cursor.rowcount} of {len(batch)}"
                )
            print(f"updated {start + len(batch)}/{len(updates)}", flush=True)
    await connection.commit()


async def run(apply: bool, expected_host: str) -> None:
    config = dotenv_values(ROOT / ".env")
    if config.get("SGO_DATABASE_TYPE") != "kingbase" or config.get("SGO_KINGBASE_HOST") not in {
        "127.0.0.1", "localhost", "::1"
    }:
        raise ValueError("SGO source must be the local Kingbase snapshot")
    if config.get("MAIN_DB_HOST") != expected_host:
        raise ValueError("Business MySQL host does not match --expected-main-host")
    pg = psycopg2.connect(
        host=config["SGO_KINGBASE_HOST"],
        port=int(config["SGO_KINGBASE_PORT"]),
        user=config["SGO_KINGBASE_USER"],
        password=config["SGO_KINGBASE_PASSWORD"],
        dbname=config["SGO_KINGBASE_DATABASE"],
    )
    try:
        pg.set_session(readonly=True)
        with pg.cursor() as cursor:
            old = load_source(cursor, "_bak_20260929_102150")
            new = load_source(cursor)
    finally:
        pg.close()

    mysql = await asyncmy.connect(
        host=config["MAIN_DB_HOST"],
        port=int(config["MAIN_DB_PORT"]),
        user=config["MAIN_DB_USER"],
        password=config["MAIN_DB_PASSWORD"],
        db=config["MAIN_DB_DATABASE"],
    )
    try:
        rows = await business_rows(mysql)
        updates, counts = plan_updates(rows, old, new)
        print(f"old source={len(old)}, new source={len(new)}, business={len(rows)}")
        print(f"planned changes={dict(sorted(counts.items()))}", flush=True)
        if not apply:
            return
        await backup_tables(mysql, datetime.now().strftime("%Y%m%d_%H%M%S"))
        await apply_updates(mysql, updates)
    except Exception:
        await mysql.rollback()
        raise
    finally:
        mysql.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Back up and update business MySQL")
    parser.add_argument("--expected-main-host", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.apply, args.expected_main_host))


if __name__ == "__main__":
    main()
