"""Metadata storage: API keys, schemas, uploads, datasets, recipes, webhooks.

Like a filing cabinet with labelled drawers: each *kind* of record (schema,
dataset, ...) is a drawer, each record a JSON document. The
:class:`MetadataStore` interface is what the rest of the API uses;
:class:`SQLiteStore` is today's implementation (one local file, zero setup).
A Postgres implementation can replace it later without touching the routes.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Protocol

from synthetic.api.ids import now


class MetadataStore(Protocol):
    """What the API needs from a metadata database."""

    # documents
    def put(self, kind: str, doc: dict[str, Any]) -> dict[str, Any]: ...
    def get(self, kind: str, doc_id: str, workspace_id: str | None = None) -> dict[str, Any] | None: ...
    def list(self, kind: str, workspace_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]: ...
    def delete(self, kind: str, doc_id: str) -> None: ...
    # api keys
    def add_key(self, record: dict[str, Any]) -> None: ...
    def key_by_hash(self, key_hash: str) -> dict[str, Any] | None: ...
    def list_keys(self, workspace_id: str | None = None) -> list[dict[str, Any]]: ...
    def revoke_key(self, key_id: str, workspace_id: str) -> bool: ...
    def count_keys(self) -> int: ...
    # idempotency
    def idem_claim(self, workspace_id: str, key: str, endpoint: str, request_hash: str) -> dict | None: ...
    def idem_finish(self, workspace_id: str, key: str, endpoint: str, status: int, body: Any) -> None: ...
    def idem_release(self, workspace_id: str, key: str, endpoint: str) -> None: ...
    # usage
    def add_usage(self, workspace_id: str, period: str, rows: int) -> None: ...
    def get_usage(self, workspace_id: str, period: str) -> dict[str, int]: ...
    # webhook deliveries
    def add_delivery(self, record: dict[str, Any]) -> None: ...
    def due_deliveries(self, at: float, limit: int = 20) -> list[dict[str, Any]]: ...
    def update_delivery(self, delivery_id: str, **fields: Any) -> None: ...
    def list_deliveries(self, webhook_id: str | None = None) -> list[dict[str, Any]]: ...


_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    kind TEXT NOT NULL, id TEXT NOT NULL, workspace_id TEXT,
    created_at REAL NOT NULL, updated_at REAL NOT NULL, body TEXT NOT NULL,
    PRIMARY KEY (kind, id)
);
CREATE INDEX IF NOT EXISTS documents_ws ON documents (kind, workspace_id, created_at);
CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, name TEXT, prefix TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE, scopes TEXT NOT NULL, mode TEXT NOT NULL,
    created_at REAL NOT NULL, revoked_at REAL
);
CREATE TABLE IF NOT EXISTS idempotency (
    workspace_id TEXT NOT NULL, key TEXT NOT NULL, endpoint TEXT NOT NULL,
    request_hash TEXT NOT NULL, state TEXT NOT NULL, status INTEGER, body TEXT,
    created_at REAL NOT NULL, PRIMARY KEY (workspace_id, key, endpoint)
);
CREATE TABLE IF NOT EXISTS usage (
    workspace_id TEXT NOT NULL, period TEXT NOT NULL, rows INTEGER NOT NULL DEFAULT 0,
    jobs INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (workspace_id, period)
);
CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id TEXT PRIMARY KEY, webhook_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
    event_id TEXT NOT NULL, event_type TEXT NOT NULL, payload TEXT NOT NULL,
    status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at REAL NOT NULL,
    last_status_code INTEGER, created_at REAL NOT NULL, delivered_at REAL
);
CREATE INDEX IF NOT EXISTS deliveries_due ON webhook_deliveries (status, next_attempt_at);
"""

IDEMPOTENCY_TTL_S = 24 * 3600


