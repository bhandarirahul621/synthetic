"""Safe retries with ``Idempotency-Key`` (FR14).

If a client sends the same POST twice with the same ``Idempotency-Key``
(for example, because the network dropped the first response), the second
call returns the *stored* first response instead of doing the work again. A
lift button works the same way: pressing it twice still calls one lift.

* Same key + same body within 24 h → the original response is replayed
  (header ``Idempotent-Replayed: true``).
* Same key + different body → ``409 idempotency_conflict``.
* Same key while the first request is still running → ``409 idempotency_in_progress``.
* Server errors (5xx) are not stored, so the client can retry.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from synthetic.api.auth import Principal
from synthetic.api.errors import APIError
from synthetic.errors import SyntheticError


def fingerprint(body: Any) -> str:
    """Stable hash of a request body."""
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def run_idempotent(request: Request, principal: Principal, endpoint: str, body: Any,
                   handler: Callable[[], tuple[int, dict]]) -> JSONResponse:
    """Run ``handler`` at most once per (workspace, Idempotency-Key, endpoint)."""
    key = request.headers.get("idempotency-key")
    if not key:
        status, payload = handler()
        return JSONResponse(payload, status_code=status)
    if len(key) > 255:
        raise APIError(400, "invalid_idempotency_key", "Idempotency-Key must be at most 255 characters.",
                       param="Idempotency-Key")
    store = request.app.state.store
    digest = fingerprint(body)
    existing = store.idem_claim(principal.workspace_id, key, endpoint, digest)
    if existing is not None:
        if existing["request_hash"] != digest:
            raise APIError(409, "idempotency_conflict",
                           "This Idempotency-Key was already used with a different request. "
                           "Use a new key for a new request.", param="Idempotency-Key")
        if existing["state"] != "done":
            raise APIError(409, "idempotency_in_progress",
                           "A request with this Idempotency-Key is still being processed. Retry shortly.",
                           param="Idempotency-Key")
        return JSONResponse(existing["body"], status_code=existing["status"],
                            headers={"Idempotent-Replayed": "true"})
    try:
        status, payload = handler()
    except SyntheticError as exc:
        if exc.status >= 500:
            store.idem_release(principal.workspace_id, key, endpoint)
            raise
        payload = {"error": {"type": exc.type, "code": exc.code, "message": exc.message, "param": exc.param,
                             "request_id": getattr(request.state, "request_id", None)}}
        store.idem_finish(principal.workspace_id, key, endpoint, exc.status, payload)
        raise
    except Exception:
        store.idem_release(principal.workspace_id, key, endpoint)
        raise
    store.idem_finish(principal.workspace_id, key, endpoint, status, payload)
    return JSONResponse(payload, status_code=status)
