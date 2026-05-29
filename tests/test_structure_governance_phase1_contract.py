from pathlib import Path


def test_core_and_infra_phase_one_modules_exist():
    expected_paths = [
        "csrcqsf/core/__init__.py",
        "csrcqsf/core/app.py",
        "csrcqsf/core/settings.py",
        "csrcqsf/core/runtime.py",
        "csrcqsf/core/logger.py",
        "csrcqsf/core/scheduler.py",
        "csrcqsf/infra/__init__.py",
        "csrcqsf/infra/db/__init__.py",
        "csrcqsf/infra/db/main_db.py",
        "csrcqsf/infra/db/mdp_db.py",
        "csrcqsf/infra/storage/__init__.py",
        "csrcqsf/infra/storage/minio.py",
        "csrcqsf/infra/vector_store/__init__.py",
        "csrcqsf/infra/vector_store/milvus.py",
        "csrcqsf/infra/external/__init__.py",
        "csrcqsf/infra/external/basis_api.py",
        "csrcqsf/infra/external/model_client.py",
    ]

    for relative_path in expected_paths:
        assert Path(relative_path).exists(), relative_path


def test_root_compat_modules_reference_core_implementations():
    expected_references = {
        "csrcqsf/app.py": "csrcqsf.core.app",
        "csrcqsf/settings.py": "csrcqsf.core.settings",
        "csrcqsf/runtime.py": "csrcqsf.core.runtime",
        "csrcqsf/logger.py": "csrcqsf.core.logger",
        "csrcqsf/scheduler.py": "csrcqsf.core.scheduler",
    }

    for relative_path, expected in expected_references.items():
        text = Path(relative_path).read_text(encoding="utf-8")
        assert expected in text, relative_path


def test_data_and_model_client_compat_modules_reference_infra_implementations():
    expected_references = {
        "csrcqsf/data/main_db.py": "csrcqsf.infra.db.main_db",
        "csrcqsf/data/mdpdb.py": "csrcqsf.infra.db.mdp_db",
        "csrcqsf/data/minio.py": "csrcqsf.infra.storage.minio",
        "csrcqsf/data/milvus.py": "csrcqsf.infra.vector_store.milvus",
        "csrcqsf/data/basis_api.py": "csrcqsf.infra.external.basis_api",
        "csrcqsf/biz/model_client.py": "csrcqsf.infra.external.model_client",
    }

    for relative_path, expected in expected_references.items():
        text = Path(relative_path).read_text(encoding="utf-8")
        assert expected in text, relative_path


def test_legacy_pg_compat_module_removed_in_phase_eight():
    assert not Path("csrcqsf/data/pg.py").exists()
