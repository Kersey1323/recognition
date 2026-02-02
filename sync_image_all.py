from csrcqsf.biz.sgo import SGOBiz
from anyio import run 

run(SGOBiz.sync_all_images)

