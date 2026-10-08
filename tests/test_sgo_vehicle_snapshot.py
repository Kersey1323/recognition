import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from csrcqsf.models.orm.item import Items
from csrcqsf.models.orm.sgo_external import SgoMaterielVehicle
from csrcqsf.modules.sgo import services as sgo_services


def test_vehicle_batch_groups_direct_mappings_by_item_code():
    direct = [
        ("CODE-1", "vehicle-2", "sfe27", "车型二"),
        ("CODE-1", "vehicle-1", "SFE27", "车型一"),
        ("CODE-1", "vehicle-4", "SFE30", "车型四"),
        ("CODE-2", "vehicle-3", "SFE28", "车型三"),
    ]

    result = sgo_services._build_item_vehicle_batch(
        {"code-1": 101, "code-2": 102}, direct
    )

    assert result == {101: "SFE27,SFE30", 102: "SFE28"}


def test_item_info_exposes_vehicle_batch_column_instead_of_vehicle_info():
    assert "vehicle_batch" in Items.__table__.columns
    assert "vehicle_info" not in Items.__table__.columns


def test_vehicle_sync_updates_changed_items_and_removes_stale_batch():
    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def commit(self):
            return None

    states = [
        SimpleNamespace(id=101, item_code="CODE-1", vehicle_batch=None),
        SimpleNamespace(id=102, item_code="CODE-2", vehicle_batch="SFE28"),
        SimpleNamespace(id=103, item_code="CODE-3", vehicle_batch="STALE"),
    ]
    update = AsyncMock()
    with patch.object(sgo_services, "SessionLocal", side_effect=FakeSession), patch.object(
        sgo_services, "sgo_sessionLocal", side_effect=FakeSession
    ), patch.object(
        Items, "list_vehicle_sync_state", AsyncMock(return_value=states)
    ), patch.object(
        SgoMaterielVehicle, "list_item_vehicle_mappings",
        AsyncMock(return_value=[("CODE-1", "v1", "SFE27", "车型一"),
                                ("CODE-2", "v2", "SFE28", "车型二")]),
    ), patch.object(Items, "update_vehicle_batch", update):
        result = asyncio.run(sgo_services.SGOBiz.sync_parts_vehicle_batch())

    rows = [row for call in update.await_args_list for row in call.args[1]]
    assert [row["item_id"] for row in rows] == [101, 103]
    assert rows[0]["vehicle_batch"] == "SFE27"
    assert rows[1]["vehicle_batch"] is None
    assert result["vehicle_item_count"] == 2
    assert result["updated_vehicle_item_count"] == 2
