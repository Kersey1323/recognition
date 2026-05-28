from pathlib import Path


def test_reconstruction_server_tasks_no_longer_persist_main_db_results():
    text = Path("csrcqsf/biz/railwayparts/reconstruction_server/tasks.py").read_text(encoding="utf-8")

    assert "persist_task_result_by_task_id" not in text
    assert "_finalize_reconstruction_result" not in text


def test_reconstruction_server_train_result_keeps_ply_path_as_output_contract():
    text = Path("csrcqsf/biz/railwayparts/reconstruction_server/tasks.py").read_text(encoding="utf-8")

    assert '"ply_path": result_ply_path' in text
    assert '"elapsed_sec": round(elapsed, 1)' in text


def test_reconstruction_server_subprocesses_detach_stdin_from_terminal():
    text = Path("csrcqsf/biz/railwayparts/reconstruction_server/tasks.py").read_text(encoding="utf-8")

    assert "stdin=subprocess.DEVNULL" in text
