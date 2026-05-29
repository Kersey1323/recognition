from pathlib import Path
import subprocess


def test_csrcqsf_runtime_artifacts_are_not_git_tracked_and_are_gitignored():
    tracked = subprocess.run(
        [
            "git",
            "ls-files",
            "csrcqsf",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    assert not [path for path in tracked if "__pycache__/" in path or path.endswith(".pyc")]
    assert not [path for path in tracked if "csrcqsf/biz/railwayparts/vector_db/logs/" in path]

    gitignore = Path(".gitignore").read_text(encoding="utf-8")
    assert "csrcqsf/**/__pycache__/" in gitignore
    assert "csrcqsf/**/*.pyc" in gitignore
    assert "csrcqsf/biz/railwayparts/vector_db/logs/" in gitignore


def test_app_entrypoint_no_longer_uses_star_imports():
    text = Path("csrcqsf/app.py").read_text(encoding="utf-8")

    assert "from .api_models import *" not in text
    assert "from csrcqsf.services import *" not in text


def test_service_entrypoints_no_longer_use_star_imports():
    for relative_path in [
        "csrcqsf/modules/railway_parts/routes/__init__.py",
        "csrcqsf/modules/sgo/routes.py",
        "csrcqsf/modules/doc_parse/routes.py",
        "csrcqsf/modules/image/routes.py",
    ]:
        text = Path(relative_path).read_text(encoding="utf-8")
        assert "import *" not in text, relative_path


def test_main_db_alias_module_exists_for_phase_zero_naming_transition():
    text = Path("csrcqsf/data/main_db.py").read_text(encoding="utf-8")

    assert "csrcqsf.infra.db.main_db" in text
