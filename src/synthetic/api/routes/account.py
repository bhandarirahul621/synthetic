"""``/v1/usage`` and ``/v1/keys``: usage against plan limits, and API key management."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from synthetic.api.auth import Principal, authenticate, create_api_key, public_key_record, require
from synthetic.api.deps import ctx
from synthetic.api.errors import APIError
from synthetic.api.idempotency import run_idempotent
from synthetic.api.jobs import usage_period
from synthetic.api.models import KeyCreate

router = APIRouter(tags=["account"])


@router.get("/usage", summary="Rows generated this period vs. plan limit")
def get_usage(request: Request, principal: Principal = Depends(authenticate)):
    c = ctx(request)
    period = usage_period()
    start = datetime.strptime(period, "%Y-%m").replace(tzinfo=UTC)
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    used = c.store.get_usage(principal.workspace_id, period)
    return {"object": "usage", "workspace_id": principal.workspace_id, "plan": "free",
            "period": {"start": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "end": end.strftime("%Y-%m-%dT%H:%M:%SZ")},
            "rows_generated": used["rows"], "datasets_succeeded": used["jobs"],
            "row_limit": c.settings.monthly_row_limit, "limit_enforced": c.settings.enforce_quota,
            "rate_limit_per_minute": c.settings.rate_limit_per_minute}


@router.post("/keys", status_code=201, summary="Create an API key (shown once)")
def create_key(body: KeyCreate, request: Request, principal: Principal = Depends(require("admin"))):
    """Create a key. The secret is in ``key`` and is shown only in this response."""
    secret: dict[str, str] = {}

    def handler() -> tuple[int, dict[str, Any]]:
        raw, record = create_api_key(ctx(request).store, body.scopes, mode=body.mode, name=body.name,
                                     workspace_id=principal.workspace_id)
        secret["key"] = raw
        return 201, public_key_record(record)  # stored for idempotent replay: no secret inside

    response = run_idempotent(request, principal, "POST /v1/keys", body.model_dump(), handler)
    payload = json.loads(bytes(response.body))
    if "error" not in payload:
        payload["key"] = secret.get("key")
        if payload["key"] is None:
            payload["note"] = "This key was already created by an earlier request with the same " \
                              "Idempotency-Key. Its secret is shown only once."
    replay = {"Idempotent-Replayed": "true"} if response.headers.get("idempotent-replayed") else None
    return JSONResponse(payload, status_code=response.status_code, headers=replay)


@router.get("/keys", summary="List API keys")
def list_keys(request: Request, principal: Principal = Depends(require("admin"))):
    keys = ctx(request).store.list_keys(principal.workspace_id)
    return {"object": "list", "data": [public_key_record(k) for k in keys]}


@router.delete("/keys/{key_id}", summary="Revoke an API key")
def revoke_key(key_id: str, request: Request, principal: Principal = Depends(require("admin"))):
    if not ctx(request).store.revoke_key(key_id, principal.workspace_id):
        raise APIError(404, "key_not_found", f"No active key with id '{key_id}'.", param="key_id")
    return {"id": key_id, "object": "api_key", "revoked": True}

