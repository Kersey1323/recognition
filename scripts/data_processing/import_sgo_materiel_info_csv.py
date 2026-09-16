"""Load an exported SGO materiel table into the local Kingbase replica only."""

from __future__ import annotations

import argparse
import asyncio
import csv
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url

from csrcqsf.core.settings import ai_settings, sgo_database_type
from csrcqsf.infra.db.mdp_db import sgo_engine


COLUMNS = (
    "id", "MATNR", "MAKTX", "VRKME", "ZEINR", "WRKST", "data_source_flag",
    "CPUTM", "tenant_id_", "NTGEW", "GROES", "MTART", "MATERIEL_TYPE",
    "S_MAKTX", "S_VRKME", "S_ZEINR", "S_WRKST", "WK_WEIGHT",
    "FEATURE_CODE", "ISSUED_FLAG", "unit_convert",
)


async def import_csv(path: Path) -> int:
    url = make_url(ai_settings.get_sgo_dsn())
    if sgo_database_type != "kingbase" or url.host not in {"127.0.0.1", "localhost"}:
        raise ValueError("只允许导入本机 Kingbase 副本")

    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError("导出文件列名或顺序与 sgo_materiel_info 不一致")

        definitions = [
            '"id" VARCHAR(64) PRIMARY KEY',
            '"MATNR" VARCHAR(100) NOT NULL UNIQUE',
            *[f'"{column}" TEXT' for column in COLUMNS[2:]],
        ]
        # 本地副本缺表时只新建这张表；重复导入保留已存在的行。
        async with sgo_engine.begin() as connection:
            await connection.execute(text(
                "CREATE TABLE IF NOT EXISTS sgo_materiel_info ("
                + ", ".join(definitions) + ")"
            ))

        binds = ", ".join(f":{column}" for column in COLUMNS)
        names = ", ".join(f'"{column}"' for column in COLUMNS)
        statement = text(
            f"INSERT INTO sgo_materiel_info ({names}) VALUES ({binds}) "
            'ON CONFLICT ("id") DO NOTHING'
        )
        count = 0
        batch = []
        for row in reader:
            if not row["id"] or not row["MATNR"]:
                raise ValueError(f"导出文件第 {count + 2} 行缺少 ID 或物料编码")
            batch.append({column: row[column] or None for column in COLUMNS})
            if len(batch) >= 1000:
                async with sgo_engine.begin() as connection:
                    await connection.execute(statement, batch)
                count += len(batch)
                batch.clear()
        if batch:
            async with sgo_engine.begin() as connection:
                await connection.execute(statement, batch)
            count += len(batch)
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="本机导出的 CSV 文件")
    args = parser.parse_args()
    print(f"已处理 CSV 记录: {asyncio.run(import_csv(args.source))}")


if __name__ == "__main__":
    main()
