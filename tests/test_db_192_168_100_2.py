#!/usr/bin/env python3
"""
测试 192.168.100.2 数据库
"""
import asyncio
import os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from urllib.parse import quote_plus

# 192.168.100.2 数据库连接信息
DB_USER = "root"
DB_PASSWORD = os.getenv("PG_PASSWORD", "")
DB_HOST = "192.168.100.2"
DB_PORT = "5432"
DB_NAME = "zcsf"

DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{quote_plus(DB_PASSWORD)}@{DB_HOST}:{DB_PORT}/{DB_NAME}"


async def test_db():
    """测试数据库并检查表结构"""
    print("=" * 70)
    print(f"测试 {DB_HOST}:{DB_PORT}/{DB_NAME} 数据库")
    print("=" * 70)
    
    engine = create_async_engine(DATABASE_URL, echo=False)
    
    try:
        print("\n[1/5] 测试连接...")
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT version()"))
            version = result.scalar()
            print(f"✓ 连接成功！")
            print(f"  PostgreSQL 版本: {version[:60]}...")
        
        print("\n[2/5] 检查 parts schema...")
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
                return
        
        print("\n[3/5] 检查 parts.item_info 表...")
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
                return
        
        print("\n[4/5] 查看完整表结构...")
        async with engine.connect() as conn:
            result = await conn.execute(text("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'parts' 
                  AND table_name = 'item_info'
                ORDER BY ordinal_position
            """))
            columns = result.fetchall()
            print(f"✓ 找到 {len(columns)} 个字段:")
            for col in columns:
                nullable = "NULL" if col[2] == "YES" else "NOT NULL"
                default = f"DEFAULT {col[3]}" if col[3] else ""
                print(f"    {col[0]:25} {col[1]:20} {nullable:10} {default}")
        
        print("\n[5/5] 检查关键字段...")
        async with engine.connect() as conn:
            needed_fields = ['parent_num', 'son_num', 'image_index_num', 'feature_index_num']
            result = await conn.execute(text("""
                SELECT column_name 
                FROM information_schema.columns
                WHERE table_schema = 'parts' 
                  AND table_name = 'item_info'
                  AND column_name IN ('parent_num', 'son_num', 'image_index_num', 'feature_index_num')
            """))
            existing = [row[0] for row in result]
            
            for field in needed_fields:
                if field in existing:
                    print(f"  ✓ {field} 存在")
                else:
                    print(f"  ✗ {field} 缺失")
        
        print("\n[6/6] 查询配件数量...")
        async with engine.connect() as conn:
            result = await conn.execute(text("""
                SELECT COUNT(*) FROM parts.item_info
            """))
            count = result.scalar()
            print(f"✓ 配件总数: {count:,}")
        
        print("\n" + "=" * 70)
        print("✅ 测试完成！")
        print("=" * 70)
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(test_db())
