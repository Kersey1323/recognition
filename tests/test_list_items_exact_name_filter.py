"""list_items 的配件名称精确筛选（item_name）契约测试。"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy.dialects import mysql

from csrcqsf.models.orm import item as item_module
from csrcqsf.models.orm.item import Items


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


def test_exact_item_name_filter_ignores_case_and_surrounding_spaces():
    sql = _compiled_statement(item_name="  Rubber Sleeve  ")

    assert "lower(trim(item_info.item_name)) = 'rubber sleeve'" in sql
    # 精确筛选不能退化成模糊匹配。
    assert "LIKE" not in sql


def test_blank_item_name_does_not_add_exact_filter():
    assert "lower(trim(item_info.item_name))" not in _compiled_statement(item_name="   ")
    assert "lower(trim(item_info.item_name))" not in _compiled_statement(item_name=None)


def test_exact_item_name_is_combined_with_fuzzy_keyword_query():
    sql = _compiled_statement(item_name="司机室", query="司机")

    assert "lower(trim(item_info.item_name)) = '司机室'" in sql
    # query 仍然是原有的模糊匹配（名称或编码）。
    assert "item_info.item_name LIKE" in sql
    assert "item_info.item_code LIKE" in sql


def test_fuzzy_query_alone_stays_unchanged():
    sql = _compiled_statement(query="司机")

    assert "lower(trim(item_info.item_name))" not in sql
    assert "item_info.item_name LIKE" in sql
    assert "item_info.item_code LIKE" in sql
