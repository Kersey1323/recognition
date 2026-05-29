from pathlib import Path


def test_phase_eight_legacy_parts_reconstruction_and_pg_compat_modules_removed():
    removed_paths = [
        "csrcqsf/biz/railwayparts/parts.py",
        "csrcqsf/biz/railwayparts/reconstruction_manager.py",
        "csrcqsf/data/pg.py",
    ]

    for relative_path in removed_paths:
        assert not Path(relative_path).exists(), relative_path


def test_phase_eight_runtime_implementations_exist():
    expected_paths = [
        "csrcqsf/modules/railway_parts/services/parts_service.py",
        "csrcqsf/modules/railway_parts/services/reconstruction_service.py",
        "csrcqsf/infra/db/main_db.py",
    ]

    for relative_path in expected_paths:
        assert Path(relative_path).exists(), relative_path


def test_phase_eight_governance_contracts_no_longer_reference_removed_compat_modules():
    target_paths = [
        "tests/test_structure_governance_phase3_contract.py",
        "tests/test_structure_governance_phase6_contract.py",
        "tests/test_structure_governance_phase7_contract.py",
        "tests/test_structure_governance_phase8_contract.py",
    ]

    forbidden_fragments = (
        'Path("csrcqsf/biz/railwayparts/' + 'parts.py")',
        'Path("csrcqsf/biz/railwayparts/' + 'reconstruction_manager.py")',
        'Path("csrcqsf/data/' + 'pg.py")',
        'importlib.import_module("csrcqsf.biz.railwayparts.' + 'parts")',
        'importlib.import_module("csrcqsf.biz.railwayparts.' + 'reconstruction_manager")',
    )

    for relative_path in target_paths:
        text = Path(relative_path).read_text(encoding="utf-8")
        for fragment in forbidden_fragments:
            assert fragment not in text, f"{relative_path} still references {fragment}"
