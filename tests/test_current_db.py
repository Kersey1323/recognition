#!/usr/bin/env python3
"""
测试当前应用配置的数据库连接
"""
import asyncio
from csrcqsf.settings import ai_settings
from csrcqsf.infra.db.main_db import engine
from sqlalchemy import text


async def test_current_db():
    """测试当前配置的数据库"""
    print("=" * 60)
    print("测试当前应用配置的数据库")
    print("=" * 60)
    print(f"\n配置信息:")
    print(f"  主机: {ai_settings.mysql.url}")
    print(f"  端口: {ai_settings.mysql.port}")
    print(f"  用户: {ai_settings.mysql.user_name}")
    print(f"  DSN: {ai_settings.get_async_mysql_dsn()}")
    print("\n" + "=" * 60)
    
    try:
        print("\n[1/4] 测试连接...")
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT version()"))
            version = result.scalar()
            print(f"✓ 连接成功！")
            print(f"  PostgreSQL 版本: {version[:60]}...")
        
        print("\n[2/4] 检查 parts.item_info 表...")
        async with engine.connect() as conn:
            result = await conn.execute(text("""
                SELECT COUNT(*) 
                FROM information_schema.tables
                WHERE table_schema = 'parts' 
                  AND table_name = 'item_info'
            """))
            count = result.scalar()
            if count > 0:
                print(f"✓ parts.item_info 表存在")
            else:
                print(f"✗ parts.item_info 表不存在")
        
        print("\n[3/4] 检查字段 parent_num 和 son_num...")
        async with engine.connect() as conn:
            result = await conn.execute(text("""
                SELECT column_name 
                FROM information_schema.columns
                WHERE table_schema = 'parts' 
                  AND table_name = 'item_info'
                  AND column_name IN ('parent_num', 'son_num')
            """))
            columns = [row[0] for row in result]
            
            if 'parent_num' in columns:
                print(f"✓ parent_num 字段存在")
            else:
                print(f"✗ parent_num 字段不存在 ⚠️")
            
            if 'son_num' in columns:
                print(f"✓ son_num 字段存在")
            else:
                print(f"✗ son_num 字段不存在 ⚠️")
        
        print("\n[4/4] 查询配件数量...")
        async with engine.connect() as conn:
            result = await conn.execute(text("""
                SELECT COUNT(*) FROM parts.item_info
            """))
            count = result.scalar()
            print(f"✓ 配件总数: {count}")
        
        print("\n" + "=" * 60)
        print("✅ 测试完成！")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(test_current_db())
