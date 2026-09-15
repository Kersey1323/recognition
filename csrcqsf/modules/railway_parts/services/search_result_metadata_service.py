"""从本地业务库补充检索候选的规格、材质和供应商信息。"""

from __future__ import annotations

from collections import defaultdict

from csrcqsf.models.orm.item import ItemSupplier, Items
from csrcqsf.models.orm.search_history import SearchResultSupplier


async def enrich_search_result_metadata(session, search_results) -> None:
    """批量读取已同步元数据，历史详情不再实时依赖 SGO 数据库。"""
    if search_results is None or not search_results.items:
        return

    result_items_by_id = defaultdict(list)
    for result_item in search_results.items:
        try:
            item_id = int(result_item.item_id)
        except (TypeError, ValueError):
            continue
        result_items_by_id[item_id].append(result_item)

    item_ids = list(result_items_by_id)
    if not item_ids:
        return

    items_by_id = {}
    async for item in Items.get_item_by_id_list(session, item_ids):
        items_by_id[int(item.id)] = item

    suppliers_by_item_id = defaultdict(list)
    for supplier in await ItemSupplier.list_active_by_item_ids(session, item_ids):
        suppliers_by_item_id[int(supplier.item_id)].append(
            SearchResultSupplier(
                supplier_code=supplier.supplier_code,
                supplier_name=supplier.supplier_name,
                supplier_item_code=supplier.supplier_item_code,
                supplier_item_name=supplier.supplier_item_name,
                supplier_parts_model=supplier.supplier_parts_model,
                model_number=supplier.model_number,
                manufacturer=supplier.manufacturer,
            )
        )

    for item_id, result_items in result_items_by_id.items():
        item = items_by_id.get(item_id)
        for result_item in result_items:
            result_item.parts_model = item.parts_model if item is not None else None
            result_item.material_quality = (
                item.material_quality if item is not None else None
            )
            result_item.suppliers = suppliers_by_item_id[item_id]
