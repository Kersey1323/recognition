#!/usr/bin/env python3
"""
数据库字段修复脚本
用于添加缺失的 parent_num 和 son_num 字段
"""
import asyncio
from sqlalchemy import text
from csrcqsf.infra.db.main_db import engine


async def add_missing_columns():
    """添加缺失的数据库字段"""
    print("开始修复数据库字段...")
    
    try:
        async with engine.begin() as conn:
            # 检查字段是否存在
            check_sql = text("""
                SELECT column_name 
                FROM information_schema.columns
                WHERE table_schema = 'parts' 
                  AND table_name = 'item_info'
                  AND column_name IN ('parent_num', 'son_num')
            """)
            
            result = await conn.execute(check_sql)
            existing_columns = [row[0] for row in result]
            
            print(f"已存在的字段: {existing_columns}")
            
            # 添加 parent_num
            if 'parent_num' not in existing_columns:
                print("添加 parent_num 字段...")
                await conn.execute(text("""
                    ALTER TABLE parts.item_info 
                    ADD COLUMN parent_num INTEGER NOT NULL DEFAULT 0
                """))
                print("✓ parent_num 字段添加成功")
            else:
                print("✓ parent_num 字段已存在")
            
            # 添加 son_num
            if 'son_num' not in existing_columns:
                print("添加 son_num 字段...")
                await conn.execute(text("""
                    ALTER TABLE parts.item_info 
                    ADD COLUMN son_num INTEGER NOT NULL DEFAULT 0
                """))
                print("✓ son_num 字段添加成功")
            else:
                print("✓ son_num 字段已存在")
            
            # 验证
            verify_sql = text("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'parts' 
                  AND table_name = 'item_info'
                  AND column_name IN ('parent_num', 'son_num')
                ORDER BY column_name
            """)
            
            result = await conn.execute(verify_sql)
            print("\n验证结果:")
            for row in result:
                print(f"  - {row[0]}: {row[1]}, nullable={row[2]}, default={row[3]}")
            
        print("\n✅ 数据库字段修复完成！")
        
    except Exception as e:
        print(f"\n❌ 修复失败: {e}")
        raise
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(add_missing_columns())
