"""Service settings, read from environment variables.

Every setting has a safe default for local development. Names use the
``SYNTHETIC_`` prefix, e.g. ``SYNTHETIC_RETENTION_HOURS=0``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

#: Webhook retry delays in seconds after each failed attempt. Attempts stop once
#: 24 hours have passed since the event (FR13).
DEFAULT_WEBHOOK_DELAYS = (10, 30, 60, 300, 900, 1800, 3600, 7200, 14400, 28800)


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(f"SYNTHETIC_{name}", default)


def _env_bool(name: str, default: bool) -> bool:
    value = _env(name)
    return default if value is None else value.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    """All tunables of the API service."""

    data_dir: Path = Path("var")
    """Where SQLite metadata and files live. Replace with Postgres/S3 later (see api/store.py, api/blobs.py)."""

    retention_hours: float = 24.0
    """Uploaded source data is deleted this long after the last job using it completes (FR11). 0-720."""

    rate_limit_per_minute: int = 60
    """Requests per API key per minute (PRD §9.1.6 free plan)."""

    workers: int = 2
    """Background generation threads."""

    max_upload_bytes: int = 1024**3
    """Largest accepted sample upload (1 GB, PRD F1)."""

    preview_max_rows: int = 100
    """Largest preview per table (FR5)."""

    test_key_max_rows: int = 100_000
    """Largest job (requested rows) allowed for sk_test_ keys."""

    monthly_row_limit: int = 100_000
    """Rows per month shown by GET /v1/usage (free plan). Enforced only if ``enforce_quota``."""

    enforce_quota: bool = False
    """When True, jobs that would exceed ``monthly_row_limit`` are rejected with 429."""

    webhook_retry_delays: tuple[float, ...] = DEFAULT_WEBHOOK_DELAYS
    webhook_max_age_s: float = 24 * 3600
    webhook_timeout_s: float = 10.0
    webhook_poll_interval_s: float = 1.0

    signed_url_ttl_s: int = 3600
    """How long download links stay valid."""

    housekeeping_interval_s: float = 300.0
    """How often the retention cleanup runs."""

    secret_key: str | None = None
    """Signs download links. Generated and saved under data_dir if not set."""

    dev_bootstrap: bool = False
    """Create an admin test key on first start and write it to data_dir/dev-api-key.txt."""

    schema_planner: str | None = None
    """Name of the natural-language schema planner (FR1). Not available in this milestone."""

    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> Settings:
        """Build settings from ``SYNTHETIC_*`` environment variables."""
        retention = float(_env("RETENTION_HOURS", "24") or 24)
        if not 0 <= retention <= 720:
            raise ValueError("SYNTHETIC_RETENTION_HOURS must be between 0 and 720 (30 days)")
        return cls(
            data_dir=Path(_env("DATA_DIR", "var") or "var"),
            retention_hours=retention,
            rate_limit_per_minute=int(_env("RATE_LIMIT_PER_MINUTE", "60") or 60),
            workers=int(_env("WORKERS", "2") or 2),
            max_upload_bytes=int(_env("MAX_UPLOAD_BYTES", str(1024**3)) or 1024**3),
            test_key_max_rows=int(_env("TEST_KEY_MAX_ROWS", "100000") or 100000),
            monthly_row_limit=int(_env("MONTHLY_ROW_LIMIT", "100000") or 100000),
            enforce_quota=_env_bool("ENFORCE_QUOTA", False),
            secret_key=_env("SECRET_KEY"),
            dev_bootstrap=_env_bool("DEV_BOOTSTRAP", False),
            schema_planner=_env("SCHEMA_PLANNER") or None,
        )
