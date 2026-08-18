import importlib.util
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "database"
    / "sync_sgo_inquiry_history_to_main_mysql.py"
)


def _load_sync_module():
    spec = importlib.util.spec_from_file_location(
        "sync_sgo_inquiry_history_to_main_mysql",
        SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_item_inquiry_history_model_is_loaded_by_main_db_migration():
    import csrcqsf.infra.db.main_db as main_db

    assert "csrcqsf.models.orm.item_inquiry_history" in main_db.MAIN_DB_MODEL_MODULES


def test_item_inquiry_history_model_matches_sync_contract():
    from csrcqsf.models.orm.item_inquiry_history import ItemInquiryHistory

    columns = ItemInquiryHistory.__table__.columns

    for name in (
        "item_id",
        "item_code",
        "inquiry_id",
        "inquiry_num",
        "vehicle_batch",
        "train_no",
        "car_num",
        "inquiry_item_name",
        "subordinate_component",
        "remark",
        "return_item_name",
        "return_item_code",
        "inquiry_time",
        "source",
    ):
        assert name in columns
    assert ItemInquiryHistory.__table__.name == "item_inquiry_history"


def test_source_row_maps_sgo_inquiry_and_return_fields_to_history_payload():
    sync = _load_sync_module()
    row = {
        "inquiry_id": "inq-1",
        "inquiry_num": "CX230001",
        "vehicle": "SFE27_CRH380A统",
        "train_no": "2777",
        "car_num": "01",
        "inquiry_item_name": "  盖板  ",
        "subordinate_component": "座椅",
        "remark": "01车座椅盖板",
        "return_item_name": "座椅中扶手盖板",
        "return_item_code": "19010001",
        "inquiry_time": "2023-05-18 15:26:35",
    }

    payload = sync.history_payload_from_source_row(row, item_id=101)

    assert payload == {
        "item_id": 101,
        "item_code": "19010001",
        "inquiry_id": "inq-1",
        "inquiry_num": "CX230001",
        "vehicle_batch": "SFE27",
        "vehicle": "SFE27_CRH380A统",
        "train_no": "2777",
        "car_num": "01",
        "inquiry_item_name": "盖板",
        "subordinate_component": "座椅",
        "remark": "01车座椅盖板",
        "return_item_name": "座椅中扶手盖板",
        "return_item_code": "19010001",
        "inquiry_time": "2023-05-18 15:26:35",
        "source": "sgo",
    }


def test_history_upsert_sql_uses_business_key_and_updates_mutable_context():
    sync = _load_sync_module()

    statement = sync.build_history_upsert_sql()
    update_clause = statement.split("ON DUPLICATE KEY UPDATE", 1)[1]

    assert "INSERT INTO `item_inquiry_history`" in statement
    for base_column in ("`id`", "`created_by`", "`updated_by`", "`time_created`", "`time_updated`"):
        assert base_column in statement
    assert "`inquiry_id`" in statement
    assert "`return_item_code`" in statement
    assert "`source`" in statement
    assert "ON DUPLICATE KEY UPDATE" in statement
    assert "VALUES(`" not in statement
    assert "`id` = new.`id`" not in update_clause
    assert "`time_created` = new.`time_created`" not in update_clause
    assert "`inquiry_id` = new.`inquiry_id`" not in update_clause
    assert "`return_item_code` = new.`return_item_code`" not in update_clause
    assert "`source` = new.`source`" not in update_clause
    assert "`vehicle_batch` = new.`vehicle_batch`" in statement
    assert "`time_updated` = CURRENT_TIMESTAMP" in statement
