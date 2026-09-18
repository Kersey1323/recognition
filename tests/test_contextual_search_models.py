import json
from datetime import datetime

from csrcqsf.models.orm.search_history import (
    SearchHistory,
    SearchParameters,
    SearchResults,
    SearchSnapshot,
)
from csrcqsf.modules.railway_parts.schemas.search import ContextualSearchRes


def test_search_history_exposes_previous_snapshot_and_revision_columns():
    assert "previous_search_snapshot" in SearchHistory.__table__.columns
    assert "search_revision" in SearchHistory.__table__.columns
    assert SearchHistory.__table__.columns["search_revision"].default.arg == 0
    assert str(SearchHistory.__table__.columns["search_revision"].server_default.arg) == "0"


def test_previous_search_snapshot_can_be_encoded_by_database_json_type():
    snapshot = SearchSnapshot(
        query_images=["query-images/previous.jpg"],
        parameters=SearchParameters(vehicle_batch="E11_CRH380A"),
        results=SearchResults(items=[]),
        searched_at=datetime(2026, 8, 20, 9, 30, 0),
    )

    column_type = SearchHistory.__table__.columns["previous_search_snapshot"].type
    bound_value = column_type.process_bind_param(snapshot, dialect=None)

    encoded = json.loads(json.dumps(bound_value))
    assert encoded["searched_at"] == "2026-08-20T09:30:00"


def test_search_parameters_with_source_time_can_be_encoded_by_database_json_type():
    parameters = SearchParameters(
        source_inquiry_id="current-inquiry",
        source_inquiry_time=datetime(2026, 3, 5, 10, 30, 26),
    )

    column_type = SearchHistory.__table__.columns["search_parameter"].type
    bound_value = column_type.process_bind_param(parameters, dialect=None)

    encoded = json.loads(json.dumps(bound_value))
    assert encoded["source_inquiry_id"] == "current-inquiry"
    assert encoded["source_inquiry_time"] == "2026-03-05T10:30:26"


def test_search_parameters_support_contextual_fields_and_default_to_siglip():
    parameters = SearchParameters()

    assert parameters.vehicle_batch is None
    assert parameters.item_name is None
    assert parameters.item_description is None
    assert parameters.train_no is None
    assert parameters.car_num is None
    assert parameters.subordinate_component is None
    assert parameters.search_mode == "siglip"


def test_contextual_search_response_keeps_one_history_id_and_two_windows():
    response = ContextualSearchRes(
        history_id="2048696242753638400",
        previous=None,
        current={
            "query_images": ["search-history/query-images/current.jpg"],
            "parameters": {"vehicle_batch": "SFE27"},
            "searched_at": "2026-08-18 10:18:23",
            "data": [],
        },
        message=None,
    )

    assert response.history_id == "2048696242753638400"
    assert response.previous is None
    assert response.current.parameters.vehicle_batch == "SFE27"
    assert response.current.parameters.search_mode == "siglip"
