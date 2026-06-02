from pathlib import Path


def test_phase_nineteen_target_modules_exist():
    expected_paths = [
        "csrcqsf/modules/railway_parts/services/auto_processor_service.py",
    ]

    for relative_path in expected_paths:
        assert Path(relative_path).exists(), relative_path


def test_phase_nineteen_target_service_modules_stop_reverse_importing_legacy_orms():
    expectations = {
        "csrcqsf/modules/sgo/services.py": (
            "from csrcqsf.models.orm.item import Items",
            "from csrcqsf.models.orm.sgo import SgoItemImages",
            "from csrcqsf.models.orm.sgo_external import (",
        ),
        "csrcqsf/modules/railway_parts/repositories/search_history_repository.py": (
            "from csrcqsf.models.orm.search_history import SearchHistory, SearchReviewTicket",
        ),
        "csrcqsf/modules/railway_parts/schemas/_parts_api_models.py": (
            "from csrcqsf.models.orm.search_history import MatchedImage, SearchParameters, SearchResults",
        ),
    }

    forbidden_fragments = (
        "from csrcqsf.models.item import",
        "from csrcqsf.models.sgo import",
        "from csrcqsf.models.search_history import",
        "from csrcqsf.models.sgo_models import",
    )

    for relative_path, required_fragments in expectations.items():
        text = Path(relative_path).read_text(encoding="utf-8")
        for fragment in required_fragments:
            assert fragment in text, f"{relative_path} missing {fragment}"
        for fragment in forbidden_fragments:
            assert fragment not in text, f"{relative_path} still imports {fragment}"


def test_phase_nineteen_auto_processor_old_path_is_removed():
    assert not Path("csrcqsf/biz/railwayparts/auto_processor.py").exists()


def test_phase_nineteen_auto_processor_new_path_no_longer_reverse_imports_legacy_biz_module():
    text = Path("csrcqsf/modules/railway_parts/services/auto_processor_service.py").read_text(
        encoding="utf-8"
    )
    assert "csrcqsf.biz.railwayparts.auto_processor" not in text
