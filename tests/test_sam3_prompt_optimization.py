from unittest.mock import patch

import numpy as np
from PIL import Image

from csrcqsf.biz.railwayparts.vector_db.preprocessing.sam3_preprocessor import (
    SAM3Preprocessor,
)


def _preprocessor_without_model():
    preprocessor = object.__new__(SAM3Preprocessor)
    preprocessor.mask_dilate = 0
    preprocessor.bg_color = "white"
    preprocessor.device = "cpu"
    preprocessor.save_debug_images = False
    preprocessor.debug_output_dir = "logs/vector_db/test"
    return preprocessor


def test_normalize_item_name_for_prompt_strips_direction_version_and_size_noise():
    preprocessor = _preprocessor_without_model()

    assert preprocessor.normalize_item_name_for_prompt("特殊螺栓M10X40") == "特殊螺栓"
    assert preprocessor.normalize_item_name_for_prompt("自动高度调整阀(右)A") == "自动高度调整阀"
    assert preprocessor.normalize_item_name_for_prompt("90°弯头DN15") == "90°弯头"
    assert preprocessor.normalize_item_name_for_prompt("司机室隔门锁左") == "司机室隔门锁"


def test_sanitize_prompt_candidates_dedupes_and_normalizes_case():
    preprocessor = _preprocessor_without_model()

    assert preprocessor._sanitize_prompt_candidates(
        ["Bolt", " bolt ", "", "door lock", "Door Lock", "object"]
    ) == ["bolt", "door lock", "object"]


def test_fallback_prompt_candidates_append_object_once():
    preprocessor = _preprocessor_without_model()

    with patch.object(preprocessor, "_fallback_translate", return_value="bracket"):
        assert preprocessor._fallback_prompt_candidates("左支座") == [
            "bracket",
            "object",
        ]


def test_preprocess_image_with_metadata_retries_until_a_candidate_succeeds():
    preprocessor = _preprocessor_without_model()
    preprocessor.generate_prompt_candidates = lambda _item_name: ["support", "bracket"]
    preprocessor._segment_with_prompt = lambda _image, prompt: (
        None
        if prompt == "support"
        else (Image.new("RGB", (4, 4), "white"), np.ones((4, 4), dtype=np.uint8))
    )

    outcome = preprocessor.preprocess_image_with_metadata(
        image=Image.new("RGB", (8, 8), "white"),
        item_name="左支座",
        image_id=9001,
    )

    assert outcome.selected_prompt == "bracket"
    assert outcome.prompt_candidates == ["support", "bracket"]
    assert outcome.attempt_count == 2
    assert outcome.result_image is not None


def test_preprocess_image_wrapper_returns_only_result_image():
    preprocessor = _preprocessor_without_model()
    expected = Image.new("RGB", (4, 4), "white")

    class _Outcome:
        result_image = expected

    preprocessor.preprocess_image_with_metadata = lambda **_kwargs: _Outcome()

    result = preprocessor.preprocess_image(
        image=Image.new("RGB", (8, 8), "white"),
        item_name="特殊螺栓",
        image_id=9002,
    )

    assert result is expected
