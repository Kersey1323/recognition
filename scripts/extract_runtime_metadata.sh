#!/usr/bin/env bash
set -euo pipefail

DOCKERFILE_PATH="${RUNTIME_DOCKERFILE:-Dockerfile}"
APP_NAME="${GITOPS_APP_NAME:-${CI_PROJECT_NAME:-$(basename "$(pwd)")}}"
CI_NAMESPACE="${CI_PROJECT_NAMESPACE:-}"
GROUP_NAME="${GITOPS_GROUP:-${CI_NAMESPACE##*/}}"
HOST_SUFFIX="${GITOPS_HOST_SUFFIX:-buffalo.com}"
DEFAULT_HEALTH_PATH="${GITOPS_HEALTH_PATH:-/health}"

if [[ -z "${GROUP_NAME}" || "${GROUP_NAME}" == "${CI_NAMESPACE}" ]]; then
  GROUP_NAME="${CI_PROJECT_ROOT_NAMESPACE:-xi}"
fi

python3 - "$DOCKERFILE_PATH" "$APP_NAME" "$GROUP_NAME" "$HOST_SUFFIX" "$DEFAULT_HEALTH_PATH" <<'PY'
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def collapse_dockerfile_lines(text: str) -> list[str]:
    logical_lines: list[str] = []
    current: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.endswith("\\"):
            current.append(stripped[:-1].strip())
            continue
        current.append(stripped)
        logical_lines.append(" ".join(part for part in current if part))
        current = []
    if current:
        logical_lines.append(" ".join(part for part in current if part))
    return logical_lines


def parse_expose(lines: list[str]) -> int:
    for line in lines:
        match = re.match(r"^EXPOSE\s+(.+)$", line, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = match.group(1).split()[0].split("/")[0]
        if candidate.isdigit():
            return int(candidate)
    raise SystemExit("No EXPOSE instruction with a numeric port was found")


def parse_health_path(lines: list[str], default_path: str) -> str:
    for line in lines:
        if not re.match(r"^HEALTHCHECK\b", line, flags=re.IGNORECASE):
            continue
        match = re.search(r"https?://[^/\s\"']+(/[^\"\s']*)", line)
        if match:
            return match.group(1)
    return default_path


def parse_volumes(lines: list[str]) -> list[str]:
    for line in lines:
        match = re.match(r"^VOLUME\s+(.+)$", line, flags=re.IGNORECASE)
        if not match:
            continue
        raw_value = match.group(1).strip()
        volume_paths: list[str]
        if raw_value.startswith("["):
            volume_paths = json.loads(raw_value)
        else:
            volume_paths = raw_value.split()
        app_dirs: list[str] = []
        seen: set[str] = set()
        for path in volume_paths:
            normalized = path.strip().rstrip("/")
            if not normalized.startswith("/app/"):
                continue
            relative = normalized.removeprefix("/app/").strip("/")
            if not relative or relative in seen:
                continue
            seen.add(relative)
            app_dirs.append(relative)
        return app_dirs
    return []


dockerfile_path = Path(sys.argv[1])
if not dockerfile_path.exists():
    raise SystemExit(f"Dockerfile not found: {dockerfile_path}")

app_name = sys.argv[2]
group_name = sys.argv[3]
host_suffix = sys.argv[4]
default_health_path = sys.argv[5]

logical_lines = collapse_dockerfile_lines(dockerfile_path.read_text(encoding="utf-8"))
container_port = parse_expose(logical_lines)
health_path = parse_health_path(logical_lines, default_health_path)
app_data_dirs = parse_volumes(logical_lines)

print(f"APP_NAME={app_name}")
print(f"GROUP={group_name}")
print(f"HOST={group_name}-{app_name}.{host_suffix}")
print(f"CONTAINER_PORT={container_port}")
print(f"HEALTH_PATH={health_path}")
print(f"APP_DATA_DIRS={','.join(app_data_dirs)}")
PY
