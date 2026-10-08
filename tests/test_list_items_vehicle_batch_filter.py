"""list_items 的车型（vehicle_batch）精确筛选契约测试。"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy.dialects import mysql

from csrcqsf.models.orm import item as item_module
from csrcqsf.models.orm.item import Items

VEHICLE_SQL = "find_in_set('SFE27', item_info.vehicle_batch) > 0"


def _compiled_statement(**kwargs) -> str:
    """捕获 list_items 生成的 SQL，用 MySQL 方言渲染成可断言的字符串。"""
    captured = {}
    session = AsyncMock()
    session.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: []))

    async def _capture(_session, stmt):
        captured["stmt"] = stmt
        return 0

    async def _run():
        with patch.object(
            item_module,
            "async_get_count",
            new=AsyncMock(side_effect=_capture),
        ):
            await Items.list_items(session, **kwargs)

    asyncio.run(_run())
    return str(
        captured["stmt"].compile(
            dialect=mysql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_vehicle_batch_filter_matches_persisted_item_vehicle_batch():
    sql = _compiled_statement(vehicle_batch="SFE27")

    assert VEHICLE_SQL in sql
    assert "item_inquiry_history" not in sql


def test_vehicle_batch_filter_normalizes_case_and_surrounding_spaces():
    sql = _compiled_statement(vehicle_batch="  sfe27  ")

    assert VEHICLE_SQL in sql


def test_blank_vehicle_batch_does_not_add_vehicle_filter():
    assert "find_in_set" not in _compiled_statement(
        vehicle_batch="   "
    )
    assert "find_in_set" not in _compiled_statement(
        vehicle_batch=None
    )


def test_vehicle_batch_is_combined_with_name_and_keyword_filters():
    sql = _compiled_statement(vehicle_batch="SFE27", item_name="司机室", query="司机")

    assert VEHICLE_SQL in sql
    assert "lower(trim(item_info.item_name)) = '司机室'" in sql
    assert "item_info.item_name LIKE" in sql
    assert "item_info.item_code LIKE" in sql
