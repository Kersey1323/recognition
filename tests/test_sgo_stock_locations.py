import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from csrcqsf.models.orm.item import Items
from csrcqsf.modules.sgo import services


def test_stock_snapshot_preserves_distinct_locations_and_deduplicates_batches():
    build = getattr(services, "build_stock_locations", None)
    assert build is not None, "stock snapshot builder has not been added"
    rows = [
        (" CODE-1 ", "JS00", "青岛寄售库", "DF050205"),
        ("code-1", "JS00", "青岛寄售库", "DF050201"),
        ("CODE-1", "JS00", "青岛寄售库", "DF050205"),
        ("CODE-1", "2514", "备件销售-销售库1", "DF0101001"),
        ("CODE-1", "JS00", "青岛寄售库", "  "),
        ("CODE-2", "JS00", "青岛寄售库", "DF150207"),
    ]
    snapshot = build({"code-1": 101, "code-2": 102}, rows)
    assert snapshot[101]["LGORT"] == "2514,JS00"
    assert snapshot[101]["GRARD"] == "DF0101001,DF050201,DF050205"
    assert snapshot[101]["stock_locations"] == [
        {"LGORT": "2514", "LGORTD": "备件销售-销售库1", "GRARD": "DF0101001"},
        {"LGORT": "JS00", "LGORTD": "青岛寄售库", "GRARD": "DF050201"},
        {"LGORT": "JS00", "LGORTD": "青岛寄售库", "GRARD": "DF050205"},
    ]
    assert snapshot[102]["GRARD"] == "DF150207"


def test_stock_sync_clears_stale_positions_and_does_not_touch_video():
    method = getattr(services.SGOBiz, "sync_parts_stock_locations", None)
    assert method is not None, "stock refresh has not been added"
    from csrcqsf.models.orm.sgo_stock import WmsStockDetail

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def commit(self):
            pass

    states = [
        SimpleNamespace(id=101, item_code="CODE-1", LGORT=None, LGORTD=None,
                        GRARD=None, stock_locations=None),
        SimpleNamespace(id=102, item_code="CODE-2", LGORT="JS00", LGORTD="青岛寄售库",
                        GRARD="OLD", stock_locations=[{"GRARD": "OLD"}]),
        SimpleNamespace(id=103, item_code="CODE-3", LGORT=None, LGORTD=None,
                        GRARD=None, stock_locations=[]),
    ]
    update = AsyncMock()
    with patch.object(services, "SessionLocal", side_effect=Session), patch.object(
        services, "sgo_sessionLocal", side_effect=Session
    ), patch.object(Items, "list_stock_sync_state", AsyncMock(return_value=states)), patch.object(
        WmsStockDetail, "list_available_locations",
        AsyncMock(return_value=[("CODE-1", "JS00", "青岛寄售库", "DF050201")]),
    ), patch.object(Items, "update_stock_locations", update):
        result = asyncio.run(method())
    changed = [r for call in update.await_args_list for r in call.args[1]]
    assert [r["item_id"] for r in changed] == [101, 102]
    assert changed[0]["GRARD"] == "DF050201"
    assert changed[1]["LGORT"] is None
    assert changed[1]["stock_locations"] == []
    assert all("source_video_path" not in r for r in changed)
    assert result == {"stock_item_count": 1, "updated_stock_item_count": 2}


def test_stock_location_query_ignores_quantity_and_excludes_other_warehouses():
    from csrcqsf.models.orm import sgo_external
    assert "wms_stock_detail" in sgo_external.Base.metadata.tables, "stock ORM not added"
    from csrcqsf.models.orm.sgo_stock import WmsStockDetail
    from sqlalchemy.dialects import postgresql

    session = AsyncMock()
    session.execute.return_value = SimpleNamespace(all=lambda: [])
    asyncio.run(WmsStockDetail.list_available_locations(session))
    sql = str(session.execute.await_args.args[0].compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    ))
    assert '"CLABS"' not in sql
    assert '"WERKS" = \'3100\'' in sql
    assert "('2514', 'JS00')" in sql
    assert 'trim(wms_stock_detail."GRARD") !=' in sql

