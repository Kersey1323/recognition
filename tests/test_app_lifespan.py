import inspect
import os

os.environ["SGO_KINGBASE_PORT"] = "54321"
os.environ["SGO_MYSQL_PORT"] = "3306"

def test_app_lifespan_manages_viewer360_workers():
    from csrcqsf.core import settings

    settings.ai_settings.sgo_mysql_port = "3306"
    settings.ai_settings.sgo_kingbase_port = "54321"
    from csrcqsf.core import app as app_module

    source = inspect.getsource(app_module.lifespan)
    assert "viewer360_task_manager.start_workers" in source
    assert "viewer360_task_manager.stop_workers" in source
