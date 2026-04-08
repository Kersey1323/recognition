#!/usr/bin/env python3
"""
检查数据库中的图片URL
"""
import asyncio
from sqlalchemy import text
from csrcqsf.data.pg import engine


async def check_images():
    """检查数据库中的图片数据"""
    print("=" * 70)
    print("检查数据库中的图片URL")
    print("=" * 70)
    
    async with engine.connect() as conn:
        # 检查所有表
        print("\n[1/3] 查找包含图片的表...")
        result = await conn.execute(text("""
            SELECT table_name 
            FROM information_schema.tables
            WHERE table_schema = 'parts'
            ORDER BY table_name
        """))
        tables = [row[0] for row in result]
        print(f"找到 {len(tables)} 个表:")
        for table in tables:
            print(f"  - {table}")
        
        # 检查 sgo_item_images 表
        if 'sgo_item_images' in tables:
            print("\n[2/3] 检查 sgo_item_images 表...")
            result = await conn.execute(text("""
                SELECT COUNT(*) FROM parts.sgo_item_images
            """))
            count = result.scalar()
            print(f"  总记录数: {count:,}")
            
            if count > 0:
                result = await conn.execute(text("""
                    SELECT item_id, image_url, image_source, raw_url
                    FROM parts.sgo_item_images
                    LIMIT 5
                """))
                print(f"\n  示例图片URL (前5条):")
                for row in result:
                    print(f"    配件ID: {row[0]}")
                    print(f"      图片URL: {row[1][:80]}...")
                    print(f"      来源: {row[2]}")
                    print(f"      原始URL: {row[3][:80] if row[3] else 'None'}...")
                    print()
                
                # 统计图片URL的域名
                result = await conn.execute(text("""
                    SELECT 
                        CASE 
                            WHEN image_url LIKE 'http://%' THEN 
                                SUBSTRING(image_url FROM 'http://([^/]+)')
                            WHEN image_url LIKE 'https://%' THEN 
                                SUBSTRING(image_url FROM 'https://([^/]+)')
                            ELSE 'other'
                        END as domain,
                        COUNT(*) as count
                    FROM parts.sgo_item_images
                    WHERE image_url IS NOT NULL
                    GROUP BY domain
                    ORDER BY count DESC
                    LIMIT 10
                """))
                print(f"  图片URL域名统计:")
                for row in result:
                    print(f"    {row[0]}: {row[1]:,} 个")
        
        # 检查其他可能包含图片的表
        print("\n[3/3] 检查其他表...")
        for table in tables:
            if 'image' in table.lower() or 'photo' in table.lower():
                result = await conn.execute(text(f"""
                    SELECT COUNT(*) FROM parts.{table}
                """))
                count = result.scalar()
                print(f"  {table}: {count:,} 条记录")
    
    await engine.dispose()
    
    print("\n" + "=" * 70)
    print("✅ 检查完成！")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(check_images())
