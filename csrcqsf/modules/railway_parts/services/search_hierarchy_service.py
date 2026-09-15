"""Batch-enrich V2 search candidates with persisted direct hierarchy relations."""

from __future__ import annotations

from csrcqsf.infra.db.main_db import SessionLocal
from csrcqsf.models.orm.item import ItemHierarchyRelation
from csrcqsf.modules.railway_parts.schemas.search import SearchHierarchyPart, SearchItem


async def enrich_search_items(
    search_items: list[SearchItem], *, vehicle_batch: str | None = None
) -> None:
    codes = {item.item_code.strip() for item in search_items if item.item_code and item.item_code.strip()}
    if not codes:
        return
    async with SessionLocal() as session:
        relations = await ItemHierarchyRelation.list_search_relations(session, sorted(codes))

    parents: dict[str, set[tuple[str, str | None]]] = {}
    children: dict[str, set[tuple[str, str | None]]] = {}
    for row in relations:
        if vehicle_batch and row.vehicle_batch != vehicle_batch:
            continue
        code = (row.materiel_code or "").strip()
        parent_code = (row.parent_materiel_code or "").strip()
        if not code or not parent_code or code == parent_code:
            continue
        if code in codes:
            parents.setdefault(code, set()).add((parent_code, row.parent_materiel_name or None))
        if parent_code in codes:
            children.setdefault(parent_code, set()).add((code, row.materiel_name or None))

    for item in search_items:
        code = (item.item_code or "").strip()
        item.parent_parts = [
            SearchHierarchyPart(item_code=part_code, item_name=part_name)
            for part_code, part_name in sorted(parents.get(code, ()), key=lambda part: (part[0], part[1] or ""))
        ]
        item.child_parts = [
            SearchHierarchyPart(item_code=part_code, item_name=part_name)
            for part_code, part_name in sorted(children.get(code, ()), key=lambda part: (part[0], part[1] or ""))
        ]
