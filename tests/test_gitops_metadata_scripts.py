from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def parse_key_values(output: str) -> dict[str, str]:
    pairs = {}
    for line in output.strip().splitlines():
        key, value = line.split("=", 1)
        pairs[key] = value
    return pairs


def test_extract_runtime_metadata_reads_dockerfile_contract() -> None:
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "extract_runtime_metadata.sh")],
        check=True,
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**os.environ, "CI_PROJECT_NAME": "recognition", "CI_PROJECT_NAMESPACE": "xi"},
    )

    values = parse_key_values(result.stdout)

    assert values == {
        "APP_NAME": "recognition",
        "GROUP": "xi",
        "HOST": "xi-recognition.buffalo.com",
        "CONTAINER_PORT": "65432",
        "HEALTH_PATH": "/health",
        "APP_DATA_DIRS": "logs,temp,state",
    }


def test_update_gitops_app_yaml_rewrites_generated_and_preserves_overrides(tmp_path: Path) -> None:
    descriptor = tmp_path / "app.yaml"
    descriptor.write_text(
        "\n".join(
            [
                "generated:",
                '  appName: "old-app"',
                '  group: "old-group"',
                '  host: "old-host"',
                "  image:",
                '    repository: "old-repo"',
                '    tag: "old-tag"',
                "  runtime:",
                "    containerPort: 1",
                '    healthPath: "/old"',
                "    appDataDirs: []",
                "overrides:",
                "  replicas: 1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "update_gitops_app_yaml.py"),
            "cicd-test-registry:5000/recognition:abc12345",
            str(descriptor),
        ],
        check=True,
        cwd=ROOT,
        env={
            **os.environ,
            "APP_NAME": "recognition",
            "GROUP": "xi",
            "HOST": "xi-recognition.buffalo.com",
            "CONTAINER_PORT": "65432",
            "HEALTH_PATH": "/health",
            "APP_DATA_DIRS": "logs,temp,state",
        },
    )

    assert descriptor.read_text(encoding="utf-8") == "\n".join(
        [
            "generated:",
            '  appName: "recognition"',
            '  group: "xi"',
            '  host: "xi-recognition.buffalo.com"',
            "  image:",
            '    repository: "cicd-test-registry:5000/recognition"',
            '    tag: "abc12345"',
            "  runtime:",
            "    containerPort: 65432",
            '    healthPath: "/health"',
            "    appDataDirs:",
            '      - "logs"',
            '      - "temp"',
            '      - "state"',
            "overrides:",
            "  replicas: 1",
            "",
        ]
    )
