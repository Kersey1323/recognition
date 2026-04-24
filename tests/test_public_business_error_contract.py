import ast
from pathlib import Path


PROJECT_ROOT = Path("/home/ubuntu/project-train/recognition")
RAILWAYPARTS_BIZ_ROOT = PROJECT_ROOT / "csrcqsf" / "biz" / "railwayparts"
PUBLIC_SERVICE_FILE = PROJECT_ROOT / "csrcqsf" / "services" / "parts.py"


def _iter_public_business_files() -> list[Path]:
    files: list[Path] = []

    for path in RAILWAYPARTS_BIZ_ROOT.rglob("*.py"):
        if "reconstruction_server" in path.parts:
            continue
        files.append(path)

    files.append(PUBLIC_SERVICE_FILE)
    return sorted(set(files))


def _find_http_exception_usages(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    findings: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "fastapi":
            for alias in node.names:
                if alias.name == "HTTPException":
                    findings.append(f"import@{node.lineno}")

        if isinstance(node, ast.Raise):
            exc = node.exc
            if isinstance(exc, ast.Call):
                func = exc.func
                if isinstance(func, ast.Name) and func.id == "HTTPException":
                    findings.append(f"raise@{node.lineno}")
                elif isinstance(func, ast.Attribute) and func.attr == "HTTPException":
                    findings.append(f"raise@{node.lineno}")

    return findings


def test_public_parts_business_layers_do_not_raise_http_exception_directly():
    offenders: dict[str, list[str]] = {}

    for path in _iter_public_business_files():
        findings = _find_http_exception_usages(path)
        if findings:
            offenders[str(path.relative_to(PROJECT_ROOT))] = findings

    assert offenders == {}
