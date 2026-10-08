import pytest

from csrcqsf.modules.railway_parts.vector_search.config.env_config import VectorDBConfig


def test_inquiry_semantic_config_defaults(monkeypatch):
    names = (
        "INQUIRY_TEXT_COLLECTION_ALIAS",
        "INQUIRY_TEXT_EMBEDDING_DIM",
        "INQUIRY_TEXT_INDEX_BATCH_SIZE",
        "INQUIRY_TEXT_SEARCH_OVERSAMPLE",
        "INQUIRY_TEXT_SEARCH_MIN_CANDIDATES",
        "INQUIRY_TEXT_SEARCH_MAX_CANDIDATES",
        "INQUIRY_TEXT_MIN_SCORE",
    )
    for name in names:
        monkeypatch.delenv(name, raising=False)

    config = VectorDBConfig()

    assert config.inquiry_text_collection_alias == "PARTS_INQUIRY_BGE_M3_CURRENT"
    assert config.inquiry_text_embedding_dim == 1024
    assert config.inquiry_text_index_batch_size == 128
    assert config.inquiry_text_search_oversample == 5
    assert config.inquiry_text_search_min_candidates == 30
    assert config.inquiry_text_search_max_candidates == 1000
    assert config.inquiry_text_min_score == 0.55


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("INQUIRY_TEXT_EMBEDDING_DIM", "0"),
        ("INQUIRY_TEXT_INDEX_BATCH_SIZE", "-1"),
        ("INQUIRY_TEXT_SEARCH_OVERSAMPLE", "0"),
        ("INQUIRY_TEXT_SEARCH_MIN_CANDIDATES", "0"),
        ("INQUIRY_TEXT_SEARCH_MAX_CANDIDATES", "0"),
        ("INQUIRY_TEXT_MIN_SCORE", "1.1"),
        ("INQUIRY_TEXT_MIN_SCORE", "-1.1"),
    ],
)
def test_inquiry_semantic_config_rejects_invalid_values(monkeypatch, name, value):
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=name):
        VectorDBConfig()
