from __future__ import annotations

import json
import re
from typing import Any


_URL_CREDENTIAL_RE = re.compile(
    r"(?P<prefix>[a-z][a-z0-9+.-]*://[^:/\s]+:)[^@\s/]+(?=@)",
    re.IGNORECASE,
)
_SENSITIVE_FIELD_RE = re.compile(
    r"(?P<name>password|passwd|pwd|token|access[_-]?key|secret[_-]?key|authorization|u-token)"
    r"(?P<separator>\s*[:=]\s*)(?:Bearer\s+)?[^\s,;]+",
    re.IGNORECASE,
)


def _stringify(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _sanitize(message: str, *, max_length: int = 2000) -> str:
    text = message.strip() or "远端服务未返回错误详情"
    text = _URL_CREDENTIAL_RE.sub(r"\g<prefix>[REDACTED]", text)
    text = _SENSITIVE_FIELD_RE.sub(
        lambda match: f"{match.group('name')}{match.group('separator')}[REDACTED]",
        text,
    )
    if len(text) > max_length:
        return f"{text[:max_length]}..."
    return text


def format_remote_error(payload: Any) -> str:
    if not isinstance(payload, dict):
        return _sanitize(_stringify(payload))

    detail = payload.get("detail") or payload.get("message") or payload.get("error") or payload
    metadata = []
    for key in ("service", "error_type", "request_id"):
        value = payload.get(key)
        if value:
            metadata.append(f"{key}={_sanitize(_stringify(value), max_length=200)}")

    message = _sanitize(_stringify(detail))
    return f"{message} ({', '.join(metadata)})" if metadata else message


async def read_remote_error(response) -> str:
    try:
        payload = await response.json()
    except Exception:
        payload = await response.text()
    return format_remote_error(payload)
