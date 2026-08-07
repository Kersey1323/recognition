import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np

from csrcqsf.modules.railway_parts.services import item_service


def test_get_image_from_oss_preserves_manual_upload_object_path():
    image_url = (
        "bfr-ai-files/manual-upload/1978381826303725568/20260618/"
        "2067490055592742912_66_001.jpg"
    )
    object_name = image_url.split("/", 1)[1]
    response = SimpleNamespace(
        status=200,
        data=b"image-bytes",
        close=MagicMock(),
        release_conn=MagicMock(),
    )
    minio_instance = SimpleNamespace(
        client=SimpleNamespace(get_object=MagicMock(return_value=response))
    )
    parse_minio_path = MagicMock(return_value=("bfr-ai-files", object_name))

    async def run_sync(func, *args):
        return func(*args)

    runtime = SimpleNamespace(
        _get_minio_helpers=lambda: (None, minio_instance, parse_minio_path),
        minio_bucket="bfr-ai-files",
        run_sync=run_sync,
        np=np,
        cv2=SimpleNamespace(
            IMREAD_COLOR=1,
            imdecode=MagicMock(return_value=np.zeros((2, 2, 3), dtype=np.uint8)),
        ),
    )
    manager = SimpleNamespace(resize_image=lambda image: image)

    asyncio.run(item_service.get_image_from_oss(manager, image_url, runtime=runtime))

    parse_minio_path.assert_called_once_with(
        image_url,
        default_bucket="bfr-ai-files",
    )
    minio_instance.client.get_object.assert_called_once_with(
        "bfr-ai-files",
        object_name,
    )
