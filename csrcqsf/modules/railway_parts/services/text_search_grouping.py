from __future__ import annotations

import re
import unicodedata
from typing import Any

from csrcqsf.models.orm.search_history import SearchGroupMember


def normalize_item_name_group(item_name: str | None, item_code: str | None) -> str:
    """同名聚合只消除字符宽度、空白和大小写差异，保留型号与方位信息。"""
    normalized = unicodedata.normalize("NFKC", item_name or "")
    normalized = re.sub(r"\s+", " ", normalized).strip().casefold()
    if normalized:
        return f"name:{normalized}"
    return f"code:{str(item_code or '').strip().casefold()}"


def aggregate_text_search_items_by_name(
    search_items: list[Any],
    *,
    limit: int,
) -> list[Any]:
    """让同名多编码共享一个召回位，并在该组中保留全部编码。"""
    grouped: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(search_items):
        key = normalize_item_name_group(item.item_name, item.item_code)
        bucket = grouped.setdefault(
            key,
            {"best": item, "first_index": index, "members": {}},
        )
        member = SearchGroupMember(
            item_id=str(item.item_id),
            item_code=item.item_code,
            item_name=item.item_name,
            rate=float(item.rate),
            matched_description=getattr(item, "matched_description", None),
            matched_inquiry_id=getattr(item, "matched_inquiry_id", None),
        )
        previous = bucket["members"].get(member.item_code)
        if previous is None or member.rate > previous.rate:
            bucket["members"][member.item_code] = member
        if float(item.rate) > float(bucket["best"].rate):
            bucket["best"] = item

    aggregated = []
    for bucket in grouped.values():
        members = sorted(
            bucket["members"].values(),
            key=lambda member: -member.rate,
        )
        aggregated.append(
            (
                bucket["best"].copy(update={"group_members": members}),
                bucket["first_index"],
            )
        )
    aggregated.sort(key=lambda pair: (-float(pair[0].rate), pair[1]))
    return [item for item, _index in aggregated[:limit]]
