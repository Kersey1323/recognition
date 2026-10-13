import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import mysql
from csrcqsf.models.orm import item as item_module
from csrcqsf.models.orm.item import Items
from csrcqsf.modules.railway_parts.schemas._parts_api_models import ListItemReq, ListItem


def test_stock_fields_are_persisted_and_exposed_by_list():
    assert {"LGORT", "LGORTD", "GRARD", "stock_locations"} <= set(Items.__table__.columns.keys())
    assert {"LGORT", "LGORTD", "GRARD"} <= set(ListItemReq.__fields__)
    assert {"LGORT", "LGORTD", "GRARD", "stock_locations"} <= set(ListItem.__fields__)


def test_list_stock_filters_match_one_location_object():
    assert "stock_locations" in Items.__table__.columns, "stock columns not added"
    captured = {}
    session = AsyncMock()
    session.scalars.return_value = SimpleNamespace(all=lambda: [])

    async def count(_session, stmt):
        captured["stmt"] = stmt
        return 0

    with patch.object(item_module, "async_get_count", AsyncMock(side_effect=count)):
        asyncio.run(Items.list_items(session, LGORT=" JS00 ", GRARD=" DF050205 "))
    compiled = captured["stmt"].compile(dialect=mysql.dialect())
    sql = str(compiled)
    assert sql.count("json_contains(") == 1
    assert "json_object(" in sql
    assert "JS00" in compiled.params.values()
    assert "DF050205" in compiled.params.values()
    assert "find_in_set" not in sql


def test_blank_stock_filters_do_not_filter_list():
    assert "stock_locations" in Items.__table__.columns, "stock columns not added"
    session = AsyncMock()
    session.scalars.return_value = SimpleNamespace(all=lambda: [])
    with patch.object(item_module, "async_get_count", AsyncMock(return_value=0)):
        asyncio.run(Items.list_items(session, LGORT="  ", LGORTD=None, GRARD=""))
    assert "json_contains(" not in str(session.scalars.await_args.args[0])


@pytest.mark.parametrize("value", ["01", "1", 1, " 01 "])
def test_rack_number_is_normalized_to_two_digits(value):
    req = ListItemReq(page=1, pageSize=10, rack_no=value)
    assert getattr(req, "rack_no", None) == "01"


@pytest.mark.parametrize("value", ["DF01", "100", "-1", "1.5", True])
def test_invalid_rack_number_is_rejected(value):
    with pytest.raises(ValidationError):
        ListItemReq(page=1, pageSize=10, rack_no=value)


def test_rack_filter_matches_warehouse_and_rack_in_one_position():
    captured = {}
    session = AsyncMock()
    session.scalars.return_value = SimpleNamespace(all=lambda: [])

    async def count(_session, stmt):
        captured["stmt"] = stmt
        return 0

    with patch.object(item_module, "async_get_count", AsyncMock(side_effect=count)):
        asyncio.run(Items.list_items(session, rack_no="01", LGORT="JS00", GRARD="DF0101001"))
    compiled = captured["stmt"].compile(dialect=mysql.dialect())
    sql = str(compiled)
    assert "IN (SELECT stock_items.id" in sql
    assert "json_table(stock_items.stock_locations" in sql
    assert "stock_location.`LGORT` =" in sql
    assert "stock_location.`GRARD` REGEXP" in sql
    assert "stock_location.`GRARD` =" in sql
    assert "^[^0-9]*01[0-9]{4,5}$" in compiled.params.values()
    assert "JS00" in compiled.params.values()
    assert "DF0101001" in compiled.params.values()


def test_empty_rack_number_does_not_add_rack_filter():
    session = AsyncMock()
    session.scalars.return_value = SimpleNamespace(all=lambda: [])
    with patch.object(item_module, "async_get_count", AsyncMock(return_value=0)):
        asyncio.run(Items.list_items(session, rack_no="  "))
    assert "json_table(" not in str(session.scalars.await_args.args[0])
