from csrcqsf.infra.db.main_db import MAIN_DB_MODEL_MODULES
from csrcqsf.models.orm.reconstruction_operation_audit import (
    ReconstructionOperationAudit,
)
from csrcqsf.modules.railway_parts.services.reconstruction_operations_service import (
    _sanitize_summary,
)


def test_reconstruction_operation_audit_has_required_columns_and_indexes():
    columns = ReconstructionOperationAudit.__table__.columns

    assert {
        "operation",
        "operator_id",
        "task_id",
        "item_id",
        "request_summary_json",
        "response_summary_json",
        "success",
        "status_code",
        "error_message",
        "time_created",
    }.issubset(columns.keys())
    index_columns = {
        tuple(column.name for column in index.columns)
        for index in ReconstructionOperationAudit.__table__.indexes
    }
    assert ("task_id", "time_created") in index_columns
    assert ("operation", "time_created") in index_columns


def test_audit_model_is_registered_for_startup_table_creation():
    assert (
        "csrcqsf.models.orm.reconstruction_operation_audit"
        in MAIN_DB_MODEL_MODULES
    )


def test_audit_summary_removes_internal_and_sensitive_values():
    result = _sanitize_summary(
        {
            "mode": "auto",
            "token": "secret-token",
            "output_dir": "/srv/private/task",
            "detail": "see http://reconstruction:8000/debug at /srv/private/task",
        }
    )

    assert result["mode"] == "auto"
    assert "token" not in result
    assert "output_dir" not in result
    assert "http://" not in result["detail"]
    assert "/srv/private" not in result["detail"]
