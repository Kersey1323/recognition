import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch


class _AsyncBegin:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_db_migrate_no_longer_uses_postgres_schema_sql():
    text = Path("csrcqsf/infra/db/main_db.py").read_text(encoding="utf-8")

    assert "CREATE SCHEMA IF NOT EXISTS" not in text
    assert "JSONB" not in text
    assert "TIMESTAMP WITHOUT TIME ZONE" not in text


def test_db_migrate_contains_column_probe_strategy():
    text = Path("csrcqsf/infra/db/main_db.py").read_text(encoding="utf-8")

    assert "information_schema.columns" in text or "inspect(" in text


def test_db_migrate_loads_reconstruction_upload_model():
    text = Path("csrcqsf/infra/db/main_db.py").read_text(encoding="utf-8")

    assert '"csrcqsf.models.orm.reconstruction_upload"' in text


def test_load_main_db_models_imports_all_main_db_model_modules():
    import csrcqsf.infra.db.main_db as pg_module

    imported = []

    def _fake_import(name):
        imported.append(name)
        return SimpleNamespace(__name__=name)

    with patch("csrcqsf.infra.db.main_db.importlib.import_module", side_effect=_fake_import):
        pg_module.load_main_db_models()

    assert imported == [
        "csrcqsf.models.orm.files",
        "csrcqsf.models.orm.item",
        "csrcqsf.models.orm.reconstruction",
        "csrcqsf.models.orm.reconstruction_upload",
        "csrcqsf.models.orm.search_history",
        "csrcqsf.models.orm.sgo",
    ]


def test_ensure_main_database_exists_creates_database_when_missing():
    import csrcqsf.infra.db.main_db as pg_module

    fake_conn = AsyncMock()
    fake_engine = SimpleNamespace(
        begin=lambda: _AsyncBegin(fake_conn),
        dispose=AsyncMock(),
    )

    with patch("csrcqsf.infra.db.main_db.create_async_engine", return_value=fake_engine) as create_engine_mock, \
         patch.object(type(pg_module.ai_settings), "get_async_main_db_dsn", return_value="mysql+asyncmy://root:pwd@127.0.0.1:3306/coronavirusdb"), \
         patch.object(pg_module, "main_db_database", "coronavirusdb"):
        asyncio.run(pg_module.ensure_main_database_exists())

    create_engine_mock.assert_called_once()
    executed_sql = str(fake_conn.execute.await_args.args[0])
    assert "CREATE DATABASE IF NOT EXISTS" in executed_sql
    assert "coronavirusdb" in executed_sql
    fake_engine.dispose.assert_awaited_once()


def test_db_migrate_bootstraps_database_then_creates_all_tables():
    import csrcqsf.infra.db.main_db as pg_module

    fake_conn = AsyncMock()
    fake_conn.run_sync = AsyncMock()
    fake_engine = SimpleNamespace(begin=lambda: _AsyncBegin(fake_conn))

    with patch.object(pg_module, "engine", fake_engine), \
         patch("csrcqsf.infra.db.main_db.ensure_main_database_exists", AsyncMock()) as ensure_db_mock, \
         patch("csrcqsf.infra.db.main_db.load_main_db_models") as load_models_mock, \
         patch("csrcqsf.infra.db.main_db._ensure_item_info_columns", AsyncMock()) as ensure_item_mock, \
         patch("csrcqsf.infra.db.main_db._ensure_search_history_columns", AsyncMock()) as ensure_history_mock, \
         patch("csrcqsf.infra.db.main_db._ensure_reconstruction_columns", AsyncMock()) as ensure_reconstruction_mock:
        asyncio.run(pg_module.db_migrate())

    ensure_db_mock.assert_awaited_once()
    load_models_mock.assert_called_once_with()
    assert fake_conn.run_sync.await_args_list == [
        call(pg_module.Base.metadata.create_all),
        call(pg_module.PlainBase.metadata.create_all),
    ]
    ensure_item_mock.assert_awaited_once_with(fake_conn)
    ensure_history_mock.assert_awaited_once_with(fake_conn)
    ensure_reconstruction_mock.assert_awaited_once_with(fake_conn)


def test_db_migrate_contains_reconstruction_upload_column_backfills():
    text = Path("csrcqsf/infra/db/main_db.py").read_text(encoding="utf-8")

    assert '"reconstruction_video_upload_session"' in text
    assert '"storage_mode"' in text
    assert '"remote_upload_id"' in text
