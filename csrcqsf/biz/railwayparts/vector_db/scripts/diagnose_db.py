#!/usr/bin/env python3
"""
数据库结构诊断脚本
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from configparser import ConfigParser
from sqlalchemy import create_engine, inspect, text
from urllib.parse import quote_plus

def main():
    # 加载配置
    config = ConfigParser()
    config.read('vector_db/config/db_config.ini', encoding='utf-8')

    # 创建连接
    user = quote_plus(config.get('postgresql', 'user'))
    password = quote_plus(config.get('postgresql', 'password'))
    host = config.get('postgresql', 'host')
    port = config.getint('postgresql', 'port')
    database = config.get('postgresql', 'database')

    connection_string = f"postgresql://{user}:{password}@{host}:{port}/{database}"
    engine = create_engine(connection_string)

    print("=" * 60)
    print("数据库结构诊断")
    print("=" * 60)

    # 获取所有 schema
    inspector = inspect(engine)
    schemas = inspector.get_schema_names()
    print(f"\n数据库中的 schema (共 {len(schemas)} 个):")
    for schema in schemas:
        print(f"  - {schema}")

    # 获取所有表（包括所有 schema）
    all_tables = []
    for schema in schemas:
        tables = inspector.get_table_names(schema=schema)
        for table in tables:
            all_tables.append((schema, table))

    print(f"\n数据库中的表 (共 {len(all_tables)} 个):")
    for schema, table in sorted(all_tables):
        print(f"  - {schema}.{table}")

    # 查找包含 item 的表
    print("\n包含 'item' 的表:")
    item_tables = [(s, t) for s, t in all_tables if 'item' in t.lower()]
    for schema, table in item_tables:
        print(f"\n表: {schema}.{table}")
        columns = inspector.get_columns(table, schema=schema)
        print("  字段:")
        for col in columns:
            print(f"    - {col['name']}: {col['type']}")

    # 查找包含 image 的表
    print("\n包含 'image' 的表:")
    image_tables = [(s, t) for s, t in all_tables if 'image' in t.lower()]
    for schema, table in image_tables:
        print(f"\n表: {schema}.{table}")
        columns = inspector.get_columns(table, schema=schema)
        print("  字段:")
        for col in columns:
            print(f"    - {col['name']}: {col['type']}")

    # 尝试查询数据
    print("\n" + "=" * 60)
    print("尝试查询数据...")
    print("=" * 60)

    with engine.connect() as conn:
        # 尝试找到正确的表名
        for schema, table in item_tables:
            try:
                result = conn.execute(text(f"SELECT COUNT(*) FROM {schema}.{table}"))
                count = result.scalar()
                print(f"\n{schema}.{table}: {count} 条记录")

                # 显示前几条数据
                result = conn.execute(text(f"SELECT * FROM {schema}.{table} LIMIT 3"))
                rows = result.fetchall()
                if rows:
                    print(f"  示例数据:")
                    for row in rows:
                        print(f"    {dict(row._mapping)}")
            except Exception as e:
                print(f"\n{schema}.{table}: 查询失败 - {e}")

if __name__ == "__main__":
    main()
