from pathlib import Path


SCAN_FILES = [
    Path("tests/test_reconstruction_server_api_contract.py"),
    Path("tests/test_reconstruction_server_task_result_contract.py"),
    Path("tests/test_reconstruction_turntable_diagnostics.py"),
    Path("tests/test_reconstruction_turntable_foreground_prototype.py"),
    Path("tests/test_reconstruction_turntable_holdout_eval.py"),
    Path("scripts/testing/test_celery_progress.py"),
    Path("scripts/testing/test_celery_redis.py"),
    Path("test_support/reconstruction_turntable_holdout_support.py"),
]


def test_main_repo_has_no_embedded_reconstruction_server_specific_tests_or_scripts():
    assert all(not path.exists() for path in SCAN_FILES)
