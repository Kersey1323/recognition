from pathlib import Path


def test_phase_seven_legacy_services_package_removed():
    removed_paths = [
        "csrcqsf/services/__init__.py",
        "csrcqsf/services/parts.py",
        "csrcqsf/services/images.py",
        "csrcqsf/services/doc_parse.py",
        "csrcqsf/services/sgo.py",
    ]

    for relative_path in removed_paths:
        assert not Path(relative_path).exists(), relative_path


def test_phase_seven_public_route_modules_remain_as_runtime_entrypoints():
    expected_paths = [
        "csrcqsf/modules/railway_parts/routes/__init__.py",
        "csrcqsf/modules/sgo/routes.py",
        "csrcqsf/modules/doc_parse/routes.py",
        "csrcqsf/modules/image/routes.py",
    ]

    for relative_path in expected_paths:
        assert Path(relative_path).exists(), relative_path


def test_phase_seven_governance_tests_no_longer_reference_legacy_services_package():
    target_paths = [
        "tests/test_structure_governance_phase0_contract.py",
        "tests/test_structure_governance_phase2_contract.py",
        "tests/test_structure_governance_phase6_contract.py",
        "tests/test_v2_route_definitions.py",
    ]

    forbidden_fragments = (
        "csrcqsf/services/",
        'importlib.import_module("csrcqsf.services',
        'Path("csrcqsf/services/',
    )

    for relative_path in target_paths:
        text = Path(relative_path).read_text(encoding="utf-8")
        for fragment in forbidden_fragments:
            assert fragment not in text, f"{relative_path} still references {fragment}"
