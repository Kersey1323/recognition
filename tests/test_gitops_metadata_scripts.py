from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_project_ci_hook_scripts_exist() -> None:
    assert (ROOT / "scripts" / "ci" / "lint.sh").is_file()
    assert (ROOT / "scripts" / "ci" / "test.sh").is_file()
    assert (ROOT / "scripts" / "ci" / "build.sh").is_file()


def test_business_repo_does_not_ship_platform_gitops_scripts() -> None:
    assert not (ROOT / "scripts" / "extract_runtime_metadata.sh").exists()
    assert not (ROOT / "scripts" / "update_gitops_app_yaml.py").exists()
    assert not (ROOT / "scripts" / "update_gitops_repo.sh").exists()

