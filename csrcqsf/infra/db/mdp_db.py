
from csrcqsf.core.settings import ai_settings
from csrcqsf.infra.db.kingbase_dialect import register_kingbase_dialect
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


register_kingbase_dialect()

sgo_engine = create_async_engine(
    ai_settings.get_sgo_dsn(),
    echo=False,
    future=True,
    pool_pre_ping=True,
)


sgo_sessionLocal = async_sessionmaker(expire_on_commit=False,
                                  autoflush=False, bind=sgo_engine)



