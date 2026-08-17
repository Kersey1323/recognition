import asyncio
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from PIL import Image

from csrcqsf.models.orm.sgo import SegmentedImage
from csrcqsf.modules.railway_parts.services.segmented_image_service import (
    SegmentedImageService,
)
from csrcqsf.modules.sgo.schemas import SegmentStatus


def test_segmented_image_latest_success_query_filters_source_and_orders_desc():
    session = AsyncMock()
    scalar_result = MagicMock()
    scalar_result.first.return_value = None
    session.scalars.return_value = scalar_result

    asyncio.run(SegmentedImage.get_latest_success(session, 101, 9001))

    stmt = session.scalars.await_args.args[0]
    sql = str(stmt)
    assert "segmented_image_info.item_id" in sql
    assert "segmented_image_info.source_image_id" in sql
    assert "segmented_image_info.status" in sql
    assert "segmented_image_info.id DESC" in sql


def test_persist_success_uploads_png_and_updates_segmentation_record():
    session = AsyncMock()
    session.add = MagicMock()
    minio_client = SimpleNamespace(put_object=MagicMock())
    service = SegmentedImageService(
        session,
        minio_client=minio_client,
        bucket="bfr-ai-files",
        id_factory=lambda: 7001,
    )

    record = asyncio.run(
        service.persist_success(
            item_id=101,
            source_image_id=9001,
            source_image_url="bfr-ai-files/source.jpg",
            image=Image.new("RGB", (3, 2), "black"),
            bbox=(1, 2, 3, 4),
            mask_area=8,
        )
    )

    assert record.id == 7001
    assert record.status == SegmentStatus.SUCCESS
    assert record.segmented_image_url == (
        "bfr-ai-files/segmented/101/9001/7001.png"
    )
    assert (record.bbox_x, record.bbox_y, record.bbox_w, record.bbox_h) == (
        1,
        2,
        3,
        4,
    )
    put_args = minio_client.put_object.call_args.args
    assert put_args[:2] == (
        "bfr-ai-files",
        "segmented/101/9001/7001.png",
    )
    stream, length = put_args[2:4]
    assert length > 0
    assert stream.read().startswith(b"\x89PNG")
    assert session.add.call_count == 1
    assert session.flush.await_count == 2


def test_remove_source_artifacts_deletes_all_objects_then_database_rows():
    session = AsyncMock()
    records = [
        SimpleNamespace(
            segmented_image_url="bfr-ai-files/segmented/101/9001/a.png"
        ),
        SimpleNamespace(
            segmented_image_url="bfr-ai-files/segmented/101/9001/b.png"
        ),
        SimpleNamespace(segmented_image_url=None),
    ]
    scalar_result = MagicMock()
    scalar_result.all.return_value = records
    session.scalars.return_value = scalar_result
    minio_client = SimpleNamespace(remove_object=MagicMock())
    service = SegmentedImageService(
        session,
        minio_client=minio_client,
        bucket="bfr-ai-files",
    )

    deleted = asyncio.run(service.remove_source_artifacts(101, 9001))

    assert deleted == 3
    assert minio_client.remove_object.call_args_list == [
        (("bfr-ai-files", "segmented/101/9001/a.png"),),
        (("bfr-ai-files", "segmented/101/9001/b.png"),),
    ]
    stmt = session.execute.await_args.args[0]
    sql = str(stmt)
    assert "segmented_image_info.item_id" in sql
    assert "segmented_image_info.source_image_id" in sql


def test_load_image_reads_segmented_png_and_releases_minio_response():
    stream = io.BytesIO()
    Image.new("RGB", (4, 3), "black").save(stream, format="PNG")
    response = SimpleNamespace(
        read=MagicMock(return_value=stream.getvalue()),
        close=MagicMock(),
        release_conn=MagicMock(),
    )
    minio_client = SimpleNamespace(get_object=MagicMock(return_value=response))
    service = SegmentedImageService(
        AsyncMock(),
        minio_client=minio_client,
        bucket="bfr-ai-files",
    )
    record = SimpleNamespace(
        id=7001,
        segmented_image_url="bfr-ai-files/segmented/101/9001/a.png",
    )

    image = asyncio.run(service.load_image(record))

    assert image.size == (4, 3)
    minio_client.get_object.assert_called_once_with(
        "bfr-ai-files",
        "segmented/101/9001/a.png",
    )
    response.close.assert_called_once()
    response.release_conn.assert_called_once()
