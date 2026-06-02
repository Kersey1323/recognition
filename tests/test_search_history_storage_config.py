from unittest.mock import call, patch

from csrcqsf.infra.storage import minio as minio_module
from csrcqsf.models.orm.search_history import SearchHistory
from csrcqsf.core.settings import minio_search_history_bucket


def test_search_history_table_has_explicit_query_columns():
    columns = list(SearchHistory.__table__.columns.keys())

    assert "query_text" in columns
    assert "query_image" in columns
    assert "query_images_json" in columns


def test_create_minio_buckets_sync_includes_search_history_bucket():
    with patch.object(minio_module, "ensure_minio_bucket") as ensure_bucket:
        minio_module.create_minio_buckets_sync()

    assert call(minio_search_history_bucket) in ensure_bucket.call_args_list
