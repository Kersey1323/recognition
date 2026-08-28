import importlib.util
from pathlib import Path
import sys


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts/experiments/validate_inquiry_text_embeddings.py"
)
SPEC = importlib.util.spec_from_file_location("validate_inquiry_text_embeddings", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
evaluate_labeled_thresholds = MODULE.evaluate_labeled_thresholds


def test_threshold_evaluation_reports_positive_and_negative_metrics():
    cases = [
        {
            "query": "监控室对面窗帘",
            "expected_item_ids": [1],
            "top_results": [{"item_id": 1, "score": 0.91}],
        },
        {
            "query": "完全无关的描述",
            "expected_item_ids": [],
            "top_results": [{"item_id": 2, "score": 0.52}],
        },
        {
            "query": "车下的过滤部件",
            "expected_item_ids": [3],
            "top_results": [{"item_id": 4, "score": 0.80}],
        },
    ]

    report = evaluate_labeled_thresholds(cases, thresholds=[0.55, 0.85])

    assert report[0] == {
        "threshold": 0.55,
        "true_positive": 1,
        "false_positive": 1,
        "true_negative": 1,
        "false_negative": 1,
        "precision": 0.5,
        "recall": 0.5,
        "false_positive_rate": 0.5,
    }
    assert report[1]["threshold"] == 0.85
    assert report[1]["false_positive"] == 0
    assert report[1]["recall"] == 0.5


def test_threshold_evaluation_always_includes_production_default():
    report = evaluate_labeled_thresholds([], thresholds=[0.6])

    assert [row["threshold"] for row in report] == [0.55, 0.6]
