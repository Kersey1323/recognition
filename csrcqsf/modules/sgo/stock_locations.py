"""按配件编码保留库存的全部位置，并生成列表展示字段。"""


def build_stock_locations(item_id_by_code: dict[str, int], rows) -> dict[int, dict]:
    locations_by_item: dict[int, set[tuple[str, str, str]]] = {}
    for code, warehouse, warehouse_name, location in rows:
        item_id = item_id_by_code.get(str(code or "").strip().casefold())
        warehouse = str(warehouse or "").strip()
        location = str(location or "").strip()
        if item_id is None or not warehouse or not location:
            continue
        # 批次和供应商不同不会产生新的货位；相同库区、名称、货位只保留一组。
        locations_by_item.setdefault(item_id, set()).add(
            (warehouse, str(warehouse_name or "").strip(), location)
        )
    snapshot = {}
    for item_id, locations in locations_by_item.items():
        entries = [
            {"LGORT": warehouse, "LGORTD": name or None, "GRARD": location}
            for warehouse, name, location in sorted(locations)
        ]
        snapshot[item_id] = {
            key: ",".join(sorted({entry[key] for entry in entries if entry[key]})) or None
            for key in ("LGORT", "LGORTD", "GRARD")
        }
        snapshot[item_id]["stock_locations"] = entries
    return snapshot
