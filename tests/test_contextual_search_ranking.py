from types import SimpleNamespace

from csrcqsf.models.orm.search_history import SearchParameters
from csrcqsf.modules.railway_parts.services.contextual_search_service import (
    rank_contextual_candidates,
)


def _history(item_id: int, **overrides):
    values = {
        "item_id": item_id,
        "vehicle_batch": "SFE27",
        "train_no": None,
        "car_num": None,
        "subordinate_component": None,
        "inquiry_item_name": None,
        "return_item_name": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_name_and_history_context_can_correct_a_visual_only_ranking():
    ranked = rank_contextual_candidates(
        item_ids=[1, 2],
        image_scores={1: 0.76, 2: 0.90},
        text_scores={1: 0.95, 2: 0.10},
        item_names={1: "便器冲洗按钮", 2: "排水球阀"},
        histories_by_item={
            1: [
                _history(
                    1,
                    train_no="2777",
                    car_num="01",
                    subordinate_component="卫生间",
                    inquiry_item_name="便器冲洗按钮",
                    return_item_name="便器冲洗按钮",
                )
            ],
            2: [],
        },
        parameters=SearchParameters(
            vehicle_batch="SFE27",
            item_name="便器冲洗按钮",
            train_no="2777",
            car_num="01",
            subordinate_component="卫生间",
        ),
    )

    assert [row["item_id"] for row in ranked] == [1, 2]
    assert ranked[0]["history_context_score"] == 1.0
    assert ranked[0]["exact_match_score"] == 1.0
    assert ranked[0]["final_score"] > ranked[1]["final_score"]


def test_missing_metadata_layers_reweight_image_score_to_the_full_score():
    ranked = rank_contextual_candidates(
        item_ids=[1, 2],
        image_scores={1: 0.72, 2: 0.91},
        text_scores={},
        item_names={1: "A", 2: "B"},
        histories_by_item={},
        parameters=SearchParameters(vehicle_batch="SFE27"),
    )

    assert [row["item_id"] for row in ranked] == [2, 1]
    assert ranked[0]["final_score"] == 0.91
    assert ranked[1]["final_score"] == 0.72


def test_candidate_without_inquiry_history_remains_in_results():
    ranked = rank_contextual_candidates(
        item_ids=[1],
        image_scores={1: 0.8},
        text_scores={},
        item_names={1: "按钮"},
        histories_by_item={},
        parameters=SearchParameters(train_no="2777"),
    )

    assert len(ranked) == 1
    assert ranked[0]["item_id"] == 1
    assert ranked[0]["history_context_score"] == 0.0
