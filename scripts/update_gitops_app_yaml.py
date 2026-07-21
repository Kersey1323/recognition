from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


def quote(value: str) -> str:
    return json.dumps(value)


def build_generated_section(image_ref: str) -> str:
    app_name = os.environ["APP_NAME"]
    group = os.environ["GROUP"]
    host = os.environ["HOST"]
    container_port = int(os.environ["CONTAINER_PORT"])
    health_path = os.environ["HEALTH_PATH"]
    app_data_dirs = [item for item in os.environ.get("APP_DATA_DIRS", "").split(",") if item]
    image_repository, image_tag = image_ref.rsplit(":", 1)

    lines = [
        "generated:",
        f"  appName: {quote(app_name)}",
        f"  group: {quote(group)}",
        f"  host: {quote(host)}",
        "  image:",
        f"    repository: {quote(image_repository)}",
        f"    tag: {quote(image_tag)}",
        "  runtime:",
        f"    containerPort: {container_port}",
        f"    healthPath: {quote(health_path)}",
    ]

    if app_data_dirs:
        lines.append("    appDataDirs:")
        for directory in app_data_dirs:
            lines.append(f"      - {quote(directory)}")
    else:
        lines.append("    appDataDirs: []")

    return "\n".join(lines) + "\n"


def preserve_overrides(text: str) -> str:
    match = re.search(r"(?ms)^overrides:\n.*\Z", text)
    if match:
        return match.group(0).rstrip() + "\n"
    return "overrides: {}\n"


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: update_gitops_app_yaml.py <image-ref> <descriptor-path>")

    image_ref = sys.argv[1]
    descriptor_path = Path(sys.argv[2])
    existing = descriptor_path.read_text(encoding="utf-8")
    updated = build_generated_section(image_ref) + preserve_overrides(existing)
    descriptor_path.write_text(updated, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
