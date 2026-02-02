import os
from contextlib import asynccontextmanager
import time
import uuid
from anyio import CapacityLimiter
from anyio.lowlevel import RunVar
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from bfrcommon.doc_router import make_doc_router, doc_router
from bfrcommon.middlewares.response import DefaultResponse, catch_exceptions_middleware
from bfrcommon.middlewares.auth import add_process_time_header, auth_middleware


from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from .logger import logger
from .settings import make_sure_models
from .api_models import *
from csrcqsf.biz.segment import SegmentBiz
from fastapi import Request
from csrcqsf.services import *
from csrcqsf.data.pg import db_migrate
from csrcqsf.biz.sgo import SGOBiz
from csrcqsf.biz.railwayparts.milvus import MilvusManager
origins = [
    "*",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    #await make_sure_models()
    await db_migrate()
    await SegmentBiz.init()
    await MilvusManager.init_collection()
    SGOBiz.init()
    RunVar("_default_thread_limiter").set(CapacityLimiter(200))
    yield


app = FastAPI(docs_url=None, redoc_url=None,
              default_response_class=DefaultResponse, lifespan=lifespan, redirect_slashes=False)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    return JSONResponse(content={'status': 'fail', 'message': str(exc), 'requestID': str(uuid.uuid4()), 'datetime': int(time.time() * 1000)})

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.middleware('http')(catch_exceptions_middleware(logger=logger, limit=4))
app.middleware('http')(add_process_time_header(logger))

app.add_middleware(GZipMiddleware, minimum_size=1000)


swagger_static_url = os.environ.get('swagger')
if swagger_static_url is None:
    make_doc_router()
else:
    make_doc_router(swagger_static_url=swagger_static_url)


app.include_router(doc_router)
app.include_router(parts_router)
app.include_router(image_router)
app.include_router(sgo_router)
app.include_router(parts_docs_router)

@app.post("/segment/simple",tags=["deepseek"], summary='简单的图像物体提取', responses={
    200: {
        'model': SimpleSegmentRes
    }
})
async def simpe_segment(req:SimpleSegmentReq):
    res = SimpleSegmentRes()
    res.mask = await SegmentBiz.mask(req.file_url)
    return res