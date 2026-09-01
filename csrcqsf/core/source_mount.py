from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from csrcqsf.core.logging_config import logger
from csrcqsf.core.runtime_paths import RuntimePaths, get_runtime_paths


SourceType = Literal["external-mount", "image-layer"]


@dataclass(frozen=True)
class SourceMountResolution:
    source_type: SourceType
    container_path: str
    resolved_path: str
    mount_root: str | None = None
    filesystem: str | None = None
    mount_source: str | None = None
    diagnostic: str | None = None


def _decode_mountinfo_path(value: str) -> str:
    replacements = {
        "\\040": " ",
        "\\011": "\t",
        "\\012": "\n",
        "\\134": "\\",
    }
    for encoded, decoded in replacements.items():
        value = value.replace(encoded, decoded)
    return value


def resolve_source_mount(
    *,
    container_path: Path,
    mountinfo_path: Path,
) -> SourceMountResolution:
    """判断当前业务包来自宿主机挂载还是镜像内置源码。"""
    resolved_path = container_path.resolve()
    base = {
        "container_path": str(container_path),
        "resolved_path": str(resolved_path),
    }

    try:
        lines = mountinfo_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return SourceMountResolution(
            source_type="image-layer",
            diagnostic=str(exc),
            **base,
        )

    # 只有挂载点与业务包路径完全一致时才认定为外部源码，父目录中的普通挂载不算。
    for line in lines:
        left, separator, right = line.partition(" - ")
        if not separator:
            continue
        left_fields = left.split()
        right_fields = right.split()
        if len(left_fields) < 5 or len(right_fields) < 2:
            continue

        mount_point = Path(_decode_mountinfo_path(left_fields[4]))
        if mount_point != resolved_path:
            continue
        return SourceMountResolution(
            source_type="external-mount",
            mount_root=_decode_mountinfo_path(left_fields[3]),
            filesystem=right_fields[0],
            mount_source=_decode_mountinfo_path(right_fields[1]),
            **base,
        )

    return SourceMountResolution(source_type="image-layer", **base)


def _env_flag(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def record_source_mount(
    paths: RuntimePaths | None = None,
    *,
    container_path: Path | None = None,
    mountinfo_path: Path | None = None,
) -> SourceMountResolution | None:
    """记录实际运行的源码来源，便于线上确认挂载代码是否已经生效。"""
    if not _env_flag("RECOGNITION_MAIN_SOURCE_LOG_ENABLED", True):
        return None

    runtime_paths = paths or get_runtime_paths()
    package_path = Path(__file__).resolve().parents[1]
    configured_container_path = container_path or Path(
        os.getenv("RECOGNITION_MAIN_SOURCE_CONTAINER_PATH", str(package_path))
    )
    configured_mountinfo_path = mountinfo_path or Path(
        os.getenv("RECOGNITION_MAIN_MOUNTINFO_PATH", "/proc/self/mountinfo")
    )
    resolution = resolve_source_mount(
        container_path=configured_container_path,
        mountinfo_path=configured_mountinfo_path,
    )
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": "source_mount_resolution",
        "service": "recognition-service",
        **asdict(resolution),
        "host_path": os.getenv("RECOGNITION_MAIN_SOURCE_HOST_PATH") or None,
        "pid": os.getpid(),
        "argv": sys.argv,
    }

    # 源码来源日志不能影响主服务启动，因此磁盘不可写时仅告警。
    try:
        runtime_paths.log_dir.mkdir(parents=True, exist_ok=True)
        source_log_path = runtime_paths.log_dir / "source_mount.log"
        with source_log_path.open("a", encoding="utf-8") as source_log:
            source_log.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning(
            "源码来源日志写入失败: path={}, error={}",
            runtime_paths.log_dir / "source_mount.log",
            exc,
        )

    return resolution
