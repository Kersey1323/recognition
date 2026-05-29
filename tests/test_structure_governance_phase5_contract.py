from pathlib import Path


def test_phase_five_schema_packages_exist():
    expected_paths = [
        "csrcqsf/modules/railway_parts/schemas/__init__.py",
        "csrcqsf/modules/railway_parts/schemas/parts.py",
        "csrcqsf/modules/railway_parts/schemas/search.py",
        "csrcqsf/modules/railway_parts/schemas/review_ticket.py",
        "csrcqsf/modules/railway_parts/schemas/reconstruction.py",
        "csrcqsf/modules/sgo/__init__.py",
        "csrcqsf/modules/sgo/schemas.py",
        "csrcqsf/modules/railway_parts/repositories/__init__.py",
        "csrcqsf/modules/railway_parts/repositories/search_history_repository.py",
    ]

    for relative_path in expected_paths:
        assert Path(relative_path).exists(), relative_path


def test_legacy_api_model_modules_reference_new_schema_packages():
    expected_references = {
        "csrcqsf/biz/railwayparts/api_models.py": "csrcqsf.modules.railway_parts.schemas",
        "csrcqsf/biz/railwayparts/reconstruction_api_models.py": "csrcqsf.modules.railway_parts.schemas.reconstruction",
    }

    for relative_path, expected in expected_references.items():
        text = Path(relative_path).read_text(encoding="utf-8")
        assert expected in text, relative_path


def test_routes_reference_new_schema_modules_instead_of_legacy_api_models():
    expected_references = {
        "csrcqsf/modules/railway_parts/routes/parts_routes.py": "csrcqsf.modules.railway_parts.schemas.parts",
        "csrcqsf/modules/railway_parts/routes/search_routes.py": "csrcqsf.modules.railway_parts.schemas.search",
        "csrcqsf/modules/railway_parts/routes/review_ticket_routes.py": "csrcqsf.modules.railway_parts.schemas.review_ticket",
        "csrcqsf/modules/railway_parts/routes/reconstruction_routes.py": "csrcqsf.modules.railway_parts.schemas.reconstruction",
    }

    forbidden_references = (
        "csrcqsf.biz.railwayparts.api_models",
        "csrcqsf.biz.railwayparts.reconstruction_api_models",
    )

    for relative_path, expected in expected_references.items():
        text = Path(relative_path).read_text(encoding="utf-8")
        assert expected in text, relative_path
        for forbidden in forbidden_references:
            assert forbidden not in text, f"{relative_path} still imports {forbidden}"


def test_sgo_models_file_is_orm_oriented_and_uses_external_schema_types():
    text = Path("csrcqsf/models/sgo.py").read_text(encoding="utf-8")
    assert "from csrcqsf.modules.sgo.schemas import" in text
    assert "class ListInqueryItem" not in text


def test_phase_five_search_history_repository_is_referenced_by_parts_service():
    repository_text = Path(
        "csrcqsf/modules/railway_parts/repositories/search_history_repository.py"
    ).read_text(encoding="utf-8")
    service_text = Path(
        "csrcqsf/modules/railway_parts/services/parts_service.py"
    ).read_text(encoding="utf-8")

    assert "class SearchHistoryRepository" in repository_text
    assert "SearchHistoryRepository" in service_text
