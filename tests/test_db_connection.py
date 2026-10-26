#!/usr/bin/env python3
"""
数据库连接测试脚本
测试到 192.168.100.8 PostgreSQL 的连接
"""
import asyncio
import os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from urllib.parse import quote_plus

# 数据库连接信息
DB_USER = "root"
DB_PASSWORD = os.getenv("PG_PASSWORD", "")
DB_HOST = "192.168.100.8"
DB_PORT = "5432"
DB_NAME = "zcsf"

DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{quote_plus(DB_PASSWORD)}@{DB_HOST}:{DB_PORT}/{DB_NAME}"


async def test_connection():
    """测试数据库连接"""
    print("=" * 60)
    print("PostgreSQL 数据库连接测试")
    print("=" * 60)
    print(f"\n连接信息:")
    print(f"  主机: {DB_HOST}")
    print(f"  端口: {DB_PORT}")
    print(f"  数据库: {DB_NAME}")
    print(f"  用户: {DB_USER}")
    print(f"  密码: {'*' * len(DB_PASSWORD)}")
    print(f"\n连接字符串: postgresql+asyncpg://{DB_USER}:***@{DB_HOST}:{DB_PORT}/{DB_NAME}")
    print("\n" + "=" * 60)
    
    engine = create_async_engine(DATABASE_URL, echo=False)
    
    try:
        print("\n[1/5] 测试基本连接...")
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT version()"))
            version = result.scalar()
            print(f"✓ 连接成功！")
            print(f"  PostgreSQL 版本: {version[:50]}...")
        
        print("\n[2/5] 检查 parts schema 是否存在...")
        async with engine.connect() as conn:
            result = await conn.execute(text("""
                SELECT schema_name 
                FROM information_schema.schemata 
                WHERE schema_name = 'parts'
            """))
            schema = result.scalar()
            if schema:
                print(f"✓ parts schema 存在")
            else:
                print(f"✗ parts schema 不存在")
        
        print("\n[3/5] 检查 parts.item_info 表是否存在...")
        async with engine.connect() as conn:
            result = await conn.execute(text("""
                SELECT table_name 
                FROM information_schema.tables
                WHERE table_schema = 'parts' 
                  AND table_name = 'item_info'
            """))
            table = result.scalar()
            if table:
                print(f"✓ parts.item_info 表存在")
            else:
                print(f"✗ parts.item_info 表不存在")
        
        print("\n[4/5] 检查表字段...")
        async with engine.connect() as conn:
            result = await conn.execute(text("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'parts' 
                  AND table_name = 'item_info'
                ORDER BY ordinal_position
            """))
            columns = result.fetchall()
            if columns:
                print(f"✓ 找到 {len(columns)} 个字段:")
                for col in columns:
                    nullable = "NULL" if col[2] == "YES" else "NOT NULL"
                    default = f"DEFAULT {col[3]}" if col[3] else ""
                    print(f"    - {col[0]}: {col[1]} {nullable} {default}")
            else:
                print(f"✗ 未找到字段")
        
        print("\n[5/5] 检查关键字段 parent_num 和 son_num...")
        async with engine.connect() as conn:
            result = await conn.execute(text("""
                SELECT column_name 
                FROM information_schema.columns
                WHERE table_schema = 'parts' 
                  AND table_name = 'item_info'
                  AND column_name IN ('parent_num', 'son_num')
            """))
            key_columns = [row[0] for row in result]
            
            if 'parent_num' in key_columns:
                print(f"✓ parent_num 字段存在")
            else:
                print(f"✗ parent_num 字段不存在 ⚠️")
            
            if 'son_num' in key_columns:
                print(f"✓ son_num 字段存在")
            else:
                print(f"✗ son_num 字段不存在 ⚠️")
        
        print("\n" + "=" * 60)
        print("✅ 数据库连接测试完成！")
        print("=" * 60)
        
        # 返回是否需要添加字段
        return 'parent_num' not in key_columns or 'son_num' not in key_columns
        
    except Exception as e:
        print(f"\n❌ 连接失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await engine.dispose()


if __name__ == "__main__":
    need_fix = asyncio.run(test_connection())
    
    if need_fix:
        print("\n⚠️  需要添加缺失的字段！")
        print("运行以下命令修复:")
        print("  python fix_db_columns_production.py")
    else:
        print("\n✓ 数据库结构正常，无需修复")
