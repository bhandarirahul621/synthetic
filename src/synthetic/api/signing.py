"""Short-lived signed download links (a local stand-in for S3 presigned URLs).

A signed link is like a cloakroom ticket: whoever holds it can collect that
one coat until it expires, without showing ID. The token encodes the file
key and an expiry time, plus an HMAC so it cannot be forged or edited.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from pathlib import Path

from synthetic.api.ids import now


def load_or_create_secret(data_dir: Path, configured: str | None) -> str:
    """Use the configured secret, or create one in ``data_dir/secret.key`` (mode 600)."""
    if configured:
        return configured
    path = data_dir / "secret.key"
    if path.exists():
        return path.read_text().strip()
    data_dir.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_urlsafe(48)
    path.write_text(secret)
    path.chmod(0o600)
    return secret


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign_link(secret: str, key: str, ttl_s: int) -> tuple[str, float]:
    """Return ``(token, expires_at)`` for blob ``key``."""
    expires = now() + ttl_s
    payload = _b64(json.dumps({"k": key, "e": int(expires)}, separators=(",", ":")).encode())
    mac = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{mac}", expires


def verify_link(secret: str, token: str) -> str | None:
    """Return the blob key if ``token`` is authentic and unexpired, else ``None``."""
    try:
        payload, mac = token.split(".", 1)
        expected = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(mac, expected):
            return None
        data = json.loads(_unb64(payload))
        if now() > data["e"]:
            return None
        return str(data["k"])
    except (ValueError, KeyError, json.JSONDecodeError):
        return None
