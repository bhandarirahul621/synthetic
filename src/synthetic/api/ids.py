"""Readable, random resource IDs such as ``ds_3Fz9KqLm2aBcD8xY``."""

from __future__ import annotations

import secrets
import string
import time
from datetime import UTC, datetime

_ALPHABET = string.ascii_letters + string.digits


def new_id(prefix: str, length: int = 16) -> str:
    """Return ``<prefix>_<random>`` using a cryptographically secure generator."""
    return f"{prefix}_" + "".join(secrets.choice(_ALPHABET) for _ in range(length))


def now() -> float:
    """Current time as Unix seconds."""
    return time.time()


def iso(ts: float | None) -> str | None:
    """Unix seconds → ISO 8601 UTC string (``None`` stays ``None``)."""
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