class SQLiteStore:
    """SQLite implementation of :class:`MetadataStore` (thread-safe via one lock)."""

    _DELIVERY_FIELDS = frozenset({"status", "attempts", "next_attempt_at", "last_status_code", "delivered_at"})

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _exec(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    # ----- documents ----------------------------------------------------------
    def put(self, kind: str, doc: dict[str, Any]) -> dict[str, Any]:
        ts = now()
        doc.setdefault("created_at", ts)
        doc["updated_at"] = ts
        self._exec(
            "INSERT INTO documents (kind, id, workspace_id, created_at, updated_at, body) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT (kind, id) DO UPDATE SET body = excluded.body, updated_at = excluded.updated_at",
            (kind, doc["id"], doc.get("workspace_id"), doc["created_at"], ts, json.dumps(doc)),
        )
        return doc

    def get(self, kind: str, doc_id: str, workspace_id: str | None = None) -> dict[str, Any] | None:
        rows = self._exec("SELECT body, workspace_id FROM documents WHERE kind = ? AND id = ?", (kind, doc_id))
        if not rows:
            return None
        if workspace_id is not None and rows[0]["workspace_id"] != workspace_id:
            return None
        return json.loads(rows[0]["body"])

    def list(self, kind: str, workspace_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if workspace_id is None:
            rows = self._exec("SELECT body FROM documents WHERE kind = ? ORDER BY created_at DESC LIMIT ?",
                              (kind, limit))
        else:
            rows = self._exec("SELECT body FROM documents WHERE kind = ? AND workspace_id = ? "
                              "ORDER BY created_at DESC LIMIT ?", (kind, workspace_id, limit))
        return [json.loads(r["body"]) for r in rows]

    def delete(self, kind: str, doc_id: str) -> None:
        self._exec("DELETE FROM documents WHERE kind = ? AND id = ?", (kind, doc_id))

    # ----- api keys -------------------------------------------------------------
    def add_key(self, record: dict[str, Any]) -> None:
        self._exec(
            "INSERT INTO api_keys (id, workspace_id, name, prefix, key_hash, scopes, mode, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (record["id"], record["workspace_id"], record.get("name"), record["prefix"], record["key_hash"],
             json.dumps(record["scopes"]), record["mode"], record.get("created_at", now())),
        )

    @staticmethod
    def _key_row(row: sqlite3.Row) -> dict[str, Any]:
        out = dict(row)
        out["scopes"] = json.loads(out["scopes"])
        return out

    def key_by_hash(self, key_hash: str) -> dict[str, Any] | None:
        rows = self._exec("SELECT * FROM api_keys WHERE key_hash = ?", (key_hash,))
        return self._key_row(rows[0]) if rows else None

    def list_keys(self, workspace_id: str | None = None) -> list[dict[str, Any]]:
        if workspace_id is None:
            rows = self._exec("SELECT * FROM api_keys ORDER BY created_at")
        else:
            rows = self._exec("SELECT * FROM api_keys WHERE workspace_id = ? ORDER BY created_at", (workspace_id,))
        return [self._key_row(r) for r in rows]

    def revoke_key(self, key_id: str, workspace_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE api_keys SET revoked_at = ? WHERE id = ? AND workspace_id = ? AND revoked_at IS NULL",
                (now(), key_id, workspace_id))
            return cur.rowcount > 0

    def count_keys(self) -> int:
        return int(self._exec("SELECT COUNT(*) AS n FROM api_keys")[0]["n"])

    # ----- idempotency ------------------------------------------------------------
    def idem_claim(self, workspace_id: str, key: str, endpoint: str, request_hash: str) -> dict | None:
        """Claim a key. Returns ``None`` if newly claimed, else the existing record."""
        with self._lock:
            self._conn.execute("DELETE FROM idempotency WHERE created_at < ?", (now() - IDEMPOTENCY_TTL_S,))
            rows = self._conn.execute(
                "SELECT * FROM idempotency WHERE workspace_id = ? AND key = ? AND endpoint = ?",
                (workspace_id, key, endpoint)).fetchall()
            if rows:
                rec = dict(rows[0])
                rec["body"] = json.loads(rec["body"]) if rec["body"] else None
                return rec
            self._conn.execute(
                "INSERT INTO idempotency (workspace_id, key, endpoint, request_hash, state, created_at) "
                "VALUES (?,?,?,?, 'in_progress', ?)", (workspace_id, key, endpoint, request_hash, now()))
            return None

    def idem_finish(self, workspace_id: str, key: str, endpoint: str, status: int, body: Any) -> None:
        self._exec("UPDATE idempotency SET state = 'done', status = ?, body = ? "
                   "WHERE workspace_id = ? AND key = ? AND endpoint = ?",
                   (status, json.dumps(body), workspace_id, key, endpoint))

    def idem_release(self, workspace_id: str, key: str, endpoint: str) -> None:
        self._exec("DELETE FROM idempotency WHERE workspace_id = ? AND key = ? AND endpoint = ?",
                   (workspace_id, key, endpoint))

    # ----- usage --------------------------------------------------------------------
    def add_usage(self, workspace_id: str, period: str, rows: int) -> None:
        self._exec("INSERT INTO usage (workspace_id, period, rows, jobs) VALUES (?,?,?,1) "
                   "ON CONFLICT (workspace_id, period) DO UPDATE SET rows = rows + excluded.rows, "
                   "jobs = jobs + 1", (workspace_id, period, int(rows)))

    def get_usage(self, workspace_id: str, period: str) -> dict[str, int]:
        rows = self._exec("SELECT rows, jobs FROM usage WHERE workspace_id = ? AND period = ?",
                          (workspace_id, period))
        return {"rows": rows[0]["rows"], "jobs": rows[0]["jobs"]} if rows else {"rows": 0, "jobs": 0}

    # ----- webhook deliveries -------------------------------------------------------
    def add_delivery(self, record: dict[str, Any]) -> None:
        self._exec(
            "INSERT INTO webhook_deliveries (id, webhook_id, workspace_id, event_id, event_type, payload, "
            "status, attempts, next_attempt_at, created_at) VALUES (?,?,?,?,?,?, 'pending', 0, ?, ?)",
            (record["id"], record["webhook_id"], record["workspace_id"], record["event_id"],
             record["event_type"], record["payload"], record["next_attempt_at"], record["created_at"]))

    def due_deliveries(self, at: float, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._exec("SELECT * FROM webhook_deliveries WHERE status = 'pending' AND next_attempt_at <= ? "
                          "ORDER BY next_attempt_at LIMIT ?", (at, limit))
        return [dict(r) for r in rows]

    def update_delivery(self, delivery_id: str, **fields: Any) -> None:
        unknown = set(fields) - self._DELIVERY_FIELDS
        if unknown:
            raise ValueError(f"unknown delivery fields: {sorted(unknown)}")
        # Column names come from the fixed allow-list above, never from user input.
        assignments = ", ".join(f"{name} = ?" for name in fields)
        self._exec(f"UPDATE webhook_deliveries SET {assignments} WHERE id = ?",  # noqa: S608
                   (*fields.values(), delivery_id))

    def list_deliveries(self, webhook_id: str | None = None) -> list[dict[str, Any]]:
        if webhook_id is None:
            rows = self._exec("SELECT * FROM webhook_deliveries ORDER BY created_at")
        else:
            rows = self._exec("SELECT * FROM webhook_deliveries WHERE webhook_id = ? ORDER BY created_at",
                              (webhook_id,))
        return [dict(r) for r in rows]
