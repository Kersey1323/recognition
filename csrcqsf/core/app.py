"""
FastAPI 应用主入口
职责：应用初始化、中间件配置、路由注册
"""
from contextlib import asynccontextmanager
import asyncio
import time
import uuid
from anyio import CapacityLimiter
from anyio.lowlevel import RunVar
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from bfrcommon.middlewares.response import DefaultResponse, catch_exceptions_middleware
from bfrcommon.middlewares.auth import add_process_time_header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from csrcqsf.core.logging_config import logger
from csrcqsf.core.runtime import ensure_segment_model_enabled, segment_model_enabled
from csrcqsf.core.startup_logging import run_startup_step
from csrcqsf.modules.doc_parse.routes import parts_docs_router
from csrcqsf.modules.image.routes import image_router
from csrcqsf.modules.image.schemas import SimpleSegmentReq, SimpleSegmentRes
from csrcqsf.modules.image.services import SegmentBiz
from csrcqsf.modules.railway_parts.routes import asset_proxy_router, parts_router
from csrcqsf.modules.railway_parts.services.auto_index_scheduler import auto_index_scheduler
from csrcqsf.modules.railway_parts.services.parts_service import RailwayPartsManager
from csrcqsf.modules.sgo.routes import sgo_router
from csrcqsf.infra.db.main_db import db_migrate
from csrcqsf.models.orm.index_rebuild_task import recover_index_rebuild_tasks
from csrcqsf.models.orm.inquiry_text_index_task import recover_inquiry_text_index_tasks
from csrcqsf.models.orm.sgo_sync_task import recover_sgo_sync_tasks
from csrcqsf.infra.storage.minio import create_minio_buckets
from csrcqsf.modules.sgo.services import SGOBiz
from csrcqsf.modules.railway_parts.services.inquiry_text_index_task_manager import (
    inquiry_text_index_task_manager,
)
from csrcqsf.core.scheduler import register_main_async_loop
from csrcqsf.core.settings import (
    ai_settings,
    main_db_env_configured,
    main_db_database,
    milvus_env_configured,
    minio_endpoint,
    minio_env_configured,
    reconstruction_server_env_configured,
    sgo_database_name,
    sgo_database_type,
    sgo_env_configured,
)

API_PREFIX = ""

# 导入 scheduler 以启动定时任务（包括重建任务状态同步）

