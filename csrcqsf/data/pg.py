"""
数据访问层 - PostgreSQL数据库连接
职责：数据库连接管理、会话管理、Schema初始化
注意：此层不包含具体的业务逻辑，仅提供数据库基础设施
"""

from bfrcommon.db import with_schema
from globals_vars import logger
from sqlalchemy import text
from csrcqsf.settings import ai_settings
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from anyio import to_thread

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
