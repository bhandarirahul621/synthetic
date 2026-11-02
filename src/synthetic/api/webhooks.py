"""Webhooks: tell the customer's server when a job finishes (FR13).

Each event is signed with HMAC-SHA256 using the subscription's secret, so the
receiver can prove the message came from us and was not changed. The header
looks like ``Synthetic-Signature: t=1730550000,v1=<hex>`` where the signed
text is ``"<t>.<raw body>"`` (the timestamp stops replay of old messages).

Deliveries are stored in the metadata database and sent by a background
thread. Failures are retried with growing delays (backoff) for up to 24
hours. Payloads contain IDs, statuses and links only: never data values.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx

from synthetic.api.ids import iso, new_id, now

log = logging.getLogger("synthetic.webhooks")

EVENTS = ("dataset.succeeded", "dataset.failed", "report.ready")
SIGNATURE_HEADER = "Synthetic-Signature"


def sign(secret: str, body: bytes, timestamp: int) -> str:
    """Return the ``Synthetic-Signature`` header value for ``body``."""
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={mac}"


def verify_signature(secret: str, header: str, body: bytes, tolerance_s: int = 300,
                     at: float | None = None) -> bool:
    """Check a received webhook (for customers' receivers and our tests)."""
    try:
        parts = dict(item.split("=", 1) for item in header.split(","))
        timestamp = int(parts["t"])
        expected = sign(secret, body, timestamp).split("v1=", 1)[1]
    except (KeyError, ValueError):
        return False
    if abs((at or time.time()) - timestamp) > tolerance_s:
        return False
    return hmac.compare_digest(expected, parts.get("v1", ""))


def emit(store, workspace_id: str, event_type: str, data: dict[str, Any]) -> list[str]:
    """Queue ``event_type`` for every matching subscription. Returns delivery IDs."""
    created = now()
    event = {"id": new_id("evt"), "object": "event", "type": event_type, "created_at": iso(created),
             "data": data}
    payload = json.dumps(event, sort_keys=True)
    ids = []
    for hook in store.list("webhook", workspace_id, limit=1000):
        if hook.get("disabled") or event_type not in hook["events"]:
            continue
        delivery_id = new_id("dlv")
        store.add_delivery({"id": delivery_id, "webhook_id": hook["id"], "workspace_id": workspace_id,
                            "event_id": event["id"], "event_type": event_type, "payload": payload,
                            "next_attempt_at": created, "created_at": created})
        ids.append(delivery_id)
    return ids


Sender = Callable[[str, bytes, dict[str, str], float], int]


def http_sender(url: str, body: bytes, headers: dict[str, str], timeout: float) -> int:
    """Send one webhook over HTTP; return the status code."""
    response = httpx.post(url, content=body, headers=headers, timeout=timeout)
    return response.status_code


class WebhookDispatcher:
    """Background thread that sends due deliveries and schedules retries."""

    def __init__(self, store, delays: tuple[float, ...], max_age_s: float, timeout_s: float,
                 poll_interval_s: float = 1.0, sender: Sender | None = None):
        self.store = store
        self.delays = delays
        self.max_age_s = max_age_s
        self.timeout_s = timeout_s
        self.poll_interval_s = poll_interval_s
        self.sender = sender or http_sender
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="webhook-dispatcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=5)

    def wake(self) -> None:
        """Send new deliveries now instead of waiting for the next poll."""
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception as exc:  # keep the thread alive; log the type only
                log.error("webhook loop error type=%s", type(exc).__name__)
            self._wake.wait(self.poll_interval_s)
            self._wake.clear()

    def run_once(self, at: float | None = None) -> int:
        """Attempt every due delivery once. Returns how many were attempted."""
        at = at if at is not None else now()
        due = self.store.due_deliveries(at)
        for delivery in due:
            self._attempt(delivery, at)
        return len(due)

    def _attempt(self, delivery: dict[str, Any], at: float) -> None:
        hook = self.store.get("webhook", delivery["webhook_id"])
        if hook is None:
            self.store.update_delivery(delivery["id"], status="cancelled")
            return
        body = delivery["payload"].encode()
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Synthetic-Webhooks/1",
            "Synthetic-Event": delivery["event_type"],
            "Synthetic-Delivery": delivery["id"],
            SIGNATURE_HEADER: sign(hook["secret"], body, int(at)),
        }
        attempts = delivery["attempts"] + 1
        try:
            code = self.sender(hook["url"], body, headers, self.timeout_s)
        except Exception as exc:  # network errors are expected; retry later
            log.info("webhook attempt failed delivery=%s attempt=%s error=%s", delivery["id"], attempts,
                     type(exc).__name__)
            code = 0
        if 200 <= code < 300:
            self.store.update_delivery(delivery["id"], status="delivered", attempts=attempts,
                                       last_status_code=code, delivered_at=at)
            log.info("webhook delivered delivery=%s event=%s attempt=%s", delivery["id"],
                     delivery["event_type"], attempts)
            return
        delay = self.delays[min(attempts - 1, len(self.delays) - 1)]
        next_at = at + delay
        if next_at - delivery["created_at"] > self.max_age_s:
            self.store.update_delivery(delivery["id"], status="failed", attempts=attempts,
                                       last_status_code=code or None)
            log.info("webhook gave up delivery=%s attempts=%s", delivery["id"], attempts)
            return
        self.store.update_delivery(delivery["id"], attempts=attempts, next_attempt_at=next_at,
                                   last_status_code=code or None)
