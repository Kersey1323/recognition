from pathlib import Path


def test_phase_three_service_modules_exist():
    expected_paths = [
        "csrcqsf/modules/railway_parts/services/__init__.py",
        "csrcqsf/modules/railway_parts/services/parts_service.py",
        "csrcqsf/modules/railway_parts/services/reconstruction_service.py",
    ]

    for relative_path in expected_paths:
        assert Path(relative_path).exists(), relative_path


def test_phase_three_legacy_business_compat_modules_removed():
    removed_paths = [
        "csrcqsf/biz/railwayparts/parts.py",
        "csrcqsf/biz/railwayparts/reconstruction_manager.py",
    ]

    for relative_path in removed_paths:
        assert not Path(relative_path).exists(), relative_path
