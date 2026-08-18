from csrcqsf.models.orm.search_history import SearchHistory, SearchParameters
from csrcqsf.modules.railway_parts.schemas.search import ContextualSearchRes


def test_search_history_exposes_previous_snapshot_and_revision_columns():
    assert "previous_search_snapshot" in SearchHistory.__table__.columns
    assert "search_revision" in SearchHistory.__table__.columns
    assert SearchHistory.__table__.columns["search_revision"].default.arg == 0
    assert str(SearchHistory.__table__.columns["search_revision"].server_default.arg) == "0"


def test_search_parameters_support_contextual_fields_and_default_to_siglip():
    parameters = SearchParameters()

    assert parameters.vehicle_batch is None
    assert parameters.item_name is None
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
