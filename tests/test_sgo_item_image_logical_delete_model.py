from csrcqsf.models.orm.sgo import SgoItemImages


def test_sgo_item_images_has_logical_delete_columns():
    columns = SgoItemImages.__table__.columns

    assert "is_deleted" in columns
    assert "deleted_at" in columns
    assert "delete_reason" in columns


def test_active_filter_excludes_deleted_images():
    from sqlalchemy import select

    stmt = SgoItemImages.active_filter(select(SgoItemImages))
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))

    assert "is_deleted" in compiled
    assert "= 0" in compiled


def test_get_item_image_statement_uses_item_id_and_image_id():
    stmt = SgoItemImages.get_item_image_stmt(item_id=101, image_id=202)
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))

    assert "item_id = 101" in compiled
    assert "id = 202" in compiled
    assert "is_deleted" in compiled


def test_mark_deleted_statement_sets_logical_delete_fields():
    stmt = SgoItemImages.mark_deleted_stmt(item_id=101, image_id=202, delete_reason="mistake")
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))

    assert "UPDATE" in compiled
    assert "is_deleted" in compiled
    assert "deleted_at" in compiled
    assert "delete_reason" in compiled
    assert "item_id = 101" in compiled
    assert "id = 202" in compiled
