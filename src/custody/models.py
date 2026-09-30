"""Wire models and the signed capture manifest."""

from __future__ import annotations

import math
import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

HEX64 = re.compile(r"^[0-9a-f]{64}$")
ID = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"


class SessionState(StrEnum):
    CREATED = "created"
    UPLOADING = "uploading"
    VERIFYING = "verifying"
    VERIFIED = "verified"
    QUARANTINED = "quarantined"
    AVAILABLE = "available"
    EXPIRED = "expired"


TRANSITIONS: dict[SessionState, frozenset[SessionState]] = {
    SessionState.CREATED: frozenset({SessionState.UPLOADING, SessionState.EXPIRED}),
    SessionState.UPLOADING: frozenset({SessionState.VERIFYING, SessionState.EXPIRED}),
    SessionState.VERIFYING: frozenset({SessionState.VERIFIED, SessionState.QUARANTINED}),
    SessionState.VERIFIED: frozenset({SessionState.AVAILABLE}),
    SessionState.QUARANTINED: frozenset(),
    SessionState.AVAILABLE: frozenset(),
    SessionState.EXPIRED: frozenset(),
}


class Manifest(BaseModel):
    """Immutable capture metadata, signed by the device key before any byte is sent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_-]{16,128}$")
    device_id: str = Field(pattern=ID)
    officer_id: str = Field(pattern=ID)
    agency_id: str = Field(pattern=ID)
    case_id: str | None = Field(default=None, pattern=ID)
    sequence_no: int = Field(ge=0)
    captured_at_ms: int = Field(ge=0)
    media_type: str = Field(pattern=r"^(video|audio|image)/[a-z0-9.+-]{1,40}$")
    size: int = Field(gt=0)
    chunk_size: int = Field(gt=0)
    chunk_sha256: list[str]
    sha256: str
    retention_class: Literal["standard", "extended", "permanent"] = "standard"

    @field_validator("sha256")
    @classmethod
    def _hex(cls, v: str) -> str:
        if not HEX64.match(v):
            raise ValueError("must be lowercase hex sha256")
        return v

    @model_validator(mode="after")
    def _consistent(self) -> Manifest:
        if len(self.chunk_sha256) != math.ceil(self.size / self.chunk_size):
            raise ValueError("chunk_sha256 length does not match size/chunk_size")
        if not all(HEX64.match(h) for h in self.chunk_sha256):
            raise ValueError("chunk hashes must be lowercase hex sha256")
        return self

    def expected_chunk_len(self, idx: int) -> int:
        last = len(self.chunk_sha256) - 1
        return self.chunk_size if idx < last else self.size - self.chunk_size * last

    def wire(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class CreateUpload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    manifest: dict[str, Any]
    signature: str = Field(pattern=r"^[0-9a-f]{128}$")


class DeviceRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: str = Field(pattern=ID)
    public_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    officer_id: str = Field(pattern=ID)
    agency_id: str = Field(pattern=ID)


class DerivativeKind(StrEnum):
    CLIP = "clip"
    REDACTION = "redaction"
    TRANSCODE = "transcode"
    THUMBNAIL = "thumbnail"
    TRANSCRIPT = "transcript"


class HoldRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_ref: str = Field(pattern=ID)
    reason: str = Field(min_length=8, max_length=500)


class Disposition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["retry_authorized", "retain_for_investigation"]
    note: str = Field(min_length=8, max_length=500)
