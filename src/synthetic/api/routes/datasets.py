"""``/v1/datasets``: generation jobs, files, deliveries, reports (FR7, FR11, FR13)."""

from __future__ import annotations

import json
import secrets
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from synthetic.api import retention
from synthetic.api.auth import Principal, require
from synthetic.api.deps import ctx, load
from synthetic.api.errors import APIError
from synthetic.api.idempotency import run_idempotent
from synthetic.api.ids import iso, new_id, now
from synthetic.api.jobs import run_delivery, usage_period
from synthetic.api.models import DatasetCreate, DeliveryCreate
from synthetic.api.serializers import dataset_out
from synthetic.api.signing import sign_link, verify_link
from synthetic.engine.scenarios import Scenario, validate_scenarios
from synthetic.engine.version import ENGINE_VERSION
from synthetic.schema import Schema

router = APIRouter(tags=["datasets"])
files_router = APIRouter(tags=["files"])


def _resolve_config(request: Request, body: DatasetCreate, principal: Principal) -> dict[str, Any]:
    """Merge recipe defaults with explicit request fields and validate everything we can up front."""
    config: dict[str, Any] = {"rows": {}, "scenarios": [], "seed": None, "formats": ["csv"]}
    schema_doc = None
    if body.recipe_id:
        recipe = load(request, "recipe", body.recipe_id, principal, param="recipe_id")
        versions = recipe["versions"]
        if body.recipe_version is not None:
            match = [v for v in versions if v["version"] == body.recipe_version]
            if not match:
                raise APIError(404, "recipe_version_not_found",
                               f"Recipe '{recipe['name']}' has no version {body.recipe_version}.",
                               param="recipe_version")
            version = match[0]
        else:
            version = versions[-1]
        rc = version["config"]
        config.update({k: rc.get(k) for k in ("rows", "scenarios", "seed", "formats", "upload_id",
                                               "sample_table") if rc.get(k) is not None})
        config.update(schema_snapshot=rc["schema_snapshot"], schema_id=rc.get("schema_id"),
                      schema_version=rc.get("schema_version"), recipe_id=recipe["id"],
                      recipe_version=version["version"])
    if body.schema_id:
        schema_doc = load(request, "schema", body.schema_id, principal, param="schema_id")
        config.update(schema_snapshot=schema_doc["schema"], schema_id=schema_doc["id"],
                      schema_version=schema_doc["version"])
    for field in ("rows", "seed", "formats", "upload_id", "sample_table", "name"):
        value = getattr(body, field)
        if value is not None:
            config[field] = value
    if body.scenarios is not None:
        config["scenarios"] = [s.model_dump() for s in body.scenarios]
    config["pii_columns"] = list(body.pii_columns)
    if not config.get("schema_snapshot") and not config.get("upload_id"):
        raise APIError(400, "schema_required", "Provide schema_id, recipe_id or upload_id.", param="schema_id")
    if config.get("upload_id"):
        upload = load(request, "upload", config["upload_id"], principal, param="upload_id")
        if upload.get("status") == "deleted":
            raise APIError(422, "upload_deleted", "That upload was deleted under the retention policy. "
                           "Upload the sample again.", param="upload_id")
        config.setdefault("sample_table", upload.get("table_name"))
        if config.get("sample_table") is None:
            config["sample_table"] = upload.get("table_name")
    if config.get("schema_snapshot"):
        schema = Schema.from_dict(config["schema_snapshot"])
        unknown = [t for t in config["rows"] if t not in schema.table_names
                   and t != config.get("sample_table")]
        if unknown:
            raise APIError(422, "unknown_table", f"Row counts given for unknown table(s): {', '.join(unknown)}.",
                           param="rows", type="schema_error")
        if not config.get("upload_id"):
            validate_scenarios(schema, [Scenario(**s) for s in config["scenarios"]])
    if any(n < 0 for n in config["rows"].values()):
        raise APIError(400, "invalid_rows", "Row counts must be zero or positive.", param="rows")
    if config.get("seed") is None:
        config["seed"] = secrets.randbelow(2**31)
    return config


