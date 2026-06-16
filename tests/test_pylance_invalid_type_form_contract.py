from pathlib import Path


def test_split_services_no_longer_suppress_report_invalid_type_form():
    target_paths = [
        "csrcqsf/modules/railway_parts/services/parts_index_service.py",
        "csrcqsf/modules/railway_parts/services/parts_search_service.py",
    ]

    for relative_path in target_paths:
        text = Path(relative_path).read_text(encoding="utf-8")
        assert "pyright: ignore[reportInvalidTypeForm]" not in text, relative_path
        assert "# type: ignore" not in text, relative_path


def test_split_services_define_static_type_aliases_for_pylance():
    expectations = {
        "csrcqsf/modules/railway_parts/services/parts_index_service.py": [
            "TYPE_CHECKING",
            "TypeAlias",
            "ImageIndexType",
        ],
        "csrcqsf/modules/railway_parts/services/parts_search_service.py": [
            "TYPE_CHECKING",
            "TypeAlias",
            "SearchItemType",
        ],
    }

    for relative_path, fragments in expectations.items():
        text = Path(relative_path).read_text(encoding="utf-8")
        for fragment in fragments:
            assert fragment in text, f"{relative_path} missing {fragment}"
