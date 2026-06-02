from pathlib import Path


def _legacy_vector_db_source_tree_root() -> str:
    return "/".join(("csrcqsf", "biz", "railwayparts", "vector_db")) + "/"


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
    target_paths = [
        "csrcqsf/models/orm/files.py",
        "csrcqsf/models/orm/item.py",
        "csrcqsf/models/orm/reconstruction.py",
        "csrcqsf/models/orm/reconstruction_upload.py",
        "csrcqsf/models/orm/search_history.py",
        "csrcqsf/models/orm/sgo.py",
        "csrcqsf/modules/railway_parts/services/parts_service.py",
        "csrcqsf/modules/railway_parts/services/reconstruction_service.py",
    ]

    for relative_path in target_paths:
        text = Path(relative_path).read_text(encoding="utf-8")
        assert "from csrcqsf.data.pg import" not in text, relative_path

    removed_paths = [
        "csrcqsf/biz/sgo.py",
        "csrcqsf/biz/doc_parse.py",
        "csrcqsf/biz/railwayparts/auto_processor.py",
        "csrcqsf/biz/railwayparts/reconstruction_sync_manager.py",
    ]
    for relative_path in removed_paths:
        assert not Path(relative_path).exists(), relative_path


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
    ]

    for relative_path in target_paths:
        text = Path(relative_path).read_text(encoding="utf-8")
        for fragment in forbidden_fragments:
            assert fragment not in text, f"{relative_path} still imports {fragment}"

    removed_paths = [
        "csrcqsf/biz/segment.py",
        "csrcqsf/biz/sgo.py",
        "csrcqsf/biz/railwayparts/reconstruction_sync_manager.py",
    ]
    for relative_path in removed_paths:
        assert not Path(relative_path).exists(), relative_path


def test_vector_search_config_no_longer_hardcodes_legacy_vector_db_source_tree_paths():
    text = Path(
        "csrcqsf/modules/railway_parts/vector_search/config/vector_db.ini"
    ).read_text(encoding="utf-8")

    assert _legacy_vector_db_source_tree_root() not in text
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
