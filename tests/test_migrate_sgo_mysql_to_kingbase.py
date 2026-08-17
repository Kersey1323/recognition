import importlib.util
from pathlib import Path

from csrcqsf.models.orm.sgo_external import (
    SgoCodeInquiry,
    SgoCodeInquiryReturn,
    SgoMaterielFileImg,
    SgoMaterielMasterplate,
)


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
        "sgo_materiel_masterplate",
        "sgo_materiel_file_img",
    ]
    assert migration.TABLE_SPECS["sgo_code_inquiry"].column_names == tuple(
        column.name for column in SgoCodeInquiry.__table__.columns
    )
    assert migration.TABLE_SPECS["sgo_code_inquiry_return"].column_names == tuple(
        column.name for column in SgoCodeInquiryReturn.__table__.columns
    )
    assert migration.TABLE_SPECS["sgo_materiel_masterplate"].column_names == tuple(
        column.name for column in SgoMaterielMasterplate.__table__.columns
    )
    assert migration.TABLE_SPECS["sgo_materiel_file_img"].column_names == tuple(
        column.name for column in SgoMaterielFileImg.__table__.columns
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

    masterplate_ddl = migration.TABLE_SPECS["sgo_materiel_masterplate"].create_table_sql(
        "public"
    )
    assert '"id" VARCHAR(64) PRIMARY KEY' in masterplate_ddl
    assert '"MATNR" VARCHAR(12)' in masterplate_ddl
    assert '"picture_info" TEXT' in masterplate_ddl
    assert '"column_id" VARCHAR(255)' in masterplate_ddl


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


def test_migration_config_accepts_runtime_sgo_kingbase_environment(monkeypatch):
    migration = _load_migration_module()
    values = {
        "SGO_MYSQL_HOST": "mysql-host",
        "SGO_MYSQL_USER": "mysql-user",
        "SGO_MYSQL_PASSWORD": "mysql-password",
        "SGO_KINGBASE_HOST": "kingbase-host",
        "SGO_KINGBASE_PORT": "54321",
        "SGO_KINGBASE_USER": "system",
        "SGO_KINGBASE_PASSWORD": "kingbase-password",
        "SGO_KINGBASE_DATABASE": "mdpdb",
    }
    for name in (
        "KINGBASE_HOST",
        "KINGBASE_PORT",
        "KINGBASE_USER",
        "KINGBASE_PASSWORD",
        "KINGBASE_DATABASE",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    config = migration.load_config()

    assert config.target_host == "kingbase-host"
    assert config.target_port == 54321
    assert config.target_user == "system"
    assert config.target_password == "kingbase-password"
    assert config.target_database == "mdpdb"


def test_select_table_specs_limits_migration_scope():
    migration = _load_migration_module()

    selected = migration.select_table_specs("sgo_materiel_file_img")

    assert list(selected) == ["sgo_materiel_file_img"]
