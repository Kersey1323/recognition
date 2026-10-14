import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import Column, DateTime, Integer, MetaData, Table, create_engine, insert

from csrcqsf.models.orm import item as item_module
from csrcqsf.models.orm.item import Items


def test_list_items_orders_latest_index_updates_first_with_stable_pagination():
    engine = create_engine("sqlite://")
    table = Table("item_info", MetaData(), Column("id", Integer, primary_key=True),
                  Column("time_created", DateTime), Column("v2_index_updated_at", DateTime))
    table.create(engine)
    with engine.begin() as connection:
        connection.execute(insert(table), [
            {"id": 10, "time_created": datetime(2026, 1, 1), "v2_index_updated_at": datetime(2026, 10, 14)},
            {"id": 20, "time_created": datetime(2026, 10, 13), "v2_index_updated_at": datetime(2026, 10, 12)},
            {"id": 30, "time_created": datetime(2026, 1, 2), "v2_index_updated_at": datetime(2026, 10, 12)},
            {"id": 40, "time_created": datetime(2026, 10, 14), "v2_index_updated_at": None},
        ])
        for page, expected in [(1, [10, 30]), (2, [20, 40])]:
            session = AsyncMock()
            session.scalars.return_value = SimpleNamespace(all=lambda: [])
            with patch.object(item_module, "async_get_count", AsyncMock(return_value=4)):
                asyncio.run(Items.list_items(session, page=page, per_page=2))
            statement = session.scalars.await_args.args[0]
            # 直接执行列表查询的排序和分页，覆盖更新时间相同及未建立索引的配件。
            ids = connection.execute(statement.with_only_columns(Items.id)).scalars().all()
            assert ids == expected
    engine.dispose()
