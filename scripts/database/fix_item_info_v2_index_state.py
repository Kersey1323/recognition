#!/usr/bin/env python3
"""
为 parts.item_info 增加 V2 索引状态缓存字段。
"""
import asyncio

from sqlalchemy import text

from csrcqsf.data.pg import engine


async def add_v2_index_state_columns():
    print("开始修复 item_info 的 V2 索引状态字段...")
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'parts'
                  AND table_name = 'item_info'
                  AND column_name IN ('has_v2_index', 'v2_indexed_image_num', 'v2_index_updated_at')
            """))
            existing = {row[0] for row in result}
            print(f"已存在字段: {sorted(existing)}")

            if "has_v2_index" not in existing:
                print("添加 has_v2_index 字段...")
                await conn.execute(text("""
                    ALTER TABLE parts.item_info
                    ADD COLUMN has_v2_index INTEGER NOT NULL DEFAULT 0
                """))
                print("✓ has_v2_index 字段添加成功")
            else:
                print("✓ has_v2_index 字段已存在")

            if "v2_indexed_image_num" not in existing:
                print("添加 v2_indexed_image_num 字段...")
                await conn.execute(text("""
                    ALTER TABLE parts.item_info
                    ADD COLUMN v2_indexed_image_num INTEGER NOT NULL DEFAULT 0
                """))
                print("✓ v2_indexed_image_num 字段添加成功")
            else:
                print("✓ v2_indexed_image_num 字段已存在")

            if "v2_index_updated_at" not in existing:
                print("添加 v2_index_updated_at 字段...")
                await conn.execute(text("""
                    ALTER TABLE parts.item_info
                    ADD COLUMN v2_index_updated_at TIMESTAMP NULL
                """))
                print("✓ v2_index_updated_at 字段添加成功")
            else:
                print("✓ v2_index_updated_at 字段已存在")

        print("✅ item_info 的 V2 索引状态字段修复完成")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(add_v2_index_state_columns())
