"""``/v1/uploads``: upload a CSV/Parquet sample (FR3).

Deviation from PRD §9.1.3: the PRD describes short-lived *signed URLs* that
let the browser upload straight to object storage. Without S3 in this
milestone we accept a multipart upload on this endpoint instead; the file is
streamed to disk in chunks and its contents never reach the logs.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from synthetic.api import retention
from synthetic.api.auth import Principal, require
from synthetic.api.blobs import BlobTooLarge
from synthetic.api.deps import ctx, load
from synthetic.api.errors import APIError
from synthetic.api.idempotency import run_idempotent
from synthetic.api.ids import new_id
from synthetic.api.serializers import upload_out
from synthetic.engine.fit import detect_column, read_sample

router = APIRouter(tags=["uploads"])

ALLOWED_SUFFIXES = (".csv", ".parquet", ".pq")


class _HashingReader:
    """Wrap a file object and hash its bytes while they are copied."""

    def __init__(self, raw):
        self.raw = raw
        self.sha = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        chunk = self.raw.read(size)
        self.sha.update(chunk)
        return chunk


@router.post("/uploads", status_code=201, summary="Upload a sample (CSV or Parquet)")
def create_upload(request: Request, file: UploadFile = File(...),
                  table_name: str | None = Form(default=None),
                  retention_hours: float | None = Form(default=None, ge=0, le=720),
                  principal: Principal = Depends(require("uploads:write"))):
    """Upload a sample. Returns an ``upload_id``, row count and detected column types (no values)."""
    c = ctx(request)
    filename = Path(file.filename or "sample.csv").name
    if not filename.lower().endswith(ALLOWED_SUFFIXES):
        raise APIError(400, "unsupported_file_type", "Upload a .csv or .parquet file.", param="file")
    upload_id = new_id("upl")
    key = f"uploads/{principal.workspace_id}/{upload_id}/{filename}"
    reader = _HashingReader(file.file)
    try:
        size = c.blobs.write(key, reader, max_bytes=c.settings.max_upload_bytes)
    except BlobTooLarge:
        raise APIError(413, "file_too_large",
                       f"The file is larger than the {c.settings.max_upload_bytes // (1024**2)} MB limit.",
                       param="file") from None
    created = {"done": False}

    def handler():
        try:
            df = read_sample(c.blobs.local_path(key), filename=filename)
        except Exception:
            c.blobs.delete_prefix(f"uploads/{principal.workspace_id}/{upload_id}")
            raise
        name = table_name or Path(filename).stem
        columns = []
        for col in df.columns:
            det = detect_column(df[col], str(col), name)
            columns.append({"name": str(col), "type": det.column.type, "pii": det.column.pii,
                            "role": det.role, "reason": det.reason})
        doc = {"id": upload_id, "workspace_id": principal.workspace_id, "status": "ready",
               "filename": filename, "bytes": size, "rows": int(len(df)), "columns": columns,
               "blob_key": key, "table_name": name, "retention_hours": retention_hours}
        c.store.put("upload", doc)
        created["done"] = True
        return 201, upload_out(doc)

    fingerprint = {"filename": filename, "sha256": reader.sha.hexdigest(), "table_name": table_name,
                   "retention_hours": retention_hours}
    try:
        return run_idempotent(request, principal, "POST /v1/uploads", fingerprint, handler)
    finally:
        if not created["done"]:
            c.blobs.delete_prefix(f"uploads/{principal.workspace_id}/{upload_id}")


@router.get("/uploads/{upload_id}", summary="Get an upload")
def get_upload(upload_id: str, request: Request, principal: Principal = Depends(require("uploads:write"))):
    return upload_out(load(request, "upload", upload_id, principal))


@router.delete("/uploads/{upload_id}", summary="Delete an upload now")
def delete_upload(upload_id: str, request: Request, principal: Principal = Depends(require("uploads:write"))):
    """Delete the uploaded source file immediately (FR11)."""
    doc = load(request, "upload", upload_id, principal)
    if doc.get("status") != "deleted":
        retention.delete_upload(ctx(request).store, ctx(request).blobs, doc, reason="requested")
    return {"id": upload_id, "object": "upload", "deleted": True}
