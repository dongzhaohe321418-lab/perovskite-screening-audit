from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CycleStatus(str, Enum):
    CREATED = "CREATED"
    AUDIT_REQUEST_INVALID = "AUDIT_REQUEST_INVALID"
    CODEX_TASK_CREATED = "CODEX_TASK_CREATED"
    AUDIT_OUTPUT_INVALID = "AUDIT_OUTPUT_INVALID"
    FINAL = "FINAL"


class DispositionStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    TASK_CREATED = "TASK_CREATED"
    INVALID = "INVALID"
    RECORDED = "RECORDED"


class Cycle(BaseModel):
    cycle_id: str
    project_id: str
    science_repo: str
    science_commit: str
    trigger_type: Literal["NEW_SCIENCE_COMMIT"]
    evidence_manifest_sha256: str
    status: CycleStatus = CycleStatus.CREATED
    idempotency_key: str
    audit_request: dict[str, Any] | None = None
    audit_repo_commit: str | None = None
    audit_report_sha256: str | None = None
    audit_report_id: str | None = None
    audit_result: dict[str, Any] | None = None
    disposition_status: DispositionStatus = DispositionStatus.NOT_STARTED
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class ActionCheckRequest(BaseModel):
    project_id: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    action: str = Field(min_length=1)
    science_commit: str
    manifest_sha256: str

    @field_validator("science_commit")
    @classmethod
    def validate_commit(cls, value: str) -> str:
        if len(value) != 40 or any(char not in "0123456789abcdefABCDEF" for char in value):
            raise ValueError("science_commit must be a full 40-character hexadecimal SHA")
        return value.lower()

    @field_validator("manifest_sha256")
    @classmethod
    def validate_manifest_hash(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdefABCDEF" for char in value):
            raise ValueError("manifest_sha256 must be a 64-character hexadecimal SHA-256")
        return value.lower()


class ActionCheckResponse(BaseModel):
    decision: Literal["ALLOW", "DENY"]
    reason_codes: list[str] = Field(default_factory=list)


class ActionAuthorization(BaseModel):
    authorization_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    action: str = Field(min_length=1)
    science_commit: str
    manifest_sha256: str
    policy_approved: bool
    budget_approved: bool
    pi_approved: bool
    approved_by: str = Field(min_length=1)
    expires_at: str
    created_at: str = Field(default_factory=utc_now)

    @field_validator("science_commit")
    @classmethod
    def validate_commit(cls, value: str) -> str:
        if len(value) != 40 or any(char not in "0123456789abcdefABCDEF" for char in value):
            raise ValueError("science_commit must be a full 40-character hexadecimal SHA")
        return value.lower()

    @field_validator("manifest_sha256")
    @classmethod
    def validate_manifest_hash(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdefABCDEF" for char in value):
            raise ValueError("manifest_sha256 must be a 64-character hexadecimal SHA-256")
        return value.lower()

    @field_validator("expires_at")
    @classmethod
    def validate_expiration(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError("expires_at must include a timezone")
        return parsed.isoformat()


class BlockerEvent(BaseModel):
    event: str
    finding_id: str
    project_id: str | None = None
    cycle_id: str | None = None
    blocked_scopes: list[str] = Field(default_factory=list)
    timestamp: str = Field(default_factory=utc_now)
    data: dict[str, Any] = Field(default_factory=dict)


class ValidationResult(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
