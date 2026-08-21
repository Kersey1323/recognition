from pathlib import Path


def test_phase_seventeen_target_module_directories_exist():
    expected_paths = [
        "csrcqsf/modules/railway_parts/integrations/__init__.py",
        "csrcqsf/modules/railway_parts/integrations/reconstruction_client.py",
        "csrcqsf/modules/railway_parts/integrations/milvus_state_manager.py",
        "csrcqsf/modules/railway_parts/repositories/item_repository.py",
        "csrcqsf/modules/railway_parts/repositories/reconstruction_repository.py",
        "csrcqsf/modules/railway_parts/repositories/upload_repository.py",
        "csrcqsf/modules/railway_parts/utils/__init__.py",
        "csrcqsf/modules/railway_parts/utils/local_file_part_reader.py",
        "csrcqsf/modules/railway_parts/utils/local_upload_storage.py",
        "csrcqsf/modules/sgo/services.py",
        "csrcqsf/modules/sgo/repositories.py",
        "csrcqsf/modules/doc_parse/services.py",
        "csrcqsf/models/orm/__init__.py",
        "csrcqsf/models/orm/item.py",
        "csrcqsf/models/orm/files.py",
        "csrcqsf/models/orm/search_history.py",
        "csrcqsf/models/orm/reconstruction.py",
        "csrcqsf/models/orm/reconstruction_upload.py",
        "csrcqsf/models/orm/sgo.py",
    ]

    for relative_path in expected_paths:
        assert Path(relative_path).exists(), relative_path


def test_phase_seventeen_runtime_layers_use_target_modules_instead_of_legacy_runtime_imports():
    target_expectations = {
        "csrcqsf/core/app.py": (
            "from csrcqsf.modules.image.services import SegmentBiz",
            "from csrcqsf.modules.sgo.services import SGOBiz",
        ),
        "csrcqsf/core/scheduler.py": (
            "from csrcqsf.modules.railway_parts.services.reconstruction_sync_service import (",
        ),
        "csrcqsf/modules/doc_parse/routes.py": (
            "from csrcqsf.modules.doc_parse.services import DocBiz",
        ),
        "csrcqsf/modules/image/routes.py": (
            "from csrcqsf.modules.image.services import SegmentBiz",
            "from csrcqsf.core.runtime import ensure_ocr_model_enabled",
        ),
        "csrcqsf/modules/sgo/routes.py": (
            "from csrcqsf.modules.sgo.services import SGOBiz",
            "from csrcqsf.modules.sgo.repositories import SgoItemImages",
        ),
        "csrcqsf/modules/railway_parts/routes/parts_routes.py": (
            "from csrcqsf.modules.sgo.services import SGOBiz",
        ),
        "csrcqsf/modules/railway_parts/routes/search_routes.py": (
            "from csrcqsf.core.runtime import ensure_vector_models_enabled",
        ),
        "csrcqsf/modules/railway_parts/routes/reconstruction_routes.py": (
            "from csrcqsf.core.runtime import ensure_gpu_reconstruction_enabled",
        ),
        "csrcqsf/modules/railway_parts/services/reconstruction_service.py": (
            "from csrcqsf.modules.railway_parts.integrations.reconstruction_client import (",
            "from csrcqsf.modules.railway_parts.utils.local_upload_storage import LocalUploadStorage",
            "from csrcqsf.modules.railway_parts.utils.local_file_part_reader import LocalFilePartReader",
        ),
        "csrcqsf/modules/railway_parts/services/parts_service.py": (
            "from csrcqsf.modules.railway_parts.integrations.milvus_state_manager import (",
            "from csrcqsf.infra.db.mdp_db import sgo_sessionLocal",
            "from csrcqsf.models.orm.item import Items, ItemsParent",
            "from csrcqsf.models.orm.sgo_external import SgoCodeInquiryReturn",
        ),
        "csrcqsf/modules/railway_parts/vector_search/storage/milvus_manager.py": (
            "from csrcqsf.infra.external.model_client import get_model_client",
        ),
        "csrcqsf/modules/railway_parts/vector_search/indexing/indexer.py": (
            "from csrcqsf.infra.external.model_client import get_model_client, ModelServiceClient",
        ),
    }

    forbidden_fragments = (
        "from csrcqsf.runtime import",
        "import csrcqsf.runtime",
        "from csrcqsf.data.",
        "import csrcqsf.data.",
        "from csrcqsf.biz.doc_parse import",
        "from csrcqsf.biz.sgo import",
        "from csrcqsf.biz.railwayparts.reconstruction_client import",
        "from csrcqsf.biz.railwayparts.local_upload_storage import",
        "from csrcqsf.biz.railwayparts.local_file_part_reader import",
        "from csrcqsf.models.orm.item import *",
    )

    for relative_path, expected_fragments in target_expectations.items():
        text = Path(relative_path).read_text(encoding="utf-8")
        for fragment in expected_fragments:
            assert fragment in text, f"{relative_path} missing {fragment}"
        for fragment in forbidden_fragments:
            assert fragment not in text, f"{relative_path} still imports {fragment}"


def test_phase_seventeen_legacy_runtime_modules_no_longer_required_after_module_cutover():
    removed_paths = [
        "csrcqsf/biz/railwayparts/reconstruction_client.py",
        "csrcqsf/biz/railwayparts/reconstruction_sync_manager.py",
        "csrcqsf/biz/railwayparts/local_file_part_reader.py",
        "csrcqsf/biz/railwayparts/local_upload_storage.py",
    ]

    for relative_path in removed_paths:
        assert not Path(relative_path).exists(), relative_path
