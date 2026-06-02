from pathlib import Path


def _legacy_vector_db_path(suffix: str) -> str:
    return "/".join(("csrcqsf", "biz", "railwayparts", "vector_db", suffix))


def _legacy_vector_db_import(suffix: str) -> str:
    parts = ["csrcqsf", "biz", "railwayparts", "vector_db"]
    if suffix:
        parts.append(suffix)
    return ".".join(parts)


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
    legacy_root = Path(_legacy_vector_db_path(""))

    assert not legacy_root.exists()


def test_phase_nine_vector_db_runtime_state_is_externalized_outside_source_tree():
    assert Path("csrcqsf/modules/railway_parts/vector_search/config/db_config.ini").exists()
    assert Path("csrcqsf/modules/railway_parts/vector_search/config/vector_db.ini").exists()
    assert Path("state/vector_db/patch_tokens").exists()
    assert not Path(_legacy_vector_db_path("patch_tokens")).exists()
    assert not Path(_legacy_vector_db_path("config")).exists()


def test_phase_nine_governance_tests_and_docs_no_longer_reference_legacy_vector_db_python_paths():
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
        "tests/test_item_image_upload_manager.py",
        "tests/vector_db/README.md",
        "docs/VECTOR_DB_CONFIG_MIGRATION.md",
    ]

    forbidden_fragments = (
        _legacy_vector_db_import(""),
        _legacy_vector_db_path("config/"),
    )

    for relative_path in target_paths:
        text = Path(relative_path).read_text(encoding="utf-8")
        for fragment in forbidden_fragments:
            assert fragment not in text, f"{relative_path} still references {fragment}"
