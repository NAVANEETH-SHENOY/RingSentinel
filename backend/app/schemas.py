"""Request and response models for the API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from ringsentinel.snapshots.schemas import RING_ID_PATTERN

IDEMPOTENCY_PATTERN = r"^[A-Za-z0-9_-]{16,64}$"
Action = Literal["confirm", "dismiss", "hold"]


def _no_control_chars(value: str, allow_newline: bool) -> str:
    for ch in value:
        if ord(ch) < 32 and not (allow_newline and ch in "\n\t"):
            raise ValueError("control characters are not allowed")
        if ord(ch) == 127:
            raise ValueError("control characters are not allowed")
    return value


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    action: Action
    analyst: str = Field(min_length=1, max_length=64)
    note: str = Field(default="", max_length=500)
    idempotency_key: str = Field(pattern=IDEMPOTENCY_PATTERN)

    @field_validator("analyst")
    @classmethod
    def _analyst_clean(cls, value: str) -> str:
        return _no_control_chars(value, allow_newline=False)

    @field_validator("note")
    @classmethod
    def _note_clean(cls, value: str) -> str:
        return _no_control_chars(value, allow_newline=True)


class AuditEntry(BaseModel):
    seq: int
    ts: str
    ring_id: str = Field(pattern=RING_ID_PATTERN)
    action: Action
    analyst: str
    note: str
    idempotency_key: str
    prev_hash: str
    hash: str


class ActionResponse(BaseModel):
    ring_id: str
    status: Literal["pending", "confirmed", "dismissed", "held"]
    replayed: bool
    entry: AuditEntry


class VerifyResponse(BaseModel):
    ok: bool
    entries: int
    head_hash: str | None
    first_bad_seq: int | None
    reason: str | None
