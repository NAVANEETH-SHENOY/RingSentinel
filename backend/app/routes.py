"""HTTP endpoints. Read endpoints serve the snapshot bundle; the action endpoint writes the log."""

from __future__ import annotations

import hmac
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse
from ringsentinel.snapshots.schemas import RING_ID_PATTERN

from app.audit import AuditError, AuditLog, IdempotencyConflict, InvalidTransition
from app.config import AppSettings
from app.schemas import ActionRequest, ActionResponse, AuditEntry, VerifyResponse
from app.store import SnapshotStore

router = APIRouter(prefix="/api/v1")
RingId = Annotated[str, Path(pattern=RING_ID_PATTERN)]


def get_store(request: Request) -> SnapshotStore:
    return request.app.state.store


def get_audit(request: Request) -> AuditLog:
    return request.app.state.audit


def get_settings(request: Request) -> AppSettings:
    return request.app.state.settings


def require_token(
    settings: Annotated[AppSettings, Depends(get_settings)],
    x_analyst_token: Annotated[str | None, Header()] = None,
) -> None:
    """Shared-secret check for writes and for reading the audit log."""
    if settings.analyst_token is None:
        raise HTTPException(503, "analyst token is not configured on this server")
    given = (x_analyst_token or "").encode("utf-8")
    if not hmac.compare_digest(given, settings.analyst_token.encode("utf-8")):
        raise HTTPException(401, "missing or invalid analyst token")


Store = Annotated[SnapshotStore, Depends(get_store)]
Audit = Annotated[AuditLog, Depends(get_audit)]


@router.get("/health")
def health(store: Store, audit: Audit, settings: Annotated[AppSettings, Depends(get_settings)]):
    meta = store.bundle.meta
    return {
        "status": "ok", "bundle_id": store.bundle_id, "schema_version": meta["schema_version"],
        "evaluation_frozen": meta["evaluation_frozen"], "git_commit": meta["git_commit"],
        "n_rings": meta["n_rings_exported"], "audit_entries": audit.count(),
        "actions_enabled": settings.analyst_token is not None,
    }  # fmt: skip


@router.get("/queue")
def queue(
    store: Store,
    audit: Audit,
    status: Annotated[Literal["pending", "confirmed", "dismissed", "held"] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
):
    statuses = audit.statuses()
    rows = [
        {**item, "status": statuses.get(item["ring_id"], "pending")}
        for item in store.queue_items()
    ]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    header = {k: v for k, v in store.bundle.queue.items() if k != "items"}
    return {
        "bundle_id": store.bundle_id, **header, "total": len(rows),
        "limit": limit, "offset": offset, "items": rows[offset : offset + limit],
    }  # fmt: skip


@router.get("/cases/{ring_id}")
def case(ring_id: RingId, store: Store, audit: Audit):
    found = store.case(ring_id)
    if found is None:
        raise HTTPException(404, "no such ring in this snapshot")
    return {
        "bundle_id": store.bundle_id, **found, "status": audit.status_of(ring_id),
        "n_actions": audit.n_actions(ring_id),
    }  # fmt: skip


@router.get("/metrics")
def metrics(store: Store):
    return {
        "bundle_id": store.bundle_id,
        "evaluation_frozen": store.bundle.meta["evaluation_frozen"], **store.bundle.metrics,
    }


@router.get("/drift")
def drift(store: Store):
    return {"bundle_id": store.bundle_id, **store.bundle.drift}


@router.get("/replay")
def replay(store: Store):
    return {"bundle_id": store.bundle_id, **store.bundle.replay}


@router.post(
    "/cases/{ring_id}/action",
    response_model=ActionResponse,
    dependencies=[Depends(require_token)],
)
def take_action(ring_id: RingId, body: ActionRequest, store: Store, audit: Audit):
    if not store.has_ring(ring_id):
        raise HTTPException(404, "no such ring in this snapshot")
    try:
        result = audit.append(
            ring_id, body.action, body.analyst, body.note, body.idempotency_key
        )
    except IdempotencyConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except InvalidTransition as exc:
        raise HTTPException(409, str(exc)) from exc
    except AuditError as exc:  # pragma: no cover - defensive
        raise HTTPException(400, str(exc)) from exc
    entry = {k: result.entry[k] for k in AuditEntry.model_fields}
    payload = ActionResponse(
        ring_id=ring_id, status=audit.status_of(ring_id), replayed=result.replayed, entry=entry
    )
    return JSONResponse(payload.model_dump(), status_code=200 if result.replayed else 201)


@router.get("/audit", dependencies=[Depends(require_token)])
def audit_list(
    audit: Audit,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
):
    entries = [{k: e[k] for k in AuditEntry.model_fields} for e in audit.entries(limit, offset)]
    return {"total": audit.count(), "limit": limit, "offset": offset, "entries": entries}


@router.get("/audit/verify", response_model=VerifyResponse)
def audit_verify(audit: Audit):
    return audit.verify()