@router.post("/datasets", status_code=202, summary="Start a generation job")
def create_dataset(body: DatasetCreate, request: Request,
                   principal: Principal = Depends(require("datasets:write"))):
    """Queue a job and return ``202 Accepted`` immediately (FR13). Poll the job or use a webhook."""
    c = ctx(request)

    def handler() -> tuple[int, dict[str, Any]]:
        config = _resolve_config(request, body, principal)
        requested = sum(config["rows"].values())
        if principal.mode == "test" and requested > c.settings.test_key_max_rows:
            raise APIError(400, "test_key_row_limit",
                           f"Test keys (sk_test_) can request at most {c.settings.test_key_max_rows:,} rows "
                           "per job. Use a live key or fewer rows.", param="rows")
        if c.settings.enforce_quota:
            used = c.store.get_usage(principal.workspace_id, usage_period())["rows"]
            if used + requested > c.settings.monthly_row_limit:
                raise APIError(429, "quota_exceeded", "This job would exceed the monthly row limit of "
                               f"{c.settings.monthly_row_limit:,} rows.", param="rows")
        doc = {"id": new_id("ds"), "object": "dataset", "workspace_id": principal.workspace_id,
               "key_id": principal.key_id, "status": "queued", "progress": 0,
               "engine_version": ENGINE_VERSION, **config}
        c.store.put("dataset", doc)
        assert c.runner is not None
        c.runner.submit(doc["id"])
        return 202, dataset_out(doc)

    return run_idempotent(request, principal, "POST /v1/datasets",
                          body.model_dump(mode="json"), handler)


@router.get("/datasets", summary="List datasets")
def list_datasets(request: Request, limit: int = 20, principal: Principal = Depends(require("datasets:read"))):
    docs = ctx(request).store.list("dataset", principal.workspace_id, limit=min(max(limit, 1), 100))
    return {"object": "list", "data": [dataset_out(d) for d in docs]}


@router.get("/datasets/{dataset_id}", summary="Get job status")
def get_dataset(dataset_id: str, request: Request, principal: Principal = Depends(require("datasets:read"))):
    """Status ``queued`` → ``running`` → ``succeeded`` / ``failed``, with ``progress`` (0-100)."""
    return dataset_out(load(request, "dataset", dataset_id, principal))


def _require_succeeded(doc: dict) -> None:
    if doc["status"] != "succeeded":
        raise APIError(409, "dataset_not_ready",
                       f"The dataset is '{doc['status']}'. Files and the report exist once it has succeeded.",
                       param="dataset_id")


@router.get("/datasets/{dataset_id}/files", summary="Signed download links")
def list_files(dataset_id: str, request: Request, principal: Principal = Depends(require("datasets:read"))):
    """One short-lived download link per table and format, plus the schema and report."""
    c = ctx(request)
    doc = load(request, "dataset", dataset_id, principal)
    _require_succeeded(doc)
    secret = c.settings.extra["link_secret"]
    prefix = f"datasets/{doc['workspace_id']}/{dataset_id}"
    entries = [dict(f) for f in doc["files"]]
    entries += [{"table": None, "format": "schema", "filename": "schema.json", "key": f"{prefix}/schema.json"},
                {"table": None, "format": "report", "filename": "report.json", "key": f"{prefix}/report.json"},
                {"table": None, "format": "report_html", "filename": "report.html",
                 "key": f"{prefix}/report.html"}]
    data = []
    for f in entries:
        token, expires = sign_link(secret, f.pop("key"), c.settings.signed_url_ttl_s)
        data.append({**f, "url": f"/v1/files/{token}", "expires_at": iso(expires)})
    return {"object": "list", "data": data}


