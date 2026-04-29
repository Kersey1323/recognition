"""
数据访问层 - PostgreSQL数据库连接
职责：数据库连接管理、会话管理、Schema初始化
注意：此层不包含具体的业务逻辑，仅提供数据库基础设施
"""

from bfrcommon.db import with_schema
from globals_vars import logger
from sqlalchemy import MetaData, text
from csrcqsf.settings import ai_settings
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from anyio import to_thread
from sqlalchemy.orm import DeclarativeBase

# 创建异步数据库引擎
# 使用 asyncpg 驱动连接 PostgreSQL
engine = create_async_engine(
    f'{ai_settings.get_async_pg_dsn()}',
    echo=False,  # 不打印SQL语句
    future=True,  # 使用SQLAlchemy 2.0风格
)

# 创建会话工厂
# expire_on_commit=False: 提交后对象不过期，可以继续访问
# autoflush=False: 不自动刷新，手动控制提交时机
SessionLocal = async_sessionmaker(expire_on_commit=False,
                                  autoflush=False, bind=engine)

# 创建带Schema的Base类
# 所有模型表都会创建在 'parts' schema下
Base = with_schema(schema_name='parts')


def with_schema_only(schema_name: str):
    metadata_obj = MetaData(schema=schema_name)

    class PlainBase(DeclarativeBase):
        metadata = metadata_obj

    return PlainBase


# 仅绑定 schema，不自动追加审计字段。
PlainBase = with_schema_only(schema_name='parts')


async def db_migrate():
    """
    数据库迁移：创建Schema和表
    
    执行时机：应用启动时（app.py的lifespan）
    操作：
    1. 创建 'parts' schema（如果不存在）
    2. 根据模型定义创建所有表
    """
    async with engine.begin() as conn:
        # 创建schema
        await conn.execute(text('CREATE SCHEMA IF NOT EXISTS "parts"'))
        # 创建所有表
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(PlainBase.metadata.create_all)
        # 为已存在的 item_info 表补齐新增字段
        await conn.execute(text("""
            ALTER TABLE parts.item_info
            ADD COLUMN IF NOT EXISTS weight DECIMAL
        """))
        await conn.execute(text("""
            ALTER TABLE parts.item_info
            ADD COLUMN IF NOT EXISTS source_video_path VARCHAR(500),
            ADD COLUMN IF NOT EXISTS source_video_filename VARCHAR(255),
            ADD COLUMN IF NOT EXISTS source_video_size BIGINT,
            ADD COLUMN IF NOT EXISTS source_video_content_type VARCHAR(100),
            ADD COLUMN IF NOT EXISTS source_video_updated_at TIMESTAMP WITHOUT TIME ZONE
        """))
        await conn.execute(text("""
            ALTER TABLE parts.search_history
            ADD COLUMN IF NOT EXISTS query_text VARCHAR(1000),
            ADD COLUMN IF NOT EXISTS query_image VARCHAR(1000)
        """))
        await conn.execute(text("""
            ALTER TABLE parts.search_history
            ADD COLUMN IF NOT EXISTS verify_status VARCHAR(50),
            ADD COLUMN IF NOT EXISTS verify_remark VARCHAR(500),
            ADD COLUMN IF NOT EXISTS verified_at TIMESTAMP WITHOUT TIME ZONE
        """))
        await conn.execute(text("""
            ALTER TABLE parts.search_history
            ADD COLUMN IF NOT EXISTS search_equipment VARCHAR(50)
        """))
        await conn.execute(text("""
            UPDATE parts.search_history
            SET verify_status = 'wrong'
            WHERE verify_status = 'partial'
        """))
        await conn.execute(text("""
            ALTER TABLE parts.reconstruction_records
            ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP WITHOUT TIME ZONE,
            ADD COLUMN IF NOT EXISTS elapsed_sec DOUBLE PRECISION
        """))
