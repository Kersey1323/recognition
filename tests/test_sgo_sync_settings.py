def test_bounded_env_int_uses_default_and_lower_bound(monkeypatch):
    from csrcqsf.core.settings import _bounded_env_int

    monkeypatch.delenv("TEST_SYNC_SIZE", raising=False)
    assert _bounded_env_int("TEST_SYNC_SIZE", default=30, minimum=1) == 30

    monkeypatch.setenv("TEST_SYNC_SIZE", "0")
    assert _bounded_env_int("TEST_SYNC_SIZE", default=30, minimum=1) == 1

    monkeypatch.setenv("TEST_SYNC_SIZE", "45")
    assert _bounded_env_int("TEST_SYNC_SIZE", default=30, minimum=1) == 45


def test_sgo_image_zip_batch_defaults_to_one():
    from csrcqsf.core.settings import sgo_image_zip_batch_size

    assert sgo_image_zip_batch_size == 1


def test_sgo_image_download_concurrency_defaults_to_four():
    from csrcqsf.core.settings import sgo_image_download_concurrency

    assert sgo_image_download_concurrency == 4


def test_inquiry_text_auto_index_is_enabled_by_default():
    from csrcqsf.core.settings import inquiry_text_auto_index_enabled

    assert inquiry_text_auto_index_enabled is True
