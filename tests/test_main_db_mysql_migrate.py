from pathlib import Path


def test_db_migrate_no_longer_uses_postgres_schema_sql():
    text = Path("csrcqsf/data/pg.py").read_text(encoding="utf-8")

    assert "CREATE SCHEMA IF NOT EXISTS" not in text
    assert "JSONB" not in text
    assert "TIMESTAMP WITHOUT TIME ZONE" not in text


def test_db_migrate_contains_column_probe_strategy():
    text = Path("csrcqsf/data/pg.py").read_text(encoding="utf-8")

    assert "information_schema.columns" in text or "inspect(" in text


def test_db_migrate_loads_reconstruction_upload_model():
    text = Path("csrcqsf/data/pg.py").read_text(encoding="utf-8")

    assert "ReconstructionVideoUploadSession" in text
