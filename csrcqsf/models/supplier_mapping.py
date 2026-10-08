"""Merge historical procurement relationships without replacing maintained suppliers."""

from types import SimpleNamespace


PROCURE_SOURCE_PREFIX = "procure:"


def key(value):
    return str(value or "").strip().casefold()


def merge_procurement_suppliers(official, procurement, templates):
    by_id = {str(row.id): row for row in templates}
    by_code = {}
    for row in sorted(templates, key=lambda row: int(row.id), reverse=True):
        if key(row.MATNR):
            by_code.setdefault((key(row.tenant_id_), key(row.MATNR)), row)
    seen = set()
    for row in official:
        template = by_id.get(str(row.masterplate_id))
        if template is not None:
            seen.add((key(template.tenant_id_), key(template.MATNR), key(row.supplier_code)))

    result = list(official)
    # 正式维护关系优先；采购历史按更新时间倒序输入，同编码供方仅补充最新一条。
    for row in procurement:
        pair = (key(row.tenant_id_), key(row.materiel_code), key(row.supplier_code))
        template = by_code.get(pair[:2])
        if template is None or not pair[2] or pair in seen:
            continue
        seen.add(pair)
        result.append(SimpleNamespace(
            id=PROCURE_SOURCE_PREFIX + str(row.id),
            masterplate_id=str(template.id),
            supplier_code=str(row.supplier_code).strip(),
            supplier_name=str(row.supplier_name or "").strip() or None,
            supplier_matnr=None, supplier_maktx=None, supplier_wrkst=None,
            model_number=None, manufacturer=None,
            # 历史成交关系可展示，但不冒充已发布或首选供应商。
            current_status="procurement_history", enable_status="normal",
        ))
    return result
