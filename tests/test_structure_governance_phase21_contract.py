from pathlib import Path


def test_phase_twenty_one_legacy_root_and_data_wrappers_are_removed():
    expected_absent = [
        "csrcqsf/app.py",
        "csrcqsf/settings.py",
        "csrcqsf/runtime.py",
        "csrcqsf/logger.py",
        "csrcqsf/scheduler.py",
        "csrcqsf/api_models.py",
        "csrcqsf/data/__init__.py",
        "csrcqsf/data/basis_api.py",
        "csrcqsf/data/main_db.py",
        "csrcqsf/data/mdpdb.py",
        "csrcqsf/data/milvus.py",
        "csrcqsf/data/minio.py",
        "csrcqsf/biz/model_client.py",
    ]

    for relative_path in expected_absent:
        assert not Path(relative_path).exists(), relative_path


def test_phase_twenty_one_image_schemas_are_module_local():
    expected_fragments = {
        "csrcqsf/modules/image/schemas.py": (
            "class SimpleSegmentReq",
            "class SimpleSegmentRes",
            "class FrontOCRReq",
            "class OCRResult",
        ),
        "csrcqsf/core/app.py": (
            "from csrcqsf.modules.image.schemas import SimpleSegmentReq, SimpleSegmentRes",
        ),
        "csrcqsf/modules/image/routes.py": (
            "from csrcqsf.modules.image.schemas import FrontOCRReq",
        ),
        "csrcqsf/modules/image/services.py": (
            "from csrcqsf.modules.image.schemas import OCRResult, Point, PointAndText",
        ),
    }

    forbidden_fragment = "from csrcqsf.api_models import"

    for relative_path, required_fragments in expected_fragments.items():
        text = Path(relative_path).read_text(encoding="utf-8")
        for fragment in required_fragments:
            assert fragment in text, f"{relative_path} missing {fragment}"
        assert forbidden_fragment not in text, f"{relative_path} still imports legacy api_models"


def test_phase_twenty_one_repo_entrypoints_no_longer_import_legacy_root_or_data_paths():
    target_paths = [
        "csrcqsf/__main__.py",
        "tests/test_api_prefix.py",
        "tests/test_current_db.py",
        "tests/test_search_history_storage_config.py",
        "tests/test_reconstruction_config.py",
        "tests/test_reconstruction_scheduler.py",
        "scripts/testing/test_app_startup.py",
        "scripts/testing/test_config.py",
        "scripts/testing/test_scheduler.py",
        "scripts/testing/test_sync_task.py",
        "scripts/testing/test_sync_task_v2.py",
        "scripts/testing/check_running_tasks.py",
        "scripts/testing/feature_test.py",
        "scripts/testing/debug_model_paths.py",
        "scripts/database/fix_db_columns.py",
        "scripts/database/fix_item_info_v2_index_state.py",
        "scripts/minio/check_image_urls.py",
    ]

    forbidden_fragments = (
        "from csrcqsf.app import",
        "from csrcqsf.settings import",
        "from csrcqsf.runtime import",
        "from csrcqsf.logger import",
        "from csrcqsf.scheduler import",
        "from csrcqsf.data.",
    )

    for relative_path in target_paths:
        text = Path(relative_path).read_text(encoding="utf-8")
        for fragment in forbidden_fragments:
            assert fragment not in text, f"{relative_path} still imports {fragment}"

    main_text = Path("csrcqsf/__main__.py").read_text(encoding="utf-8")
    assert "from csrcqsf.core.app import app" in main_text
