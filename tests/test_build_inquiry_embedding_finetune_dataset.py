import importlib.util
from datetime import datetime
from pathlib import Path

import numpy as np


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts/experiments/build_inquiry_embedding_finetune_dataset.py"
)


def _load_module():
    assert SCRIPT_PATH.exists(), "微调数据集构建器尚未实现"
    spec = importlib.util.spec_from_file_location("bge_finetune_dataset", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _record(module, history_id, vehicle, item_code, description, inquiry_time):
    return module.InquiryRecord(
        history_id=history_id,
        inquiry_num=f"Q{history_id}",
        vehicle=vehicle,
        item_code=item_code,
        description=description,
        inquiry_time=datetime.fromisoformat(inquiry_time),
    )


def test_normalize_key_text_unifies_width_case_and_whitespace():
    module = _load_module()

    assert module.normalize_key_text(" sfe１  \n 窗帘 ") == "SFE1 窗帘"


def test_find_ambiguous_descriptions_only_conflicts_within_same_vehicle():
    module = _load_module()
    records = [
        _record(module, 1, "SFE1", "A", "窗帘", "2025-01-01"),
        _record(module, 2, "SFE1", "B", "窗帘", "2025-01-02"),
        _record(module, 3, "SFE2", "B", "窗帘", "2025-01-03"),
    ]

    assert module.find_ambiguous_vehicle_descriptions(records) == {("SFE1", "窗帘")}


def test_find_globally_ambiguous_descriptions_includes_cross_vehicle_conflicts():
    module = _load_module()
    records = [
        _record(module, 1, "SFE1", "A", "窗帘", "2025-01-01"),
        _record(module, 2, "SFE2", "B", "窗帘", "2025-01-02"),
        _record(module, 3, "SFE3", "B", "垃圾箱盖板", "2025-01-03"),
    ]

    assert module.find_globally_ambiguous_descriptions(records) == {"窗帘"}


def test_build_training_examples_uses_distinct_positive_and_same_vehicle_negative():
    module = _load_module()
    records = [
        _record(module, 1, "SFE1", "A", "右侧遮阳帘挂钩", "2025-01-01"),
        _record(module, 2, "SFE2", "A", "遮阳帘固定钩", "2025-01-02"),
        _record(module, 3, "SFE1", "B", "左侧遮阳帘挂钩", "2025-01-03"),
        _record(module, 4, "SFE1", "C", "垃圾箱合页", "2025-01-04"),
    ]
    vectors = {
        1: np.array([1.0, 0.0], dtype=np.float32),
        2: np.array([0.8, 0.2], dtype=np.float32),
        3: np.array([0.9, 0.1], dtype=np.float32),
        4: np.array([0.0, 1.0], dtype=np.float32),
    }

    examples, metadata = module.build_training_examples(
        records,
        vectors,
        max_queries_per_code=1,
        positive_count=1,
        hard_negative_count=1,
        random_negative_count=0,
        seed=7,
    )

    assert examples == [
        {
            "query": "右侧遮阳帘挂钩",
            "pos": ["遮阳帘固定钩"],
            "neg": ["左侧遮阳帘挂钩"],
        }
    ]
    assert metadata[0]["item_code"] == "A"
    assert metadata[0]["negative_item_codes"] == ["B"]


def test_build_validation_queries_only_uses_new_descriptions_for_known_codes():
    module = _load_module()
    cutoff = datetime(2026, 1, 15)
    records = [
        _record(module, 1, "SFE1", "A", "遮阳帘固定钩", "2025-01-01"),
        _record(module, 2, "SFE1", "A", "右侧遮阳帘挂钩", "2026-02-01"),
        _record(module, 3, "SFE1", "A", "遮阳帘固定钩", "2026-02-02"),
        _record(module, 4, "SFE1", "B", "垃圾箱合页", "2026-02-03"),
        _record(module, 5, "SFE2", "C", "餐车桌板", "2025-01-04"),
        _record(module, 6, "SFE1", "C", "小桌板", "2026-02-04"),
    ]

    validation = module.build_validation_queries(records, cutoff)

    assert validation == [
        {
            "history_id": 2,
            "inquiry_num": "Q2",
            "vehicle": "SFE1",
            "query": "右侧遮阳帘挂钩",
            "target_item_code": "A",
        }
    ]


def test_build_validation_queries_excludes_queries_seen_by_training_model():
    module = _load_module()
    cutoff = datetime(2026, 1, 15)
    records = [
        _record(module, 1, "SFE1", "A", "遮阳帘固定钩", "2025-01-01"),
        _record(module, 2, "SFE1", "A", "右侧遮阳帘挂钩", "2026-02-01"),
    ]

    validation = module.build_validation_queries(
        records,
        cutoff,
        excluded_query_targets={("右侧遮阳帘挂钩", "A")},
    )

    assert validation == []


def test_build_mixed_training_examples_uses_cross_vehicle_and_lexical_negatives():
    module = _load_module()
    records = [
        _record(module, 1, "SFE1", "A", "监控室对面窗帘", "2025-01-01"),
        _record(module, 2, "SFE2", "A", "司机室后方侧窗遮阳帘", "2025-01-02"),
        _record(module, 3, "SFE1", "B", "监控室窗帘滑道", "2025-01-03"),
        _record(module, 4, "SFE3", "C", "司机室侧窗窗帘", "2025-01-04"),
        _record(module, 5, "SFE4", "D", "对面窗帘固定卡", "2025-01-05"),
        _record(module, 6, "SFE5", "E", "卫生间垃圾箱", "2025-01-06"),
    ]
    vectors = {
        1: np.array([1.0, 0.0], dtype=np.float32),
        2: np.array([0.9, 0.1], dtype=np.float32),
        3: np.array([0.8, 0.2], dtype=np.float32),
        4: np.array([0.7, 0.3], dtype=np.float32),
        5: np.array([0.6, 0.4], dtype=np.float32),
        6: np.array([0.0, 1.0], dtype=np.float32),
    }

    examples, metadata = module.build_mixed_training_examples(
        records,
        vectors,
        global_rankings={1: [records[3], records[4], records[5]]},
        max_queries_per_code=1,
        positive_count=1,
        same_vehicle_hard_count=1,
        cross_vehicle_hard_count=1,
        lexical_hard_count=1,
        random_negative_count=1,
        seed=7,
    )

    assert examples[0] == {
        "query": "监控室对面窗帘",
        "pos": ["司机室后方侧窗遮阳帘"],
        "neg": [
            "监控室窗帘滑道",
            "司机室侧窗窗帘",
            "对面窗帘固定卡",
            "卫生间垃圾箱",
        ],
    }
    assert metadata[0]["negative_types"] == [
        "same_vehicle_dense",
        "cross_vehicle_dense",
        "lexical_hard",
        "global_random",
    ]
