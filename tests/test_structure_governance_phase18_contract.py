from pathlib import Path


def test_phase_eighteen_target_service_modules_exist():
    expected_paths = [
        "csrcqsf/modules/sgo/services.py",
        "csrcqsf/modules/railway_parts/integrations/milvus_state_manager.py",
    ]

    for relative_path in expected_paths:
        assert Path(relative_path).exists(), relative_path


def test_phase_eighteen_runtime_layers_stop_using_legacy_sgo_and_milvus_business_modules():
    target_paths = [
        "csrcqsf/core/app.py",
        "csrcqsf/modules/sgo/routes.py",
        "csrcqsf/modules/railway_parts/routes/parts_routes.py",
        "csrcqsf/modules/railway_parts/routes/search_routes.py",
        "csrcqsf/modules/railway_parts/services/parts_service.py",
    ]

    forbidden_fragments = (
        "from csrcqsf.biz.sgo import",
        "import csrcqsf.biz.sgo",
        "from csrcqsf.biz.railwayparts.milvus import",
        "import csrcqsf.biz.railwayparts.milvus",
    )

    for relative_path in target_paths:
        text = Path(relative_path).read_text(encoding="utf-8")
        for fragment in forbidden_fragments:
            assert fragment not in text, f"{relative_path} still imports {fragment}"


def test_phase_eighteen_target_modules_no_longer_reverse_import_legacy_business_modules():
    expected_fragments = {
        "csrcqsf/modules/sgo/services.py": (
            "from csrcqsf.core.scheduler import scheduler",
            "MilvusStateManagerV2",
        ),
        "csrcqsf/modules/railway_parts/integrations/milvus_state_manager.py": (
            "class MilvusManager",
            "class MilvusManagerV2",
            "class MilvusStateManagerV2",
        ),
    }

    forbidden_fragments = (
        "csrcqsf.biz.sgo",
        "csrcqsf.biz.railwayparts.milvus",
    )

    for relative_path, fragments in expected_fragments.items():
        text = Path(relative_path).read_text(encoding="utf-8")
        for fragment in fragments:
            assert fragment in text, f"{relative_path} missing {fragment}"
        for fragment in forbidden_fragments:
            assert fragment not in text, f"{relative_path} still references {fragment}"


def test_phase_eighteen_legacy_business_modules_are_removed_after_service_cutover():
    removed_paths = [
        "csrcqsf/biz/sgo.py",
        "csrcqsf/biz/railwayparts/milvus.py",
    ]

    for relative_path in removed_paths:
        assert not Path(relative_path).exists(), relative_path
