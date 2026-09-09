"""SGO 询码回复字段的业务语义归一化。"""

from __future__ import annotations

import re


_ITEM_CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/+*()-]*$")


def _clean(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _looks_like_item_code(value: str | None) -> bool:
    if value is None:
        return False
    return bool(_ITEM_CODE_PATTERN.fullmatch(value) and any(char.isdigit() for char in value))


def normalize_sgo_return_item(
    physical_item_name: object,
    physical_item_code: object,
) -> tuple[str | None, str | None]:
    """兼容甲方回复表中正常与 name/code 写反的两类历史数据。"""
    item_name = _clean(physical_item_name)
    item_code = _clean(physical_item_code)
    name_is_code = _looks_like_item_code(item_name)
    code_is_code = _looks_like_item_code(item_code)

    # 只有名称列明显是编码、编码列明显不是编码时才交换，避免误判正常数据。
    if name_is_code and not code_is_code:
        return item_name, item_code
    return item_code, item_name
