from pathlib import Path


def _legacy_vector_db_path(suffix: str) -> str:
    return "csrcqsf/biz/railwayparts/" + "vector_db/" + suffix


def _legacy_vector_db_import(suffix: str) -> str:
    return "csrcqsf.biz.railwayparts." + "vector_db." + suffix


def test_phase_nine_root_vector_db_scripts_and_tests_remain_available():
    expected_paths = [
        "scripts/vector_db/build_index.py",
        "scripts/vector_db/init_collections.py",
        "scripts/vector_db/diagnose_db.py",
        "tests/vector_db/test_dinov2_search.py",
        "tests/vector_db/test_siglip_search.py",
        "tests/vector_db/test_hybrid_search.py",
        "tests/vector_db/test_milvus_manager.py",
        "tests/vector_db/README.md",
    ]

    for relative_path in expected_paths:
        assert Path(relative_path).exists(), relative_path


def test_phase_nine_legacy_vector_db_python_compat_tree_removed():
    removed_paths = [
        _legacy_vector_db_path("__init__.py"),
        _legacy_vector_db_path("config/env_config.py"),
        _legacy_vector_db_path("data/db_connector.py"),
        _legacy_vector_db_path("data/image_loader.py"),
        _legacy_vector_db_path("indexing/indexer.py"),
        _legacy_vector_db_path("models/dinov2_extractor.py"),
        _legacy_vector_db_path("preprocessing/sam3_preprocessor.py"),
        _legacy_vector_db_path("storage/collection_manager.py"),
        _legacy_vector_db_path("storage/milvus_manager.py"),
        _legacy_vector_db_path("storage/milvus_state_manager.py"),
        _legacy_vector_db_path("utils/logger.py"),
        _legacy_vector_db_path("scripts/build_index.py"),
        _legacy_vector_db_path("tests/test_dinov2_search.py"),
    ]

    for relative_path in removed_paths:
        assert not Path(relative_path).exists(), relative_path


def test_phase_nine_vector_db_runtime_state_dirs_can_remain():
    allowed_paths = [
        _legacy_vector_db_path("patch_tokens"),
        _legacy_vector_db_path("logs"),
        _legacy_vector_db_path("config/db_config.ini"),
        _legacy_vector_db_path("config/vector_db.ini"),
    ]

    for relative_path in allowed_paths:
        assert Path(relative_path).exists(), relative_path


def test_phase_nine_governance_and_tests_no_longer_reference_legacy_vector_db_python_paths():
    target_paths = [
        "tests/test_structure_governance_phase4_contract.py",
        "tests/test_structure_governance_phase6_contract.py",
        "tests/test_v2_dual_representation_manager.py",
        "tests/test_v2_milvus_state_manager.py",
        "tests/test_collection_manager_image_variant.py",
        "tests/test_v2_collection_manager_helpers.py",
        "tests/test_sam3_prompt_optimization.py",
        "tests/test_sam3_preprocessor_visual.py",
        "tests/test_milvus_v2_full.py",
    ]

    forbidden_fragments = (
        _legacy_vector_db_import(""),
        _legacy_vector_db_path("config/"),
    )

    for relative_path in target_paths:
        text = Path(relative_path).read_text(encoding="utf-8")
        for fragment in forbidden_fragments:
            assert fragment not in text, f"{relative_path} still references {fragment}"
