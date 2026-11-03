"""``/v1/webhooks``: subscribe to job events (FR13)."""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends, Request

from synthetic.api.auth import Principal, require
from synthetic.api.deps import ctx, load
from synthetic.api.idempotency import run_idempotent
from synthetic.api.ids import iso, new_id
from synthetic.api.models import WebhookCreate
from synthetic.api.serializers import webhook_out

router = APIRouter(tags=["webhooks"])


@router.post("/webhooks", status_code=201, summary="Subscribe to events")
def create_webhook(body: WebhookCreate, request: Request, principal: Principal = Depends(require("admin"))):
    """Events: ``dataset.succeeded``, ``dataset.failed``, ``report.ready``. The ``secret`` is shown once."""

    def handler() -> tuple[int, dict[str, Any]]:
        doc = {"id": new_id("wh"), "workspace_id": principal.workspace_id, "url": str(body.url),
               "events": list(dict.fromkeys(body.events)), "description": body.description,
               "secret": "whsec_" + secrets.token_urlsafe(32)}
        ctx(request).store.put("webhook", doc)
        return 201, webhook_out(doc, include_secret=True)

    return run_idempotent(request, principal, "POST /v1/webhooks", body.model_dump(mode="json"), handler)


@router.get("/webhooks", summary="List webhooks")
def list_webhooks(request: Request, principal: Principal = Depends(require("admin"))):
    docs = ctx(request).store.list("webhook", principal.workspace_id, limit=500)
    return {"object": "list", "data": [webhook_out(d) for d in docs]}


@router.get("/webhooks/{webhook_id}/deliveries", summary="Recent delivery attempts")
def list_deliveries(webhook_id: str, request: Request, principal: Principal = Depends(require("admin"))):
    load(request, "webhook", webhook_id, principal)
    rows = ctx(request).store.list_deliveries(webhook_id)
    return {"object": "list", "data": [
        {"id": r["id"], "event_type": r["event_type"], "event_id": r["event_id"], "status": r["status"],
         "attempts": r["attempts"], "last_status_code": r["last_status_code"],
         "created_at": iso(r["created_at"]), "delivered_at": iso(r["delivered_at"])} for r in rows]}


@router.delete("/webhooks/{webhook_id}", summary="Delete a webhook")
def delete_webhook(webhook_id: str, request: Request, principal: Principal = Depends(require("admin"))):
    load(request, "webhook", webhook_id, principal)
    ctx(request).store.delete("webhook", webhook_id)
    return {"id": webhook_id, "object": "webhook", "deleted": True}
