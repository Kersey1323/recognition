#!/usr/bin/env python3
"""
生产数据库字段修复脚本
用于在 192.168.100.8 数据库上添加缺失的 parent_num 和 son_num 字段
"""
import asyncio
import os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from urllib.parse import quote_plus

# 维护脚本从本机环境读取凭据，避免将生产口令写入仓库。
DB_USER = "root"  # PostgreSQL 用户名
DB_PASSWORD = os.getenv("PG_PASSWORD", "")
DB_HOST = "192.168.100.8"
DB_PORT = "5432"  # PostgreSQL 使用 host 网络模式，直接监听在 5432 端口
DB_NAME = "zcsf"

# 构建连接字符串
DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{quote_plus(DB_PASSWORD)}@{DB_HOST}:{DB_PORT}/{DB_NAME}"


async def add_missing_columns():
    """添加缺失的数据库字段"""
    print(f"连接到数据库: {DB_HOST}:{DB_PORT}/{DB_NAME}")
    print("开始修复数据库字段...")
    
    engine = create_async_engine(DATABASE_URL, echo=False)
    
    try:
        async with engine.begin() as conn:
            # 检查 schema 是否存在
            check_schema = text("""
                SELECT schema_name 
                FROM information_schema.schemata 
                WHERE schema_name = 'parts'
            """)
            result = await conn.execute(check_schema)
            if not result.fetchone():
                print("创建 parts schema...")
                await conn.execute(text('CREATE SCHEMA IF NOT EXISTS "parts"'))
            
            # 检查表是否存在
            check_table = text("""
                SELECT table_name 
                FROM information_schema.tables
                WHERE table_schema = 'parts' 
                  AND table_name = 'item_info'
            """)
            result = await conn.execute(check_table)
            if not result.fetchone():
                print("❌ 错误: parts.item_info 表不存在！")
                print("请先运行应用以创建表结构。")
                return
            
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
            rows = result.fetchall()
            if rows:
                for row in rows:
                    print(f"  - {row[0]}: {row[1]}, nullable={row[2]}, default={row[3]}")
            else:
                print("  ❌ 未找到字段！")
            
        print("\n✅ 数据库字段修复完成！")
        print("\n请重启应用以使更改生效。")
        
    except Exception as e:
        print(f"\n❌ 修复失败: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        await engine.dispose()


if __name__ == "__main__":
    print("=" * 60)
    print("生产数据库字段修复脚本")
    print("=" * 60)
    print(f"\n目标数据库: {DB_HOST}:{DB_PORT}/{DB_NAME}")
    print("\n⚠️  警告: 请确认数据库连接信息正确！")
    print("⚠️  建议先在测试环境验证！\n")
    
    confirm = input("确认要继续吗? (yes/no): ")
    if confirm.lower() == 'yes':
        asyncio.run(add_missing_columns())
    else:
        print("操作已取消。")
