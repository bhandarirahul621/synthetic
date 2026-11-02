"""Source-data retention (FR11).

Uploaded samples are real data, so we keep them only as long as needed:
by default they are deleted 24 hours after the last job that used them
finishes (configurable 0-30 days, globally or per upload). An upload that no
job ever used is deleted the same time after it was uploaded.

Generated outputs are synthetic and are kept until the user deletes the
dataset. Learned models are never persisted, so nothing derived from the
source survives the upload except aggregate report numbers.
"""

from __future__ import annotations

import logging

from synthetic.api.ids import now

log = logging.getLogger("synthetic.retention")

ACTIVE = ("queued", "running")


def upload_expiry(upload: dict, datasets: list[dict], default_hours: float) -> float | None:
    """When ``upload`` may be deleted (Unix seconds), or ``None`` while a job still needs it."""
    hours = upload.get("retention_hours")
    hours = default_hours if hours is None else hours
    users = [d for d in datasets if d.get("upload_id") == upload["id"]]
    if any(d.get("status") in ACTIVE for d in users):
        return None
    finished = [d["completed_at"] for d in users if d.get("completed_at")]
    anchor = max(finished) if finished else upload["created_at"]
    return anchor + hours * 3600


def delete_upload(store, blobs, upload: dict, reason: str) -> None:
    """Delete an upload's file and mark its record as deleted (the record has no data values)."""
    blobs.delete_prefix(f"uploads/{upload['workspace_id']}/{upload['id']}")
    upload = dict(upload)
    upload["status"] = "deleted"
    upload["deleted_at"] = now()
    upload["deleted_reason"] = reason
    upload.pop("blob_key", None)
    store.put("upload", upload)
    log.info("upload deleted upload_id=%s reason=%s", upload["id"], reason)


def cleanup_expired_uploads(store, blobs, default_hours: float, at: float | None = None) -> list[str]:
    """Delete every upload whose retention window has passed. Returns deleted IDs."""
    at = at if at is not None else now()
    datasets = store.list("dataset", None, limit=100_000)
    deleted = []
    for upload in store.list("upload", None, limit=100_000):
        if upload.get("status") == "deleted":
            continue
        expires = upload_expiry(upload, datasets, default_hours)
        if expires is not None and at >= expires:
            delete_upload(store, blobs, upload, reason="retention")
            deleted.append(upload["id"])
    return deleted
