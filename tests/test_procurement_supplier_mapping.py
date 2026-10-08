from types import SimpleNamespace as Row

from csrcqsf.models.supplier_mapping import merge_procurement_suppliers


def test_procurement_respects_tenant_scope_and_official_relationships():
    templates = [Row(id="1", MATNR="A", tenant_id_="t"),
                 Row(id="2", MATNR="A", tenant_id_="t")]
    official = [Row(id="s1", masterplate_id="1", supplier_code="S")]
    def purchase(id, code="A", supplier="NEW", tenant="t"):
        return Row(id=id, materiel_code=code, supplier_code=supplier,
                   supplier_name="Supplier", tenant_id_=tenant)
    rows = merge_procurement_suppliers(official, [
        purchase("10", supplier="S"), purchase("11"), purchase("9"),
        purchase("12", code="NON-A1"), purchase("13", tenant="other"),
        purchase("14", supplier=" "),
    ], templates)
    assert rows[0] is official[0]
    assert len(rows) == 2
    assert rows[1].id == "procure:11"
    assert rows[1].masterplate_id == "2"
    assert rows[1].current_status == "procurement_history"


def test_official_relationship_replaces_historical_supplement():
    template = Row(id="1", MATNR="A", tenant_id_="t")
    purchase = Row(id="11", materiel_code="A", supplier_code="S",
                   supplier_name="Supplier", tenant_id_="t")
    assert len(merge_procurement_suppliers([], [purchase], [template])) == 1
    official = Row(id="s1", masterplate_id="1", supplier_code="S")
    assert merge_procurement_suppliers([official], [purchase], [template]) == [official]
