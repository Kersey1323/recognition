"""Typed contracts for task-scoped reconstruction operations."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class _StrictModel(BaseModel):
    class Config:
        extra = "forbid"


class ReconstructionRecoveryMode(str, Enum):
    AUTO = "auto"
    COLMAP = "colmap"
    ALIGNMENT = "alignment"
    RESUME_TRAINING = "resume_training"
    RESTART_TRAINING = "restart_training"
    RENDER = "render"
    METRICS = "metrics"


class ReconstructionRecoveryReq(_StrictModel):
    mode: ReconstructionRecoveryMode = ReconstructionRecoveryMode.AUTO
    reason: str | None = Field(None, max_length=500)


class ReconstructionRecoveryPlanRes(_StrictModel):
    task_id: str
    can_recover: bool
    recommended_mode: ReconstructionRecoveryMode | None = None
    resume_from: str | None = None
    last_successful_stage: str | None = None
    reused_stages: list[str] = Field(default_factory=list)
    latest_checkpoint: str | None = None
    reason: str | None = None


class ReconstructionRecoverySubmitRes(_StrictModel):
    task_id: str
    recovery_task_id: str
    recovery_attempt: int
    mode: ReconstructionRecoveryMode
    resume_from: str | None = None
    status: str


class ReconstructionDiagnosticArtifactRes(_StrictModel):
    relative_path: str
    kind: str
    size_bytes: int = Field(ge=0)
    modified_at: str | None = None
    download_url: str


class ReconstructionDiagnosticsRes(_StrictModel):
    task_id: str
    status: str
    current_stage: str | None = None
    file_count: int = Field(default=0, ge=0)
    total_size_bytes: int = Field(default=0, ge=0)
    camera_count: int | None = Field(default=None, ge=0)
    log_download_url: str
    diagnostics_download_url: str
    key_artifacts: list[ReconstructionDiagnosticArtifactRes] = Field(default_factory=list)


class ReconstructionOutputOperationRes(_StrictModel):
    task_id: str
    status: str
    directory_name: str
    file_count: int = Field(ge=0)
    size_bytes: int = Field(ge=0)
    deleted: bool
    confirmation_required: bool
