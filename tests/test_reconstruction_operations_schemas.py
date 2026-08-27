import pytest
from pydantic import ValidationError

from csrcqsf.modules.railway_parts.schemas.reconstruction_operations import (
    ReconstructionRecoveryMode,
    ReconstructionRecoveryPlanRes,
    ReconstructionRecoveryReq,
)


def test_recovery_request_contains_only_mode_and_reason():
    request = ReconstructionRecoveryReq(mode="auto", reason="人工确认环境恢复")

    assert request.dict() == {
        "mode": ReconstructionRecoveryMode.AUTO,
        "reason": "人工确认环境恢复",
    }


@pytest.mark.parametrize("field", ["iterations", "video_path", "output_name"])
def test_recovery_request_rejects_task_creation_fields(field):
    with pytest.raises(ValidationError, match="extra fields not permitted"):
        ReconstructionRecoveryReq(**{field: 10000})


def test_recovery_reason_is_limited_to_500_characters():
    with pytest.raises(ValidationError, match="reason"):
        ReconstructionRecoveryReq(reason="x" * 501)


@pytest.mark.parametrize("mode", [None, *list(ReconstructionRecoveryMode)])
def test_recovery_plan_accepts_only_known_recommended_modes(mode):
    payload = {
        "task_id": "task-1",
        "can_recover": True,
        "recommended_mode": mode,
        "resume_from": "train",
        "last_successful_stage": "alignment",
        "reused_stages": ["alignment"],
        "latest_checkpoint": None,
        "reason": "ok",
    }

    result = ReconstructionRecoveryPlanRes(**payload)

    assert result.recommended_mode == mode


def test_recovery_plan_rejects_unknown_recommended_mode():
    with pytest.raises(ValidationError, match="recommended_mode"):
        ReconstructionRecoveryPlanRes(
            task_id="task-1",
            can_recover=True,
            recommended_mode="unknown",
        )
