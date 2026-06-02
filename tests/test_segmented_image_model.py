import asyncio
from unittest.mock import AsyncMock

from csrcqsf.models.orm.sgo import SegmentedImage


def test_segmented_image_table_matches_runtime_columns():
    assert list(SegmentedImage.__table__.columns.keys()) == [
        "item_id",
        "source_image_id",
        "source_image_url",
        "segmented_image_url",
        "status",
        "mask_area",
        "bbox_x",
        "bbox_y",
        "bbox_w",
        "bbox_h",
        "is_indexed",
        "error_message",
        "id",
    ]


def test_segmented_image_list_by_item_id_orders_by_id_desc():
    session = AsyncMock()

    asyncio.run(SegmentedImage.list_by_item_id(session, 123))

    stmt = session.scalars.await_args.args[0]
    sql = str(stmt)
    assert "segmented_image_info.id DESC" in sql
    assert "time_created" not in sql