# CORS配置：允许所有来源
origins = [
    "*",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理

    启动时执行：
    1. 数据库迁移（创建表）
    2. 初始化SAM分割模型
    3. 初始化Milvus向量数据库集合
    4. 初始化SGO业务
    5. 设置线程池容量限制

    关闭时执行：
    - 清理资源（由yield后的代码处理）
    """
    register_main_async_loop(asyncio.get_running_loop())

    if main_db_env_configured():
        await run_startup_step(
            "主业务数据库迁移",
            db_migrate,
            logger=logger,
            details=(
                f"host={ai_settings.mysql.url}, port={ai_settings.mysql.port}, "
                f"database={main_db_database}"
            ),
        )
        await run_startup_step(
            "索引重建任务状态恢复",
            recover_index_rebuild_tasks,
            logger=logger,
        )
        await run_startup_step(
            "SGO 同步任务状态恢复",
            recover_sgo_sync_tasks,
            logger=logger,
        )
        await run_startup_step(
            "询码语义索引任务状态恢复",
            recover_inquiry_text_index_tasks,
            logger=logger,
        )
    else:
        logger.warning("未显式配置主业务库环境变量，跳过数据库迁移初始化")

    if minio_env_configured():
        await run_startup_step(
            "MinIO Bucket 初始化",
            create_minio_buckets,
            logger=logger,
            details=f"endpoint={minio_endpoint}",
        )
    else:
        logger.warning("未显式配置 MinIO 环境变量，跳过 MinIO bucket 初始化")

    if not milvus_env_configured():
        logger.warning("未显式配置 Milvus 环境变量，Milvus 相关能力保持跳过/惰性初始化")

    if not main_db_env_configured():
        logger.warning("主业务数据库未配置时，将无法记录和查询三维重构任务状态")

    if not sgo_env_configured():
        logger.warning("未显式配置 SGO 数据库环境变量，跳过 SGO 数据同步初始化")

    if not reconstruction_server_env_configured():
        logger.warning("重构服务未配置时将禁用三维重构能力，请显式设置 RECONSTRUCTION_SERVER_URL")

    if segment_model_enabled():
        await run_startup_step(
            "图像分割能力初始化",
            SegmentBiz.init,
            logger=logger,
        )
    if sgo_env_configured():
        await run_startup_step(
            "SGO 定时同步初始化",
            SGOBiz.init,
            logger=logger,
            details=(
                f"type={sgo_database_type}, host={ai_settings.sgo_host}, "
                f"port={ai_settings.sgo_port}, database={sgo_database_name}"
            ),
        )
    if (
        main_db_env_configured()
        and minio_env_configured()
        and milvus_env_configured()
    ):
        await run_startup_step(
            "待索引图片自动索引调度器初始化",
            lambda: auto_index_scheduler.start(
                RailwayPartsManager.rebuild_v2_index
            ),
            logger=logger,
        )
    else:
        logger.warning(
            "主业务库、MinIO 或 Milvus 配置不完整，跳过待索引图片自动索引调度器初始化"
        )
    if main_db_env_configured() and milvus_env_configured():
        await run_startup_step(
            "询码语义索引任务队列初始化",
            inquiry_text_index_task_manager.start_worker,
            logger=logger,
        )
    else:
        logger.warning("主业务库或 Milvus 配置不完整，跳过询码语义索引任务队列初始化")
    RunVar("_default_thread_limiter").set(CapacityLimiter(200))  # 线程池限制
    logger.info("模型推理已迁移至独立服务（MODEL_SERVICE_URL），本地不再加载模型")
    logger.info("应用启动初始化全部完成")
    try:
        yield
    finally:
        await auto_index_scheduler.stop()
        await inquiry_text_index_task_manager.stop_worker()


# 创建FastAPI应用实例
app = FastAPI(
    default_response_class=DefaultResponse,
    lifespan=lifespan,
    redirect_slashes=False,
    openapi_url=f"{API_PREFIX}/openapi.json",
)


# ============================================
# 异常处理器
# ============================================

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    """
    请求参数验证失败的异常处理器

    返回统一的错误响应格式
    """
    return JSONResponse(content={'status': 'fail', 'message': str(exc), 'requestID': str(uuid.uuid4()), 'datetime': int(time.time() * 1000)})


# ============================================
# 中间件配置
# ============================================

# CORS中间件：允许跨域请求
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 异常捕获中间件
app.middleware('http')(catch_exceptions_middleware(logger=logger, limit=4))

# 请求处理时间记录中间件
app.middleware('http')(add_process_time_header(logger))

# GZip压缩中间件：响应大于1000字节时启用压缩
app.add_middleware(GZipMiddleware, minimum_size=1000)


# 注释掉自定义doc_router，使用FastAPI默认的Swagger UI
# swagger_static_url = os.environ.get('swagger')
# if swagger_static_url is None:
#     # 使用Swagger官方CDN，避免依赖内部不可访问的静态文件服务器
#     swagger_static_url = "https://unpkg.com/swagger-ui-dist@5.9.0/"
# make_doc_router(swagger_static_url=swagger_static_url)


# ============================================
# 路由注册
# ============================================
app.include_router(parts_router, prefix=API_PREFIX)
app.include_router(asset_proxy_router, prefix=API_PREFIX)
app.include_router(sgo_router, prefix=API_PREFIX)
app.include_router(parts_docs_router, prefix=API_PREFIX)
app.include_router(image_router, prefix=API_PREFIX)

@app.get(f"{API_PREFIX}/health", tags=["platform"], summary="Kubernetes health probe")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "recognition"}

@app.post(f"{API_PREFIX}/segment/simple", tags=["算法-图像分割"], summary='简单的图像物体提取 (SAM)', responses={
    200: {
        'model': SimpleSegmentRes
    }
})
async def simpe_segment(req:SimpleSegmentReq):
    """
    使用 SAM (Segment Anything Model) 进行图像分割

    - 输入：图片URL
    - 输出：Base64编码的mask图片
    - 用途：快速提取物体轮廓
    """
    ensure_segment_model_enabled()
    res = SimpleSegmentRes()
    res.mask = await SegmentBiz.mask(req.file_url)
    return res
