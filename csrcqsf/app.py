"""
FastAPI 应用主入口
职责：应用初始化、中间件配置、路由注册
"""
from contextlib import asynccontextmanager
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
from globals_vars import logger
from .api_models import *
from csrcqsf.biz.segment import SegmentBiz
from csrcqsf.runtime import ensure_segment_model_enabled, segment_model_enabled
from csrcqsf.services import *
from csrcqsf.data.pg import db_migrate
from csrcqsf.data.minio import create_minio_buckets
from csrcqsf.biz.sgo import SGOBiz
from csrcqsf.settings import (
    main_db_env_configured,
    milvus_env_configured,
    minio_env_configured,
    redis_env_configured,
)

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
    if main_db_env_configured():
        await db_migrate()  # 数据库迁移
    else:
        logger.warning("未显式配置主业务库环境变量，跳过数据库迁移初始化")

    if minio_env_configured():
        await create_minio_buckets()  # 初始化对象存储 bucket
    else:
        logger.warning("未显式配置 MinIO 环境变量，跳过 MinIO bucket 初始化")

    if not milvus_env_configured():
        logger.warning("未显式配置 Milvus 环境变量，Milvus 相关能力保持跳过/惰性初始化")

    if not redis_env_configured():
        logger.warning("未显式配置 Redis/Celery 环境变量，重建状态同步任务将按需跳过")

    if segment_model_enabled():
        await SegmentBiz.init()  # 初始化SAM模型
    # SGOBiz.init()  # 初始化SGO业务
    RunVar("_default_thread_limiter").set(CapacityLimiter(200))  # 线程池限制
    yield


# 创建FastAPI应用实例
app = FastAPI(default_response_class=DefaultResponse, lifespan=lifespan, redirect_slashes=False,openapi_url="/recognition_api/openapi.json")


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
app.include_router(parts_router)
app.include_router(sgo_router)
app.include_router(parts_docs_router)
app.include_router(image_router)

@app.post("/segment/simple", tags=["算法-图像分割"], summary='简单的图像物体提取 (SAM)', responses={
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
