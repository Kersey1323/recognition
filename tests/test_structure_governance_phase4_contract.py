from pathlib import Path


def _parse_env_file(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key] = value
    return values


def test_phase_four_vector_search_modules_exist():
    expected_paths = [
        "csrcqsf/modules/railway_parts/vector_search/__init__.py",
        "csrcqsf/modules/railway_parts/vector_search/config/__init__.py",
        "csrcqsf/modules/railway_parts/vector_search/repositories/__init__.py",
        "csrcqsf/modules/railway_parts/vector_search/indexing/__init__.py",
        "csrcqsf/modules/railway_parts/vector_search/extractors/__init__.py",
        "csrcqsf/modules/railway_parts/vector_search/preprocessing/__init__.py",
        "csrcqsf/modules/railway_parts/vector_search/storage/__init__.py",
        "csrcqsf/modules/railway_parts/vector_search/utils/__init__.py",
    ]

    for relative_path in expected_paths:
        assert Path(relative_path).exists(), relative_path


def test_vector_search_runtime_modules_exist():
    expected_paths = [
        "csrcqsf/modules/railway_parts/vector_search/config/env_config.py",
        "csrcqsf/modules/railway_parts/vector_search/repositories/db_connector.py",
        "csrcqsf/modules/railway_parts/vector_search/repositories/image_loader.py",
        "csrcqsf/modules/railway_parts/vector_search/indexing/indexer.py",
        "csrcqsf/modules/railway_parts/vector_search/extractors/dinov2_extractor.py",
        "csrcqsf/modules/railway_parts/vector_search/preprocessing/sam3_preprocessor.py",
        "csrcqsf/modules/railway_parts/vector_search/storage/milvus_manager.py",
        "csrcqsf/modules/railway_parts/vector_search/storage/milvus_state_manager.py",
        "csrcqsf/modules/railway_parts/vector_search/utils/logger.py",
    ]

    for relative_path in expected_paths:
        assert Path(relative_path).exists(), relative_path


def test_phase_four_root_level_scripts_and_tests_exist():
    expected_paths = [
        "scripts/vector_db/build_index.py",
        "scripts/vector_db/init_collections.py",
        "scripts/vector_db/diagnose_db.py",
        "tests/vector_db/test_dinov2_search.py",
        "tests/vector_db/test_hybrid_search.py",
        "tests/vector_db/test_milvus_manager.py",
        "tests/vector_db/test_siglip_search.py",
        "tests/vector_db/README.md",
    ]

    for relative_path in expected_paths:
        assert Path(relative_path).exists(), relative_path


def test_phase_four_env_defaults_externalize_vector_db_state_paths():
    expected = {
        "DINOV2_PATCH_TOKENS_DIR": "state/vector_db/patch_tokens",
        "INDEXING_CHECKPOINT_FILE": "state/vector_db/checkpoint.json",
    }

    for env_path in [Path(".env"), Path(".env.example")]:
        values = _parse_env_file(env_path)
        for key, expected_value in expected.items():
            assert values[key] == expected_value, f"{env_path}:{key}"
