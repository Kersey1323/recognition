import asyncio
from types import SimpleNamespace

from csrcqsf.infra.db import migration_runner


class FakeScalarResult:
    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values


class FakeResult:
    def __init__(self, values=None):
        self._values = values or []

    def scalars(self):
        return FakeScalarResult(self._values)

    def mappings(self):
        return FakeScalarResult(self._values)


class FakeConn:
    def __init__(self):
        self.executed = []
        self.applied_migrations = {}

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.executed.append((sql, params))
        if "SELECT version, checksum FROM schema_migrations" in sql:
            return FakeResult(
                [
                    {"version": version, "checksum": checksum}
                    for version, checksum in self.applied_migrations.items()
                ]
            )
        return FakeResult()


async def migration_a(conn):
    conn.executed.append(("migration_a", None))


async def migration_b(conn):
    conn.executed.append(("migration_b", None))


def test_run_pending_migrations_executes_in_version_order(monkeypatch):
    fake_conn = FakeConn()
    fake_migrations = [
        migration_runner.Migration("20260622_002", "b", "checksum-b", migration_b),
        migration_runner.Migration("20260622_001", "a", "checksum-a", migration_a),
    ]

    monkeypatch.setattr(migration_runner, "discover_migrations", lambda: fake_migrations)

    asyncio.run(migration_runner.run_pending_migrations(fake_conn))

    assert ("migration_a", None) in fake_conn.executed
    assert ("migration_b", None) in fake_conn.executed
    assert fake_conn.executed.index(("migration_a", None)) < fake_conn.executed.index(("migration_b", None))


def test_run_pending_migrations_skips_applied_versions(monkeypatch):
    fake_conn = FakeConn()
    fake_conn.applied_migrations["20260622_001"] = "checksum-a"
    fake_migrations = [
        migration_runner.Migration("20260622_001", "a", "checksum-a", migration_a),
        migration_runner.Migration("20260622_002", "b", "checksum-b", migration_b),
    ]

    monkeypatch.setattr(migration_runner, "discover_migrations", lambda: fake_migrations)

    asyncio.run(migration_runner.run_pending_migrations(fake_conn))

    assert ("migration_a", None) not in fake_conn.executed
    assert ("migration_b", None) in fake_conn.executed


def test_run_pending_migrations_rejects_changed_checksum(monkeypatch):
    fake_conn = FakeConn()
    fake_conn.applied_migrations["20260622_001"] = "old-checksum"
    fake_migrations = [
        migration_runner.Migration("20260622_001", "a", "checksum-a", migration_a),
    ]

    monkeypatch.setattr(migration_runner, "discover_migrations", lambda: fake_migrations)

    try:
        asyncio.run(migration_runner.run_pending_migrations(fake_conn))
    except RuntimeError as exc:
        assert "已执行迁移脚本内容发生变化" in str(exc)
    else:
        raise AssertionError("changed migration checksum should fail startup migration")


def test_inquiry_text_index_migration_adds_sgo_relation_columns():
    migration = __import__(
        "csrcqsf.infra.db.migrations.20260828_001_add_inquiry_text_index_tasks",
        fromlist=["upgrade"],
    )
    calls = []

    async def fake_ensure_column(_conn, table_name, column_name, definition):
        calls.append((table_name, column_name, definition))

    import csrcqsf.infra.db.main_db as main_db

    original = main_db._ensure_column
    main_db._ensure_column = fake_ensure_column
    try:
        asyncio.run(migration.upgrade(object()))
    finally:
        main_db._ensure_column = original

    assert calls == [
        (
            "sgo_sync_task",
            "semantic_index_task_id",
            "`semantic_index_task_id` VARCHAR(100) NULL",
        ),
        (
            "sgo_sync_task",
            "semantic_index_warning",
            "`semantic_index_warning` TEXT NULL",
        ),
    ]
