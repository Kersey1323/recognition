#!/usr/bin/env python3
"""只读复制指定库区库存到本地 Kingbase；完整导入核对后再替换同名表。"""

from __future__ import annotations

import argparse
import io
import os
from datetime import datetime
from pathlib import Path

import psycopg2
from psycopg2 import sql
from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[2]
TABLE = "wms_stock_detail"
WAREHOUSES = ("2514", "JS00")
SCOPE_SQL = '"WERKS" = %s AND "LGORT" IN (%s, %s) AND "tenant_id_" = %s'


def column_type(column: tuple) -> str:
    name, data_type, length, precision, scale, _nullable = column
    if data_type in ("character varying", "varchar", "character", "char"):
        kind = "CHAR" if data_type in ("character", "char") else "VARCHAR"
        return f"{kind}({int(length)})" if length else "TEXT"
    if data_type in ("numeric", "decimal"):
        return f"NUMERIC({int(precision)},{int(scale or 0)})" if precision else "NUMERIC"
    types = {
        "date": "DATE", "datetime": "TIMESTAMP",
        "timestamp without time zone": "TIMESTAMP",
        "timestamp with time zone": "TIMESTAMPTZ",
        "text": "TEXT", "integer": "INTEGER", "bigint": "BIGINT",
        "smallint": "SMALLINT", "boolean": "BOOLEAN",
        "double precision": "DOUBLE PRECISION", "real": "REAL",
    }
    if data_type not in types:
        raise ValueError(f"Unsupported source column type: {name} {data_type}")
    return types[data_type]


def copy_buffer(rows) -> io.StringIO:
    def cell(value):
        if value is None:
            return "\\N"
        # COPY TEXT 使用反斜线转义；名称中的换行、制表符和空字符串也必须原样保留。
        return str(value).replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")

    return io.StringIO("".join("\t".join(cell(value) for value in row) + "\n" for row in rows))


