from pathlib import Path


def test_phase_six_new_module_route_entrypoints_exist():
    expected_paths = [
        "csrcqsf/modules/sgo/routes.py",
        "csrcqsf/modules/doc_parse/__init__.py",
        "csrcqsf/modules/doc_parse/routes.py",
        "csrcqsf/modules/image/__init__.py",
        "csrcqsf/modules/image/routes.py",
    ]

    for relative_path in expected_paths:
        assert Path(relative_path).exists(), relative_path


def test_core_app_imports_routes_from_modules_instead_of_legacy_services_package():
    text = Path("csrcqsf/core/app.py").read_text(encoding="utf-8")

    assert "from csrcqsf.services import" not in text
    assert "from csrcqsf.modules.railway_parts.routes import parts_router" in text
    assert "from csrcqsf.modules.sgo.routes import sgo_router" in text
    assert "from csrcqsf.modules.doc_parse.routes import parts_docs_router" in text
    assert "from csrcqsf.modules.image.routes import image_router" in text


def test_runtime_code_no_longer_imports_legacy_pg_or_legacy_manager_paths():
    expected_absences = {
        "csrcqsf/models/files.py": (
            "from csrcqsf.data.pg import",
            "from csrcqsf.infra.db.main_db import",
        ),
        "csrcqsf/models/item.py": (
            "from csrcqsf.data.pg import",
            "from csrcqsf.infra.db.main_db import",
        ),
        "csrcqsf/models/reconstruction.py": (
            "from csrcqsf.data.pg import",
            "from csrcqsf.infra.db.main_db import",
        ),
        "csrcqsf/models/reconstruction_upload.py": (
            "from csrcqsf.data.pg import",
            "from csrcqsf.infra.db.main_db import",
        ),
        "csrcqsf/models/search_history.py": (
            "from csrcqsf.data.pg import",
            "from csrcqsf.infra.db.main_db import",
        ),
        "csrcqsf/models/sgo.py": (
            "from csrcqsf.data.pg import",
            "from csrcqsf.infra.db.main_db import",
        ),
        "csrcqsf/biz/sgo.py": (
            "from csrcqsf.data.pg import",
            "from csrcqsf.infra.db.main_db import",
        ),
        "csrcqsf/biz/doc_parse.py": (
            "from csrcqsf.data.pg import",
            "from csrcqsf.infra.db.main_db import",
        ),
        "csrcqsf/biz/railwayparts/auto_processor.py": (
            "from csrcqsf.data.pg import",
            "from csrcqsf.infra.db.main_db import",
        ),
        "csrcqsf/biz/railwayparts/reconstruction_sync_manager.py": (
            "from csrcqsf.data.pg import",
            "from csrcqsf.infra.db.main_db import",
        ),
        "csrcqsf/modules/railway_parts/services/parts_service.py": (
            "from csrcqsf.data.pg import",
            "from csrcqsf.infra.db.main_db import",
        ),
        "csrcqsf/modules/railway_parts/services/reconstruction_service.py": (
            "from csrcqsf.data.pg import",
            "from csrcqsf.infra.db.main_db import",
        ),
    }

    for relative_path, (legacy_fragment, new_fragment) in expected_absences.items():
        text = Path(relative_path).read_text(encoding="utf-8")
        assert legacy_fragment not in text, relative_path
        assert new_fragment in text, relative_path


def test_railway_parts_runtime_routes_and_services_no_longer_import_legacy_business_modules():
    forbidden_fragments = (
        "csrcqsf.biz.railwayparts.parts",
        "csrcqsf.biz.railwayparts.reconstruction_manager",
    )

    target_paths = [
        "csrcqsf/modules/railway_parts/routes/parts_routes.py",
        "csrcqsf/modules/railway_parts/routes/search_routes.py",
        "csrcqsf/modules/railway_parts/routes/review_ticket_routes.py",
        "csrcqsf/modules/railway_parts/routes/reconstruction_routes.py",
        "csrcqsf/modules/railway_parts/services/parts_service.py",
        "csrcqsf/biz/segment.py",
        "csrcqsf/biz/sgo.py",
        "csrcqsf/biz/railwayparts/reconstruction_sync_manager.py",
    ]

    for relative_path in target_paths:
        text = Path(relative_path).read_text(encoding="utf-8")
        for fragment in forbidden_fragments:
            assert fragment not in text, f"{relative_path} still imports {fragment}"


def test_vector_search_config_no_longer_hardcodes_legacy_vector_db_source_tree_paths():
    text = Path(
        "csrcqsf/modules/railway_parts/vector_search/config/vector_db.ini"
    ).read_text(encoding="utf-8")

    assert "csrcqsf/biz/railwayparts/vector_db/" not in text
    assert "patch_tokens_dir = state/vector_db/patch_tokens" in text
    assert "checkpoint_file = state/vector_db/checkpoint.json" in text
    assert "log_dir = logs/vector_db" in text


def test_phase_six_route_and_image_tests_can_use_modules_entrypoints_instead_of_services_layers():
    expected_paths = [
        "csrcqsf/modules/railway_parts/routes/__init__.py",
        "csrcqsf/modules/image/routes.py",
    ]

    for relative_path in expected_paths:
        assert Path(relative_path).exists(), relative_path
