#!/usr/bin/env python3
"""将供应商 CSV 快照导入 SGO Kingbase 的 sgo_materiel_supplier 表。"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import text


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from csrcqsf.infra.db.mdp_db import sgo_engine  # noqa: E402


COLUMNS = (
    "id",
    "supplier_code",
    "supplier_name",
    "masterplate_id",
    "supply_cycle",
    "quality_period",
    "warranty_period",
    "min_packing_quantity",
    "min_order_quantity",
    "maintenance_notes",
    "transportation_notes",
    "create_time",
    "creater_account",
    "creater",
    "tenant_id_",
    "top_falg",
    "supplier_matnr",
    "supplier_maktx",
    "supplier_zeinr",
    "supplier_wrkst",
    "supplier_vrkme",
    "maintenance_cycle",
    "description",
    "model_number",
    "manufacturer",
    "technical_standard",
    "product_info_remark",
    "temp_price",
    "maintenance_level",
    "current_status",
    "flow_id",
    "with_draft",
    "supplier_data_rate",
    "audit_status",
    "enable_status",
    "supplier_material",
    "supplier_strength",
    "storage_life",
    "storage_life_unit",
    "quality_period_unit",
    "product_size",
    "product_size_type",
    "net_weight",
    "gross_weight",
    "standard_no",
    "standard_name",
    "storage_requirement",
)


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sgo_materiel_supplier (
  id VARCHAR(64) PRIMARY KEY,
  supplier_code VARCHAR(64),
  supplier_name VARCHAR(255),
  masterplate_id VARCHAR(64) NOT NULL,
  supply_cycle VARCHAR(100),
  quality_period VARCHAR(100),
  warranty_period VARCHAR(100),
  min_packing_quantity VARCHAR(100),
  min_order_quantity VARCHAR(100),
  maintenance_notes VARCHAR(500),
  transportation_notes VARCHAR(500),
  create_time TIMESTAMP NULL,
  creater_account VARCHAR(100),
  creater VARCHAR(100),
  tenant_id_ VARCHAR(64),
  top_falg VARCHAR(20),
  supplier_matnr VARCHAR(100),
  supplier_maktx VARCHAR(255),
  supplier_zeinr VARCHAR(255),
  supplier_wrkst VARCHAR(255),
  supplier_vrkme VARCHAR(50),
  maintenance_cycle VARCHAR(100),
  description TEXT,
  model_number VARCHAR(255),
  manufacturer VARCHAR(255),
  technical_standard VARCHAR(255),
  product_info_remark VARCHAR(500),
  temp_price VARCHAR(100),
  maintenance_level VARCHAR(100),
  current_status VARCHAR(50),
  flow_id VARCHAR(64),
  with_draft VARCHAR(50),
  supplier_data_rate VARCHAR(50),
  audit_status VARCHAR(50),
  enable_status VARCHAR(50),
  supplier_material VARCHAR(255),
  supplier_strength VARCHAR(255),
  storage_life VARCHAR(100),
  storage_life_unit VARCHAR(50),
  quality_period_unit VARCHAR(50),
  product_size VARCHAR(255),
  product_size_type VARCHAR(50),
  net_weight VARCHAR(100),
  gross_weight VARCHAR(100),
  standard_no VARCHAR(255),
  standard_name VARCHAR(255),
  storage_requirement VARCHAR(500)
)
"""


def _normalize_row(row: dict[str, str]) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for column in COLUMNS:
        value = (row.get(column) or "").strip()
        normalized[column] = value or None
    if normalized["create_time"] is not None:
        normalized["create_time"] = datetime.fromisoformat(
            str(normalized["create_time"])
        )
    return normalized


async def import_csv(csv_path: Path, *, replace: bool = False) -> int:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError("CSV 字段与 sgo_materiel_supplier 预期结构不一致")
        rows = [_normalize_row(row) for row in reader]

    column_sql = ", ".join(COLUMNS)
    value_sql = ", ".join(f":{column}" for column in COLUMNS)
    update_sql = ", ".join(
        f"{column} = EXCLUDED.{column}" for column in COLUMNS if column != "id"
    )
    upsert_sql = text(
        f"INSERT INTO sgo_materiel_supplier ({column_sql}) "
        f"VALUES ({value_sql}) ON CONFLICT (id) DO UPDATE SET {update_sql}"
    )

    async with sgo_engine.begin() as conn:
        await conn.execute(text(CREATE_TABLE_SQL))
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_sgo_materiel_supplier_masterplate "
                "ON sgo_materiel_supplier (masterplate_id)"
            )
        )
        if replace:
            await conn.execute(text("TRUNCATE TABLE sgo_materiel_supplier"))
        for offset in range(0, len(rows), 1000):
            await conn.execute(upsert_sql, rows[offset : offset + 1000])

    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path", type=Path)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="导入前清空现有供应商快照",
    )
    args = parser.parse_args()
    imported = asyncio.run(import_csv(args.csv_path, replace=args.replace))
    print(f"sgo_materiel_supplier 导入完成: rows={imported}")


if __name__ == "__main__":
    main()
