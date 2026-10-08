"""Copy procurement history into local Kingbase and supplement business suppliers.

Run with PYTHONPATH=. and SOURCE_DB_PASSWORD in the environment. Defaults to
preview; --apply backs up existing target rows before importing. The remote
connection always uses a read-only transaction.
"""

import argparse
import asyncio
from datetime import datetime
import io
import json
import os
from pathlib import Path

from dotenv import dotenv_values
import psycopg2
from psycopg2 import sql


TABLE = "sgo_procure_supplier"
ROOT = Path(__file__).resolve().parents[2]


def copy_source(apply):
    config = dotenv_values(ROOT / ".env")
    if config.get("SGO_DATABASE_TYPE") != "kingbase" or config.get("SGO_KINGBASE_HOST") not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Target must be local Kingbase")
    remote = psycopg2.connect(
        host="10.22.33.22", port=54321, dbname="mdp_sgo", user="sgo_user",
        password=os.environ["SOURCE_DB_PASSWORD"], connect_timeout=10,
        options="-c default_transaction_read_only=on -c statement_timeout=60000",
    )
    remote.set_session(readonly=True, isolation_level="REPEATABLE READ")
    local = psycopg2.connect(
        host=config["SGO_KINGBASE_HOST"], port=config["SGO_KINGBASE_PORT"],
        dbname=config["SGO_KINGBASE_DATABASE"], user=config["SGO_KINGBASE_USER"],
        password=config["SGO_KINGBASE_PASSWORD"], connect_timeout=10,
    )
    try:
        with remote.cursor() as source, local.cursor() as target:
            source.execute("SHOW transaction_read_only")
            assert source.fetchone()[0] == "on"
            source.execute("SELECT a.attname,format_type(a.atttypid,a.atttypmod) FROM pg_attribute a WHERE a.attrelid='public.sgo_procure_supplier'::regclass AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum")
            columns = source.fetchall()
            source.execute("SELECT count(*),count(distinct id) FROM public.sgo_procure_supplier")
            count, unique_count = source.fetchone()
            if not count or count != unique_count:
                raise ValueError("Empty source or duplicate source IDs")
            target.execute("SELECT to_regclass('public.sgo_procure_supplier')")
            exists = target.fetchone()[0] is not None
            print(json.dumps({"remote_rows": count, "local_table_exists": exists, "apply": apply}), flush=True)
            if not apply:
                return
            data = io.StringIO()
            source.copy_expert("COPY (SELECT * FROM public.sgo_procure_supplier ORDER BY id) TO STDOUT WITH CSV", data)
            if exists:
                backup = TABLE + "_bak_" + datetime.now().strftime("%Y%m%d_%H%M%S")
                target.execute(sql.SQL("LOCK TABLE public.{} IN ACCESS EXCLUSIVE MODE").format(sql.Identifier(TABLE)))
                target.execute(sql.SQL("CREATE TABLE public.{} AS TABLE public.{}").format(sql.Identifier(backup), sql.Identifier(TABLE)))
                target.execute(sql.SQL("TRUNCATE TABLE public.{}").format(sql.Identifier(TABLE)))
                print("Kingbase backup: " + backup, flush=True)
            else:
                target.execute(sql.SQL("CREATE TABLE public.{} ({}, PRIMARY KEY (id))").format(
                    sql.Identifier(TABLE), sql.SQL(", ").join(
                        sql.SQL("{} {}").format(sql.Identifier(name), sql.SQL(dtype)) for name, dtype in columns
                    ),
                ))
                target.execute("CREATE INDEX ix_procure_material ON public.sgo_procure_supplier (materiel_code)")
            data.seek(0)
            target.copy_expert(sql.SQL("COPY public.{} ({}) FROM STDIN WITH CSV").format(
                sql.Identifier(TABLE), sql.SQL(",").join(sql.Identifier(name) for name, _ in columns),
            ).as_string(local), data)
            check = io.StringIO()
            target.copy_expert("COPY (SELECT * FROM public.sgo_procure_supplier ORDER BY id) TO STDOUT WITH CSV", check)
            if data.getvalue() != check.getvalue():
                raise ValueError("Imported data differs from source")
            local.commit()
            print(f"Kingbase verified: {count} rows, complete content match", flush=True)
    finally:
        remote.rollback()
        remote.close()
        local.close()


