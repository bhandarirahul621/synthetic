"""Background generation jobs (FR13).

A job queue works like a restaurant ticket rail: the waiter (the API) pins
the order ticket up and immediately tells the customer "202, we're on it";
cooks (worker threads) pick tickets up as they are free. The customer can
check the ticket's status (``GET /v1/datasets/{id}``) or get a call when it
is ready (a webhook).

This milestone uses a thread pool inside the API process. That is simple and
needs no extra infrastructure, but jobs share the process with the API (no
isolation) and a crash loses in-flight jobs; queued/running jobs are re-queued
on restart, which is safe because generation is deterministic.
"""

from __future__ import annotations

import logging
import shutil
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from synthetic.api import retention
from synthetic.api.blobs import BlobStore
from synthetic.api.ids import now
from synthetic.api.settings import Settings
from synthetic.api.store import MetadataStore
from synthetic.api.webhooks import WebhookDispatcher, emit
from synthetic.engine.fit import read_sample
from synthetic.engine.relational import GenerationCancelled
from synthetic.engine.scenarios import Scenario
from synthetic.engine.version import ENGINE_VERSION
from synthetic.errors import SyntheticError
from synthetic.export import write_dataset
from synthetic.pipeline import run as run_pipeline
from synthetic.report.html import render_html
from synthetic.schema import Schema

log = logging.getLogger("synthetic.jobs")


def usage_period(ts: float | None = None) -> str:
    """Billing period key, e.g. ``2026-11``."""
    return datetime.fromtimestamp(ts if ts is not None else now(), tz=UTC).strftime("%Y-%m")


@dataclass
class AppContext:
    """Shared services, stored on ``app.state.ctx``."""

    settings: Settings
    store: MetadataStore
    blobs: BlobStore
    dispatcher: WebhookDispatcher
    runner: JobRunner | None = None


class JobRunner:
    """Runs dataset jobs and deliveries on a thread pool."""

    def __init__(self, ctx: AppContext, workers: int):
        self.ctx = ctx
        self.executor = ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="job")
        self.cancelled: set[str] = set()
        self._lock = threading.Lock()

    def submit(self, dataset_id: str) -> None:
        self.executor.submit(self._safe_run, dataset_id)

    def submit_call(self, fn, *args: Any) -> None:
        self.executor.submit(fn, *args)

    def cancel(self, dataset_id: str) -> None:
        with self._lock:
            self.cancelled.add(dataset_id)

    def is_cancelled(self, dataset_id: str) -> bool:
        with self._lock:
            return dataset_id in self.cancelled

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)

    def requeue_unfinished(self) -> int:
        """After a restart, run again any job that was queued or running."""
        count = 0
        for doc in self.ctx.store.list("dataset", None, limit=100_000):
            if doc.get("status") in ("queued", "running"):
                doc["status"] = "queued"
                doc["progress"] = 0
                self.ctx.store.put("dataset", doc)
                self.submit(doc["id"])
                count += 1
        return count

    def _safe_run(self, dataset_id: str) -> None:
        try:
            run_dataset_job(self.ctx, dataset_id, self)
        except Exception as exc:  # last line of defence: never let a worker die silently
            log.error("job crashed dataset_id=%s type=%s\n%s", dataset_id, type(exc).__name__,
                      "".join(traceback.format_tb(exc.__traceback__)))


def _update(store: MetadataStore, dataset_id: str, **fields: Any) -> dict | None:
    doc = store.get("dataset", dataset_id)
    if doc is None:
        return None
    doc.update(fields)
    return store.put("dataset", doc)


def _fail(ctx: AppContext, doc: dict, type_: str, code: str, message: str) -> None:
    _update(ctx.store, doc["id"], status="failed", completed_at=now(),
            error={"type": type_, "code": code, "message": message})
    emit(ctx.store, doc["workspace_id"], "dataset.failed",
         {"dataset_id": doc["id"], "status": "failed", "error": {"code": code},
          "links": {"self": f"/v1/datasets/{doc['id']}"}})
    ctx.dispatcher.wake()


