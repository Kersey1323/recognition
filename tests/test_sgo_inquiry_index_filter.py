from csrcqsf.modules.railway_parts.integrations.milvus_state_manager import (
    MilvusStateManagerV2,
)


def test_index_state_manager_can_return_complete_indexed_item_set():
    manager = object.__new__(MilvusStateManagerV2)
    manager.get_item_index_state_snapshot = lambda: {
        103: {"has_v2_index": 1},
        101: {"has_v2_index": 1},
        102: {"has_v2_index": 0},
    }

    assert manager.get_all_indexed_item_id_list(page=-1, limit=0) == [101, 103]
