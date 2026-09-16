"""Batch-enrich V2 search candidates with persisted direct hierarchy relations."""

from __future__ import annotations

from csrcqsf.infra.db.main_db import SessionLocal
from csrcqsf.models.orm.item import ItemHierarchyRelation
from csrcqsf.models.orm.search_history import SearchResultItem
from csrcqsf.modules.railway_parts.schemas.parts import GetItemDetailRes, HierarchyItemDetailRes
from csrcqsf.modules.railway_parts.schemas.search import SearchHierarchyPart, SearchItem


async def enrich_search_items(
    search_items: list[SearchItem] | list[SearchResultItem] | list[GetItemDetailRes], *, vehicle_batch: str | None = None
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


async def get_hierarchy_item_detail(
    item_code: str, *, vehicle_batch: str | None = None
) -> HierarchyItemDetailRes | None:
    async with SessionLocal() as session:
        relations = await ItemHierarchyRelation.list_search_relations(session, [item_code])

    rows = [row for row in relations if not vehicle_batch or row.vehicle_batch == vehicle_batch]
    if not rows:
        return None

    direct_names: set[str] = set()
    referenced_names: set[str] = set()
    parents: set[tuple[str, str | None]] = set()
    children: set[tuple[str, str | None]] = set()
    vehicles: set[str] = set()
    for row in rows:
        code = (row.materiel_code or "").strip()
        parent_code = (row.parent_materiel_code or "").strip()
        if row.vehicle_batch:
            vehicles.add(row.vehicle_batch)
        if code == item_code:
            if row.materiel_name and row.materiel_name.strip():
                direct_names.add(row.materiel_name.strip())
            if parent_code and parent_code != item_code:
                parents.add((parent_code, (row.parent_materiel_name or "").strip() or None))
        if parent_code == item_code:
            if row.parent_materiel_name and row.parent_materiel_name.strip():
                referenced_names.add(row.parent_materiel_name.strip())
            if code and code != item_code:
                children.add((code, (row.materiel_name or "").strip() or None))

    # 只作为父节点出现的虚拟装配件，从子件记录里的父节点名称还原名称。
    all_names = sorted(direct_names | referenced_names)
    return HierarchyItemDetailRes(
        item_code=item_code,
        item_name=min(direct_names) if direct_names else (all_names[0] if all_names else None),
        item_names=all_names,
        vehicle_batches=sorted(vehicles),
        parent_parts=[
            SearchHierarchyPart(item_code=code, item_name=name)
            for code, name in sorted(parents, key=lambda part: (part[0], part[1] or ""))
        ],
        child_parts=[
            SearchHierarchyPart(item_code=code, item_name=name)
            for code, name in sorted(children, key=lambda part: (part[0], part[1] or ""))
        ],
    )
