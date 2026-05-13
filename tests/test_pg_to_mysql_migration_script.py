from pathlib import Path
import importlib.util


def _load_migration_module():
    module_path = Path("scripts/database/migrate_main_db_pg_to_mysql.py")
    spec = importlib.util.spec_from_file_location("main_db_migration_script", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_pg_to_mysql_migration_script_exists_with_core_tables():
    text = Path("scripts/database/migrate_main_db_pg_to_mysql.py").read_text(
        encoding="utf-8"
    )

    assert "item_info" in text
    assert "item_relation" in text
    assert "search_history" in text
    assert "search_review_ticket" in text
    assert "reconstruction_records" in text


def test_item_info_rows_fill_mysql_required_defaults():
    module = _load_migration_module()

    row = {
        "item_type": None,
        "parent_num": None,
        "son_num": None,
        "image_index_num": None,
        "feature_index_num": None,
        "item_code": "code-1",
    }

    normalized = module._normalize_row_for_table("item_info", row)

    assert normalized["item_type"] == "real"
    assert normalized["parent_num"] == 0
    assert normalized["son_num"] == 0
    assert normalized["image_index_num"] == 0
    assert normalized["feature_index_num"] == 0
