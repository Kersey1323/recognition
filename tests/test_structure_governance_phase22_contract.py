from pathlib import Path


def test_phase_twenty_two_compat_files_are_removed():
    removed_paths = [
        "csrcqsf/biz/__init__.py",
        "csrcqsf/biz/railwayparts/__init__.py",
        "csrcqsf/biz/doc_parse.py",
        "csrcqsf/biz/segment.py",
        "csrcqsf/biz/sgo.py",
        "csrcqsf/biz/railwayparts/api_models.py",
        "csrcqsf/biz/railwayparts/reconstruction_api_models.py",
        "csrcqsf/biz/railwayparts/auto_processor.py",
        "csrcqsf/biz/railwayparts/local_file_part_reader.py",
        "csrcqsf/biz/railwayparts/local_upload_storage.py",
        "csrcqsf/biz/railwayparts/milvus.py",
        "csrcqsf/biz/railwayparts/reconstruction_client.py",
        "csrcqsf/biz/railwayparts/reconstruction_sync_manager.py",
        "csrcqsf/models/files.py",
        "csrcqsf/models/item.py",
        "csrcqsf/models/reconstruction.py",
        "csrcqsf/models/reconstruction_upload.py",
        "csrcqsf/models/search_history.py",
        "csrcqsf/models/sgo.py",
        "csrcqsf/compat/__init__.py",
        "csrcqsf/compat/railwayparts_parts.py",
        "csrcqsf/compat/reconstruction_manager.py",
        "csrcqsf/compat/services_parts.py",
    ]

    for relative_path in removed_paths:
        assert not Path(relative_path).exists(), relative_path


def test_phase_twenty_two_tests_and_scripts_use_final_module_paths():
    target_paths = [
        "scripts/data_processing/sync_image_all.py",
        "scripts/data_processing/sync_v2_index_state.py",
        "scripts/testing/check_running_tasks.py",
        "scripts/testing/feature_test.py",
        "tests/test_item_measurements.py",
        "tests/test_item_upload_and_update_models.py",
        "tests/test_list_items_v2_compat_manager.py",
        "tests/test_list_items_v2_compat_models.py",
        "tests/test_local_file_part_reader.py",
        "tests/test_local_upload_storage.py",
        "tests/test_milvus_v2_full.py",
        "tests/test_milvus_v2_integration.py",
        "tests/test_reconstruction_api_models.py",
        "tests/test_reconstruction_manager_helpers.py",
        "tests/test_reconstruction_multipart_upload.py",
        "tests/test_reconstruction_record_helpers.py",
        "tests/test_reconstruction_remote_bridge.py",
        "tests/test_reconstruction_remote_client.py",
        "tests/test_reconstruction_scheduler.py",
        "tests/test_reconstruction_statistics.py",
        "tests/test_reconstruction_task_finalization.py",
        "tests/test_reconstruction_upload_session.py",
        "tests/test_sam3_preprocessor_visual.py",
        "tests/test_search_history_storage_config.py",
        "tests/test_segmented_image_model.py",
        "tests/test_v2_index_rebuild_route.py",
        "tests/test_v2_search_history_manager.py",
        "tests/test_v2_search_history_models.py",
        "tests/test_v2_search_history_review_manager.py",
        "tests/test_v2_search_history_review_models.py",
        "tests/test_v2_search_review_ticket_manager.py",
        "tests/test_v2_search_route_contract.py",
    ]

    forbidden_fragments = (
        "from csrcqsf.biz.sgo import",
        "from csrcqsf.biz.segment import",
        "from csrcqsf.biz.doc_parse import",
        "from csrcqsf.biz.railwayparts.api_models import",
        "from csrcqsf.biz.railwayparts.reconstruction_api_models import",
        "from csrcqsf.biz.railwayparts.auto_processor import",
        "from csrcqsf.biz.railwayparts.local_file_part_reader import",
        "from csrcqsf.biz.railwayparts.local_upload_storage import",
        "from csrcqsf.biz.railwayparts.milvus import",
        "from csrcqsf.biz.railwayparts.reconstruction_client import",
        "from csrcqsf.biz.railwayparts.reconstruction_sync_manager import",
        "from csrcqsf.models.files import",
        "from csrcqsf.models.item import",
        "from csrcqsf.models.reconstruction import",
        "from csrcqsf.models.reconstruction_upload import",
        "from csrcqsf.models.search_history import",
        "from csrcqsf.models.sgo import",
        "from csrcqsf.biz.railwayparts.parts import",
    )

    for relative_path in target_paths:
        text = Path(relative_path).read_text(encoding="utf-8")
        for fragment in forbidden_fragments:
            assert fragment not in text, f"{relative_path} still imports {fragment}"


def test_phase_twenty_two_scripts_and_tests_reference_target_modules():
    expected_fragments = {
        "scripts/data_processing/sync_image_all.py": "from csrcqsf.modules.sgo.services import SGOBiz",
        "scripts/data_processing/sync_v2_index_state.py": "from csrcqsf.modules.railway_parts.services.parts_service import RailwayPartsManager",
        "tests/test_local_file_part_reader.py": "from csrcqsf.modules.railway_parts.utils.local_file_part_reader import LocalFilePartReader",
        "tests/test_local_upload_storage.py": "from csrcqsf.modules.railway_parts.utils.local_upload_storage import LocalUploadStorage",
        "tests/test_reconstruction_remote_client.py": "from csrcqsf.modules.railway_parts.integrations.reconstruction_client import ReconstructionServiceClient",
        "tests/test_reconstruction_scheduler.py": "from csrcqsf.modules.railway_parts.services.reconstruction_sync_service import ReconstructionSyncManager",
        "tests/test_search_history_storage_config.py": "from csrcqsf.models.orm.search_history import SearchHistory",
        "tests/test_segmented_image_model.py": "from csrcqsf.models.orm.sgo import SegmentedImage",
    }

    for relative_path, fragment in expected_fragments.items():
        text = Path(relative_path).read_text(encoding="utf-8")
        assert fragment in text, f"{relative_path} missing {fragment}"