async def sync_business(apply):
    from sqlalchemy import select, text
    from csrcqsf.infra.db.main_db import SessionLocal, engine
    from csrcqsf.infra.db.mdp_db import sgo_sessionLocal, sgo_engine
    from csrcqsf.models.orm.item import Items, ItemSupplier
    from csrcqsf.models.orm.sgo_external import SgoMaterielSupplier, SgoMaterielMasterplate
    from csrcqsf.models.supplier_mapping import PROCURE_SOURCE_PREFIX, key

    try:
        async with sgo_sessionLocal() as session:
            suppliers = await SgoMaterielSupplier.list_sgo_suppliers(session)
            templates = (await session.execute(select(
                SgoMaterielMasterplate.id, SgoMaterielMasterplate.MATNR,
            ).where(SgoMaterielMasterplate.column_id == "A1"))).all()
        codes = {str(row.id): key(row.MATNR) for row in templates}
        async with SessionLocal() as session:
            items = (await session.execute(select(Items.id, Items.item_code))).all()
            by_code = {}
            for row in items:
                by_code.setdefault(key(row.item_code), []).append(int(row.id))
            existing = (await session.scalars(select(ItemSupplier))).all()
            existing_by_id = {row.source_supplier_id: row for row in existing}
            official_pairs = {(row.item_id, key(row.supplier_code)) for row in existing
                              if not row.source_supplier_id.startswith(PROCURE_SOURCE_PREFIX)}
            payloads = []
            unmatched = ambiguous = unchanged = 0
            for row in suppliers:
                if not str(row.id).startswith(PROCURE_SOURCE_PREFIX):
                    continue
                ids = by_code.get(codes[str(row.masterplate_id)], [])
                if not ids:
                    unmatched += 1
                    continue
                if len(ids) > 1:
                    ambiguous += 1
                    continue
                item_id = ids[0]
                if (item_id, key(row.supplier_code)) in official_pairs:
                    continue
                payload = dict(source_supplier_id=row.id, source_masterplate_id=row.masterplate_id,
                               item_id=item_id, supplier_code=row.supplier_code,
                               supplier_name=row.supplier_name, supplier_item_code=None,
                               supplier_item_name=None, supplier_parts_model=None,
                               model_number=None, manufacturer=None,
                               current_status=row.current_status, enable_status=row.enable_status)
                old = existing_by_id.get(row.id)
                if old is not None and all(getattr(old, k) == v for k, v in payload.items()):
                    unchanged += 1
                    continue
                payloads.append(payload)
            print(json.dumps(dict(business_rows_before=len(existing), upserts=len(payloads),
                                  new_items=len({p['item_id'] for p in payloads} - {r.item_id for r in existing}),
                                  unmatched=unmatched, ambiguous=ambiguous, unchanged=unchanged)), flush=True)
            if apply and payloads:
                backup = "item_supplier_info_bak_" + datetime.now().strftime("%Y%m%d_%H%M%S")
                await session.execute(text(f"CREATE TABLE `{backup}` LIKE item_supplier_info"))
                await session.execute(text(f"INSERT INTO `{backup}` SELECT * FROM item_supplier_info"))
                saved = await session.scalar(text(f"SELECT COUNT(*) FROM `{backup}`"))
                current = await session.scalar(text("SELECT COUNT(*) FROM item_supplier_info"))
                if saved != current:
                    raise ValueError("Business backup count mismatch")
                await session.commit()
                print(f"Business backup: {backup} ({saved} rows)", flush=True)
                await ItemSupplier.upsert_from_sgo(session, payloads)
                await session.commit()
            total = await session.scalar(text("SELECT COUNT(*) FROM item_supplier_info"))
            historical = await session.scalar(text("SELECT COUNT(*) FROM item_supplier_info WHERE source_supplier_id LIKE 'procure:%'"))
            print(json.dumps(dict(business_rows_after=total, historical_rows=historical)), flush=True)
    finally:
        await engine.dispose()
        await sgo_engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--business-only", action="store_true")
    args = parser.parse_args()
    if not args.business_only:
        copy_source(args.apply)
    if args.apply or args.business_only:
        asyncio.run(sync_business(args.apply))