def run_dataset_job(ctx: AppContext, dataset_id: str, runner: JobRunner) -> None:
    """Run one dataset job from ``queued`` to ``succeeded`` or ``failed``."""
    store, blobs = ctx.store, ctx.blobs
    doc = store.get("dataset", dataset_id)
    if doc is None or doc.get("status") != "queued":
        return
    doc = _update(store, dataset_id, status="running", started_at=now(), progress=1) or doc
    # Audit log line (PRD §8.1): engine version, seed, parameters, never data values.
    log.info("job started dataset_id=%s engine_version=%s seed=%s rows=%s scenarios=%d sample=%s",
             dataset_id, ENGINE_VERSION, doc["seed"], doc.get("rows"), len(doc.get("scenarios") or []),
             bool(doc.get("upload_id")))
    workdir = ctx.settings.data_dir / "tmp" / dataset_id
    try:
        schema = Schema.from_dict(doc["schema_snapshot"]) if doc.get("schema_snapshot") else None
        sample = None
        if doc.get("upload_id"):
            upload = store.get("upload", doc["upload_id"], doc["workspace_id"])
            if upload is None or upload.get("status") == "deleted":
                return _fail(ctx, doc, "invalid_request", "upload_deleted",
                             "The sample upload was deleted (retention policy or by request). "
                             "Upload it again to generate from it.")
            sample = read_sample(blobs.local_path(upload["blob_key"]), filename=upload["filename"])

        last = {"p": 0}

        def progress(fraction: float, message: str) -> None:
            pct = int(5 + 85 * fraction)
            if pct > last["p"]:
                last["p"] = pct
                _update(store, dataset_id, progress=pct)

        result = run_pipeline(
            schema,
            rows=doc.get("rows") or {},
            seed=doc["seed"],
            scenarios=[Scenario(**s) for s in doc.get("scenarios") or []],
            sample=sample,
            sample_table=doc.get("sample_table"),
            pii_columns=doc.get("pii_columns") or [],
            progress=progress,
            should_cancel=lambda: runner.is_cancelled(dataset_id),
        )
        del sample
        if runner.is_cancelled(dataset_id):
            raise GenerationCancelled()
        _update(store, dataset_id, progress=92)
        files = write_dataset(result.tables, result.schema, workdir, doc.get("formats") or ["csv"])
        prefix = f"datasets/{doc['workspace_id']}/{dataset_id}"
        stored = []
        for f in files:
            key = f"{prefix}/{f['filename']}"
            blobs.put_file(key, workdir / f["filename"])
            stored.append({k: v for k, v in f.items() if k != "path"} | {"key": key})
        blobs.put_bytes(f"{prefix}/report.json", _json_bytes(result.report))
        blobs.put_bytes(f"{prefix}/report.html", render_html(result.report).encode())
        blobs.put_bytes(f"{prefix}/schema.json", result.schema.to_json().encode())
        row_count = sum(len(df) for df in result.tables.values())
        meta = {k: v for k, v in result.generation.metadata.items() if k in
                ("timings_s", "rows_dropped_no_copy", "models", "table_order")}
        if store.get("dataset", dataset_id) is None or runner.is_cancelled(dataset_id):
            raise GenerationCancelled()
        _update(store, dataset_id, status="succeeded", progress=100, completed_at=now(), files=stored,
                row_counts=result.generation.row_counts, metadata=meta,
                report_summary={"status": result.report["overall"]["status"],
                                "fidelity_score": result.report["overall"]["fidelity_score"],
                                "summary": result.report["summary"]})
        store.add_usage(doc["workspace_id"], usage_period(), row_count)
        log.info("job succeeded dataset_id=%s rows=%d report=%s timings=%s", dataset_id, row_count,
                 result.report["overall"]["status"], meta.get("timings_s"))
        links = {"self": f"/v1/datasets/{dataset_id}", "files": f"/v1/datasets/{dataset_id}/files",
                 "report": f"/v1/datasets/{dataset_id}/report"}
        emit(store, doc["workspace_id"], "dataset.succeeded",
             {"dataset_id": dataset_id, "status": "succeeded", "rows": row_count, "links": links})
        emit(store, doc["workspace_id"], "report.ready",
             {"dataset_id": dataset_id, "report_status": result.report["overall"]["status"],
              "fidelity_score": result.report["overall"]["fidelity_score"], "links": links})
        ctx.dispatcher.wake()
        if doc.get("upload_id"):
            retention.cleanup_expired_uploads(store, blobs, ctx.settings.retention_hours)
    except GenerationCancelled:
        blobs.delete_prefix(f"datasets/{doc['workspace_id']}/{dataset_id}")
        log.info("job cancelled dataset_id=%s", dataset_id)
    except SyntheticError as exc:
        log.info("job failed dataset_id=%s code=%s", dataset_id, exc.code)
        _fail(ctx, doc, exc.type, exc.code, exc.message)
    except Exception as exc:
        # Only the exception type and stack frames: messages may contain data values (FR15).
        log.error("job error dataset_id=%s type=%s\n%s", dataset_id, type(exc).__name__,
                  "".join(traceback.format_tb(exc.__traceback__)))
        _fail(ctx, doc, "api_error", "internal_error",
              "The job failed because of an internal error. Retrying with the same request is safe.")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _json_bytes(obj: Any) -> bytes:
    import json

    return json.dumps(obj, indent=2, default=str).encode()


def run_delivery(ctx: AppContext, dataset_id: str, delivery_id: str, dsn: str, target_schema: str,
                 if_exists: str) -> None:
    """Push a finished dataset into Postgres. The DSN lives only in this call's memory."""
    from synthetic.export import deliver_postgres, read_table_file

    doc = ctx.store.get("dataset", dataset_id)
    if doc is None:
        return

    def set_status(**fields: Any) -> None:
        current = ctx.store.get("dataset", dataset_id)
        if current is None:
            return
        for d in current.get("deliveries", []):
            if d["id"] == delivery_id:
                d.update(fields)
        ctx.store.put("dataset", current)

    set_status(status="running")
    try:
        schema = Schema.from_json(ctx.blobs.local_path(
            f"datasets/{doc['workspace_id']}/{dataset_id}/schema.json").read_text())
        tables = {}
        for f in doc["files"]:
            if f["format"] == "parquet" and f["table"]:
                tables[f["table"]] = read_table_file(ctx.blobs.local_path(f["key"]))
        if len(tables) < len(schema.tables):
            for f in doc["files"]:
                if f["format"] == "csv" and f["table"] and f["table"] not in tables:
                    tables[f["table"]] = read_table_file(ctx.blobs.local_path(f["key"]))
        counts = deliver_postgres(tables, schema, dsn, target_schema=target_schema, if_exists=if_exists)
        set_status(status="succeeded", completed_at=now(), rows=counts)
    except SyntheticError as exc:
        set_status(status="failed", error={"code": exc.code, "message": exc.message})
    except Exception as exc:
        # Driver errors can echo the DSN or data; store only the type.
        set_status(status="failed", error={"code": "delivery_failed",
                                           "message": f"Delivery failed ({type(exc).__name__}). "
                                                      "Check the connection string and permissions."})
