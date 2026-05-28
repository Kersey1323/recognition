from pathlib import Path


def test_main_repo_no_longer_contains_legacy_reconstruction_package():
    assert not Path("csrcqsf/biz/reconstruction").exists()


def test_main_repo_no_longer_contains_legacy_reconstruction_entrypoints():
    assert not Path("scripts/reconstruction").exists()
    assert not Path("tests/test_mask.py").exists()
