import importlib

import pytest


@pytest.mark.parametrize(
    ("module_name", "symbols"),
    [
        (
            "csrcqsf.modules.railway_parts.services.reconstruction_task_service",
            [
                "ReconstructionStatus",
                "ReconstructionRecord",
                "SessionLocal",
                "Items",
                "logger",
                "reconstruction_sam2_model_path",
                "reconstruction_server_env_configured",
                "_get_minio_helpers",
                "map_celery_state_to_reconstruction_status",
                "ReconstructionBusinessError",
                "ReconstructionServiceClientError",
            ],
        ),
        (
            "csrcqsf.modules.railway_parts.services.parts_search_service",
            [
                "SessionLocal",
                "SearchItem",
                "SearchHistory",
                "SearchResults",
                "SearchReviewTicket",
                "logger",
                "_get_milvus_manager_v2_cls",
                "_get_minio_helpers",
                "minio_search_history_bucket",
            ],
        ),
        (
            "csrcqsf.modules.railway_parts.services.reconstruction_video_service",
            [
                "get_id",
                "Part",
                "SessionLocal",
                "Items",
                "ReconstructionVideoUploadSession",
                "ReconstructionBusinessError",
                "LocalFilePartReader",
                "_get_minio_helpers",
                "minio_reconstruction_video_bucket",
            ],
        ),
    ],
)
def test_split_service_modules_expose_runtime_placeholders(module_name, symbols):
    module = importlib.import_module(module_name)
    missing = [symbol for symbol in symbols if not hasattr(module, symbol)]
    assert not missing
