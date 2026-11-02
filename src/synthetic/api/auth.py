"""API keys and scopes (PRD §9.1.2, FR15).

* Keys look like ``sk_test_<random>`` (sandbox) or ``sk_live_<random>``.
* We store only a SHA-256 *hash* of the key. Like a password, the key itself
  is shown once at creation and can never be read back. (A fast hash is fine
  here because keys are long random strings, not human passwords.)
* Each key has *scopes*: what it is allowed to do. A request without the
  needed scope gets ``403``; a missing or unknown key gets ``401``.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

from fastapi import Depends, Request

from synthetic.api.errors import APIError
from synthetic.api.ids import new_id, now

SCOPES = ("datasets:read", "datasets:write", "recipes:read", "recipes:write", "uploads:write", "admin")
"""All scopes. ``admin`` implies every other scope; ``X:write`` implies ``X:read``."""

DEFAULT_WORKSPACE = "ws_default"


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_key(mode: str = "test") -> str:
    if mode not in ("test", "live"):
        raise ValueError("mode must be 'test' or 'live'")
    return f"sk_{mode}_{secrets.token_urlsafe(32)}"


def create_api_key(store, scopes: list[str], mode: str = "test", name: str | None = None,
                   workspace_id: str = DEFAULT_WORKSPACE) -> tuple[str, dict]:
    """Create and store a key. Returns ``(raw_key, record)``; the raw key is not stored."""
    bad = [s for s in scopes if s not in SCOPES]
    if bad or not scopes:
        raise APIError(400, "invalid_scopes",
                       f"Unknown or missing scopes: {', '.join(bad) or '(none)'}. Valid: {', '.join(SCOPES)}.",
                       param="scopes")
    raw = generate_key(mode)
    record = {
        "id": new_id("key", 12),
        "workspace_id": workspace_id,
        "name": name,
        "prefix": raw[:12] + "…",
        "key_hash": hash_key(raw),
        "scopes": sorted(set(scopes)),
        "mode": mode,
        "created_at": now(),
    }
    store.add_key(record)
    return raw, record


def public_key_record(record: dict) -> dict:
    """A key record safe to return from the API (no hash)."""
    from synthetic.api.ids import iso

    return {"id": record["id"], "object": "api_key", "name": record.get("name"), "prefix": record["prefix"],
            "mode": record["mode"], "scopes": record["scopes"], "created_at": iso(record["created_at"]),
            "revoked_at": iso(record.get("revoked_at"))}


@dataclass
class Principal:
    """The caller, as identified by their API key."""

    key_id: str
    workspace_id: str
    scopes: frozenset[str]
    mode: str

    def has(self, scope: str) -> bool:
        if "admin" in self.scopes or scope in self.scopes:
            return True
        resource, _, action = scope.partition(":")
        return action == "read" and f"{resource}:write" in self.scopes


def authenticate(request: Request) -> Principal:
    """Resolve the ``Authorization: Bearer sk_...`` header and apply the rate limit."""
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.startswith(("sk_test_", "sk_live_")):
        raise APIError(401, "invalid_api_key",
                       "Missing or malformed API key. Send 'Authorization: Bearer sk_test_...'.")
    record = request.app.state.store.key_by_hash(hash_key(token.strip()))
    if record is None or record.get("revoked_at"):
        raise APIError(401, "invalid_api_key", "This API key is not valid or has been revoked.")
    request.state.key_id = record["id"]
    allowed, remaining, reset = request.app.state.rate_limiter.hit(record["id"])
    request.state.rate_limit = (request.app.state.rate_limiter.limit, remaining, reset)
    if not allowed:
        raise APIError(429, "rate_limited", f"Too many requests. Try again in {reset} seconds.",
                       headers={"Retry-After": str(reset)})
    return Principal(record["id"], record["workspace_id"], frozenset(record["scopes"]), record["mode"])


def require(scope: str | None = None):
    """FastAPI dependency: authenticate, then insist on ``scope`` (403 if missing)."""

    def dependency(principal: Principal = Depends(authenticate)) -> Principal:
        if scope is not None and not principal.has(scope):
            raise APIError(403, "missing_scope", f"This API key lacks the '{scope}' scope needed for this "
                           "request. Create a key with that scope.", param="scope")
        return principal

    return dependency
