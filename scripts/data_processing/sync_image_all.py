from anyio import run

from csrcqsf.modules.sgo.services import SGOBiz

run(SGOBiz.sync_all_images)
