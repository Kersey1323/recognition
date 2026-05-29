
from bfrcommon.db import with_schema
from globals_vars import logger
from sqlalchemy import text
from csrcqsf.core.settings import ai_settings
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from anyio import to_thread
sgo_engine = create_async_engine(
    f'{ai_settings.get_sgo_dsn()}',
    echo=False,
    future=True,
)


sgo_sessionLocal = async_sessionmaker(expire_on_commit=False,
                                  autoflush=False, bind=sgo_engine)




