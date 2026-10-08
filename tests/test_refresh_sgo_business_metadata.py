from scripts.data_processing.refresh_sgo_business_metadata import plan_updates


def test_refreshes_old_source_values_but_preserves_operator_edits():
    old = {"a": ("旧名称", "旧规格", "旧图号", None)}
    new = {"a": ("新名称", "新规格", "新图号", "钢")}
    business = [(1, "A", "旧名称", "人工规格", "旧图号", None)]

    updates, counts = plan_updates(business, old, new)

    assert updates == [
        ("新名称", "人工规格", "新图号", "钢", 1, "A", "旧名称", "人工规格", "旧图号", None)
    ]
    assert counts["changed_items"] == 1
    assert counts["preserved_parts_model"] == 1


def test_new_codes_only_fill_empty_fields_and_unrelated_items_remain_untouched():
    new = {"a": ("新名称", "新规格", None, None)}
    business = [
        (1, "A", "人工名称", None, None, None),
        (2, "B", "其他配件", None, None, None),
    ]

    updates, counts = plan_updates(business, {}, new)

    assert updates == [("人工名称", "新规格", None, None, 1, "A", "人工名称", None, None, None)]
    assert counts["outside_new_source"] == 1
