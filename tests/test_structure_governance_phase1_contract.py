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


def test_legacy_root_compat_modules_are_removed_in_final_state():
    removed_paths = [
        "csrcqsf/app.py",
        "csrcqsf/settings.py",
        "csrcqsf/runtime.py",
        "csrcqsf/logger.py",
        "csrcqsf/scheduler.py",
        "csrcqsf/api_models.py",
    ]

    for relative_path in removed_paths:
        assert not Path(relative_path).exists(), relative_path


def test_legacy_data_and_model_client_compat_modules_are_removed_in_final_state():
    removed_paths = [
        "csrcqsf/data/__init__.py",
        "csrcqsf/data/main_db.py",
        "csrcqsf/data/mdpdb.py",
        "csrcqsf/data/minio.py",
        "csrcqsf/data/milvus.py",
        "csrcqsf/data/basis_api.py",
        "csrcqsf/biz/model_client.py",
    ]

    for relative_path in removed_paths:
        assert not Path(relative_path).exists(), relative_path


def test_legacy_pg_compat_module_removed_in_phase_eight():
    assert not Path("csrcqsf/data/pg.py").exists()
