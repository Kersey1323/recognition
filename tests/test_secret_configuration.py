import ast
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("relative_path, names", [
    ("csrcqsf/core/settings.py", {"MINIO_SECRET_KEY"}),
    ("csrcqsf/modules/railway_parts/vector_search/config/env_config.py", {"MINIO_SECRET_KEY"}),
    ("csrcqsf/modules/sgo/services.py", {
        "SGO_TENANT_ID", "SGO_USERNAME", "SGO_PASSWORD", "SGO_ENCRYPTION",
    }),
])
def test_credentials_have_no_embedded_environment_defaults(relative_path, names):
    tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "getenv" or not node.args:
            continue
        if not isinstance(node.args[0], ast.Constant) or node.args[0].value not in names:
            continue
        found.add(node.args[0].value)
        defaults = node.args[1:] + [item.value for item in node.keywords if item.arg == "default"]
        assert not defaults or all(
            isinstance(value, ast.Constant) and value.value in ("", None)
            for value in defaults
        ), f"{relative_path}: {node.args[0].value} must come from deployment configuration"
    assert found == names


@pytest.mark.parametrize("name", [".env", ".env.deployment", "docker/.env.cpu", "docker/.env copy.cpu"])
def test_private_environment_files_are_ignored(name):
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--quiet", name], cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0


def test_sanitized_environment_template_is_not_ignored():
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--quiet", ".env.example"], cwd=ROOT,
        check=False,
    )
    assert result.returncode == 1
