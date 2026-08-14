import importlib.util
from pathlib import Path

from csrcqsf.models.orm.sgo_external import SgoCodeInquiry, SgoCodeInquiryReturn


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "database"
    / "migrate_sgo_mysql_to_kingbase.py"
)


def _load_migration_module():
    spec = importlib.util.spec_from_file_location("migrate_sgo_mysql_to_kingbase", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_table_specs_cover_all_runtime_orm_columns():
    migration = _load_migration_module()

    assert list(migration.TABLE_SPECS) == [
        "sgo_code_inquiry",
        "sgo_code_inquiry_return",
    ]
    assert migration.TABLE_SPECS["sgo_code_inquiry"].column_names == tuple(
        column.name for column in SgoCodeInquiry.__table__.columns
    )
    assert migration.TABLE_SPECS["sgo_code_inquiry_return"].column_names == tuple(
        column.name for column in SgoCodeInquiryReturn.__table__.columns
    )


def test_kingbase_ddl_preserves_keys_and_materializes_mysql_computed_column():
    migration = _load_migration_module()

    inquiry_ddl = migration.TABLE_SPECS["sgo_code_inquiry"].create_table_sql("public")
    return_ddl = migration.TABLE_SPECS["sgo_code_inquiry_return"].create_table_sql("public")

    assert '"id" VARCHAR(64) PRIMARY KEY' in inquiry_ddl
    assert '"sub_creater_org_code" VARCHAR(4)' in inquiry_ddl
    assert "GENERATED" not in inquiry_ddl
    assert '"submission_date" DATE' in inquiry_ddl
    assert '"create_time" TIMESTAMP' in inquiry_ddl
    assert '"id" VARCHAR(64) PRIMARY KEY' in return_ddl
    assert '"item_code" VARCHAR(50)' in return_ddl


def test_insert_sql_uses_all_columns_and_parameter_placeholders():
    migration = _load_migration_module()
    table = migration.TABLE_SPECS["sgo_code_inquiry_return"]

    sql = table.insert_sql("public")

    assert sql.startswith('INSERT INTO "public"."sgo_code_inquiry_return"')
    assert sql.count("%s") == len(table.columns)
    assert '"inquiry_id"' in sql
    assert '"item_code"' in sql


def test_source_row_values_support_streaming_tuple_rows():
    migration = _load_migration_module()

    assert migration._source_row_values(("1", "CX001"), ("id", "inquiry_num")) == (
        "1",
        "CX001",
    )


def test_source_row_values_support_dict_rows():
    migration = _load_migration_module()

    assert migration._source_row_values(
        {"inquiry_num": "CX001", "id": "1"},
        ("id", "inquiry_num"),
    ) == ("1", "CX001")


def test_source_row_values_reject_unexpected_tuple_width():
    migration = _load_migration_module()

    try:
        migration._source_row_values(("1",), ("id", "inquiry_num"))
    except RuntimeError as exc:
        assert "源数据列数不匹配" in str(exc)
    else:
        raise AssertionError("列数不匹配时应拒绝迁移")
