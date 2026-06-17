from __future__ import annotations

from urllib.parse import unquote

from csrcqsf.core.settings import (
    minio_bucket,
    minio_reconstruction_file_bucket,
    minio_reconstruction_video_bucket,
    minio_search_history_bucket,
)

INTERNAL_ACCEL_REDIRECT_PREFIX = "/recognition_oss"
SUPPORTED_ASSET_BUCKETS = tuple(
    dict.fromkeys(
        bucket
        for bucket in (
            minio_bucket,
            minio_reconstruction_video_bucket,
            minio_reconstruction_file_bucket,
            minio_search_history_bucket,
        )
        if str(bucket or "").strip() != ""
    )
)


def asset_url_from_internal_path(path: str | None) -> str | None:
    if path is None:
        return None
    raw = str(path).strip()
    if raw == "":
        return None
    normalized = normalize_public_asset_path(raw).lstrip("/")
    parsed = parse_public_asset_url(normalized)
    if parsed is None:
        return raw
    bucket, object_name = parsed
    return f"{bucket}/{object_name}"


def normalize_public_asset_path(path: str | None) -> str:
    raw = unquote(str(path or "")).strip()
    if raw == "":
        return ""
    if "?" in raw:
        raw = raw.split("?", 1)[0]
    if "#" in raw:
        raw = raw.split("#", 1)[0]
    while "//" in raw:
        raw = raw.replace("//", "/")
    return raw


def parse_public_asset_url(path: str | None) -> tuple[str, str] | None:
    normalized = normalize_public_asset_path(path).lstrip("/")
    if normalized == "" or ".." in normalized:
        return None
    if "/" not in normalized:
        return None
    bucket, object_name = normalized.split("/", 1)
    if bucket not in SUPPORTED_ASSET_BUCKETS:
        return None
    object_name = object_name.lstrip("/")
    if object_name == "":
        return None
    return bucket, object_name


def is_supported_public_asset_url(path: str | None) -> bool:
    return parse_public_asset_url(path) is not None


def build_internal_accel_redirect(bucket: str, object_name: str) -> str:
    normalized_object_name = str(object_name or "").lstrip("/")
    return f"{INTERNAL_ACCEL_REDIRECT_PREFIX}/{bucket}/{normalized_object_name}"