def sync(args) -> dict:
    config = dotenv_values(ROOT / ".env")
    local_host = config.get("SGO_KINGBASE_HOST")
    if config.get("SGO_DATABASE_TYPE") != "kingbase" or local_host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Target must be the local Kingbase configured in .env")
    password = os.environ.get("SGO_STOCK_SOURCE_PASSWORD")
    if not password:
        raise ValueError("Set SGO_STOCK_SOURCE_PASSWORD for the read-only source connection")
    source = psycopg2.connect(
        host=args.source_host, port=args.source_port, user=args.source_user,
        password=password, dbname=args.source_database, connect_timeout=10,
        options="-c default_transaction_read_only=on -c statement_timeout=120000",
    )
    source.set_session(readonly=True, isolation_level="REPEATABLE READ")
    local = None
    try:
        scope = ("3100", *WAREHOUSES, args.tenant_id)
        with source.cursor() as cur:
            cur.execute("SHOW transaction_read_only")
            if cur.fetchone()[0] != "on":
                raise RuntimeError("Source connection is not read-only")
            cur.execute(
                "SELECT column_name,data_type,character_maximum_length,numeric_precision,"
                "numeric_scale,is_nullable FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position", (TABLE,),
            )
            columns = cur.fetchall()
            names = [column[0] for column in columns]
            if not {"id", "MATNR", "WERKS", "LGORT", "LGORTD", "GRARD", "CLABS", "tenant_id_"} <= set(names):
                raise ValueError("Source inventory schema is incomplete")
            cur.execute(sql.SQL("SELECT count(*) FROM public.{} WHERE " + SCOPE_SQL).format(sql.Identifier(TABLE)), scope)
            expected = cur.fetchone()[0]
            if expected == 0:
                raise ValueError("Source scope is empty; refusing to replace the local snapshot")
        local = psycopg2.connect(
            host=local_host, port=int(config["SGO_KINGBASE_PORT"]),
            user=config["SGO_KINGBASE_USER"], password=config["SGO_KINGBASE_PASSWORD"],
            dbname=config["SGO_KINGBASE_DATABASE"], connect_timeout=10,
            options="-c lock_timeout=10000 -c statement_timeout=120000",
        )
        suffix = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        staging = f"{TABLE}_load_{suffix}"
        backup = None
        copied = 0
        with local:
            with local.cursor() as target:
                target.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (TABLE,))
                definitions = [
                    sql.SQL("{} {} {}").format(
                        sql.Identifier(column[0]), sql.SQL(column_type(column)),
                        sql.SQL("NOT NULL" if column[5] == "NO" else "NULL"),
                    ) for column in columns
                ]
                definitions.append(sql.SQL('PRIMARY KEY ("id")'))
                target.execute(sql.SQL("CREATE TABLE public.{} ({})").format(
                    sql.Identifier(staging), sql.SQL(", ").join(definitions),
                ))
                print(f"source read-only; scope=3100/2514,JS00; expected_rows={expected}", flush=True)
                with source.cursor(name="stock_snapshot") as cursor:
                    cursor.execute(sql.SQL("SELECT {} FROM public.{} WHERE " + SCOPE_SQL).format(
                        sql.SQL(", ").join(map(sql.Identifier, names)), sql.Identifier(TABLE),
                    ), scope)
                    copy_sql = sql.SQL("COPY public.{} ({}) FROM STDIN").format(
                        sql.Identifier(staging), sql.SQL(", ").join(map(sql.Identifier, names)),
                    ).as_string(local)
                    while True:
                        rows = cursor.fetchmany(args.batch_size)
                        if not rows:
                            break
                        target.copy_expert(copy_sql, copy_buffer(rows))
                        copied += len(rows)
                        print(f"copied {copied}/{expected}", flush=True)
                target.execute(sql.SQL("SELECT count(*) FROM public.{}").format(sql.Identifier(staging)))
                if copied != expected or target.fetchone()[0] != expected:
                    raise RuntimeError("Snapshot row count mismatch; original table remains unchanged")
                for index_suffix, fields in (
                    ("code", ("MATNR",)), ("scope", ("tenant_id_", "WERKS", "LGORT")),
                ):
                    target.execute(sql.SQL("CREATE INDEX {} ON public.{} ({})").format(
                        sql.Identifier(f"stock_{suffix}_{index_suffix}"), sql.Identifier(staging),
                        sql.SQL(", ").join(map(sql.Identifier, fields)),
                    ))
                target.execute("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=%s)", (TABLE,))
                if target.fetchone()[0]:
                    backup = f"{TABLE}_bak_{suffix}"
                    target.execute(sql.SQL("ALTER TABLE public.{} RENAME TO {}").format(
                        sql.Identifier(TABLE), sql.Identifier(backup),
                    ))
                # 表结构、数据和索引校验完成后才替换；失败则回滚整个本地事务。
                target.execute(sql.SQL("ALTER TABLE public.{} RENAME TO {}").format(
                    sql.Identifier(staging), sql.Identifier(TABLE),
                ))
                target.execute(sql.SQL("ANALYZE public.{}").format(sql.Identifier(TABLE)))
        return {"table": TABLE, "rows": copied, "backup": backup, "target": f"{local_host}:{config['SGO_KINGBASE_PORT']}/{config['SGO_KINGBASE_DATABASE']}"}
    finally:
        source.rollback()
        source.close()
        if local is not None:
            local.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-host", default="10.22.33.22")
    parser.add_argument("--source-port", type=int, default=54321)
    parser.add_argument("--source-user", default="sgo_user")
    parser.add_argument("--source-database", default="mdp_sgo")
    parser.add_argument("--tenant-id", default="1463844437338755072")
    parser.add_argument("--batch-size", type=int, default=5000)
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error("--batch-size must be positive")
    print(sync(args), flush=True)


if __name__ == "__main__":
    main()
