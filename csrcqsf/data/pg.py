
from bfrcommon.db import with_schema
from csrcqsf.logger import logger
from sqlalchemy import text
from csrcqsf.settings import ai_settings
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from anyio import to_thread
engine = create_async_engine(
    f'{ai_settings.get_async_pg_dsn()}',
    echo=False,
    future=True,
)


SessionLocal = async_sessionmaker(expire_on_commit=False,
                                  autoflush=False, bind=engine)


Base = with_schema(schema_name='parts')


async def db_migrate():
    async with engine.begin() as conn:
        await conn.execute(text('CREATE SCHEMA IF NOT EXISTS "parts"'))
        await conn.run_sync(Base.metadata.create_all)
