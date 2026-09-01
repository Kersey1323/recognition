
from csrcqsf.core.settings import ai_settings
from csrcqsf.infra.db.kingbase_dialect import register_kingbase_dialect
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


# 在创建 SGO 引擎前注册自定义方言，使同一访问层兼容甲方 Kingbase 和本地环境。
register_kingbase_dialect()

# SGO 数据库只读访问仍启用连接探活，避免长期任务复用已断开的连接。
sgo_engine = create_async_engine(
    ai_settings.get_sgo_dsn(),
    echo=False,
    future=True,
    pool_pre_ping=True,
)


sgo_sessionLocal = async_sessionmaker(expire_on_commit=False,
                                  autoflush=False, bind=sgo_engine)


