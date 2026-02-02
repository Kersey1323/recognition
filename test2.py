from csrcqsf.biz.railwayparts.milvus import MilvusManager
from csrcqsf.biz.sgo import SGOBiz
from anyio import run

run(SGOBiz.resize_image)