@files_router.get("/files/{token}", summary="Download a file via a signed link", include_in_schema=True)
def download(token: str, request: Request):
    """No API key needed: the signed token is the permission (it expires)."""
    c = ctx(request)
    key = verify_link(c.settings.extra["link_secret"], token)
    if key is None or not c.blobs.exists(key):
        raise APIError(404, "link_invalid", "This download link is invalid or has expired. "
                       "Request fresh links from /v1/datasets/{id}/files.")
    return FileResponse(c.blobs.local_path(key), filename=key.rsplit("/", 1)[-1])


@router.post("/datasets/{dataset_id}/deliveries", status_code=202, summary="Push to a database")
def create_delivery(dataset_id: str, body: DeliveryCreate, request: Request,
                    principal: Principal = Depends(require("datasets:write"))):
    """Write the dataset into Postgres (F5). Needs the optional ``postgres`` extra."""
    c = ctx(request)
    try:
        import psycopg  # noqa: F401
    except ImportError:
        raise APIError(501, "connector_unavailable",
                       "Postgres delivery needs the optional 'postgres' extra on the server "
                       "(uv sync --extra postgres).", param="type") from None
    doc = load(request, "dataset", dataset_id, principal)
    _require_succeeded(doc)
    # The DSN contains a password: keep it out of the fingerprint, the store and the logs.
    fp = {"dataset_id": dataset_id, "type": body.type, "target_schema": body.target_schema,
          "if_exists": body.if_exists}

    def handler() -> tuple[int, dict[str, Any]]:
        delivery = {"id": new_id("dlv"), "object": "delivery", "type": body.type, "status": "queued",
                    "target_schema": body.target_schema, "if_exists": body.if_exists,
                    "created_at": iso(now())}
        fresh = load(request, "dataset", dataset_id, principal)
        fresh.setdefault("deliveries", []).append(delivery)
        c.store.put("dataset", fresh)
        assert c.runner is not None
        c.runner.submit_call(run_delivery, c, dataset_id, delivery["id"], body.dsn, body.target_schema,
                             body.if_exists)
        return 202, delivery

    return run_idempotent(request, principal, f"POST /v1/datasets/{dataset_id}/deliveries", fp, handler)


@router.delete("/datasets/{dataset_id}", summary="Delete outputs and linked source data now")
def delete_dataset(dataset_id: str, request: Request,
                   principal: Principal = Depends(require("datasets:write"))):
    """Delete generated files, the report and any linked upload immediately (FR11)."""
    c = ctx(request)
    doc = load(request, "dataset", dataset_id, principal)
    if doc["status"] in ("queued", "running") and c.runner is not None:
        c.runner.cancel(dataset_id)
    c.blobs.delete_prefix(f"datasets/{doc['workspace_id']}/{dataset_id}")
    if doc.get("upload_id"):
        upload = c.store.get("upload", doc["upload_id"], principal.workspace_id)
        if upload and upload.get("status") != "deleted":
            retention.delete_upload(c.store, c.blobs, upload, reason="dataset_deleted")
    c.store.delete("dataset", dataset_id)
    return {"id": dataset_id, "object": "dataset", "deleted": True}


@router.get("/datasets/{dataset_id}/report", summary="Fidelity and Privacy Report")
def get_report(dataset_id: str, request: Request,
               format: str = Query(default="json", pattern="^(json|html|pdf)$"),
               principal: Principal = Depends(require("datasets:read"))):
    """The report as JSON (default) or HTML. ``format=pdf`` is not available yet (501)."""
    c = ctx(request)
    doc = load(request, "dataset", dataset_id, principal)
    _require_succeeded(doc)
    if format == "pdf":
        raise APIError(501, "pdf_not_available", "PDF reports are planned for the next milestone. Use "
                       "format=html and your browser's Print → Save as PDF meanwhile.", param="format")
    prefix = f"datasets/{doc['workspace_id']}/{dataset_id}"
    if format == "html":
        return HTMLResponse(c.blobs.local_path(f"{prefix}/report.html").read_text(encoding="utf-8"))
    report = json.loads(c.blobs.local_path(f"{prefix}/report.json").read_text(encoding="utf-8"))
    return JSONResponse({"object": "report", "dataset_id": dataset_id, **report})
