"""The FastAPI application: wiring of storage, workers, routes, errors and the web UI.

Run it with ``synthetic serve`` (or ``uvicorn synthetic.api.app:app``).
OpenAPI is at ``/openapi.json`` and interactive docs at ``/docs`` (FR12).
"""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from synthetic import __version__
from synthetic.api import retention
from synthetic.api.auth import create_api_key
from synthetic.api.blobs import LocalBlobStore
from synthetic.api.errors import RequestContextMiddleware, install_error_handlers
from synthetic.api.jobs import AppContext, JobRunner
from synthetic.api.planner import SchemaPlanner, get_planner
from synthetic.api.ratelimit import RateLimiter
from synthetic.api.routes import account, datasets, previews, recipes, schemas, uploads, webhooks
from synthetic.api.settings import Settings
from synthetic.api.signing import load_or_create_secret
from synthetic.api.store import SQLiteStore
from synthetic.api.webhooks import Sender, WebhookDispatcher

log = logging.getLogger("synthetic.api")
STATIC_DIR = Path(__file__).parent / "static"

DESCRIPTION = """
Privacy-safe synthetic data: schema-first, reproducible, multi-table, with a
Fidelity and Privacy Report for every dataset.

Authenticate with `Authorization: Bearer sk_test_...`. Every `POST` accepts an
`Idempotency-Key` header. Errors share one format with a `request_id`.
"""


def dev_bootstrap(ctx: AppContext) -> Path | None:
    """Create an admin test key on first start; write it to a file (never to the log)."""
    if ctx.store.count_keys() > 0:
        return None
    raw, _ = create_api_key(ctx.store, ["admin"], mode="test", name="dev bootstrap")
    path = ctx.settings.data_dir / "dev-api-key.txt"
    path.write_text(raw + "\n")
    path.chmod(0o600)
    log.warning("dev bootstrap: created an admin test key; it is in %s", path)
    return path


class Housekeeper:
    """Background thread that runs the retention cleanup periodically (FR11)."""

    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="housekeeping", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.wait(self.ctx.settings.housekeeping_interval_s):
            try:
                retention.cleanup_expired_uploads(self.ctx.store, self.ctx.blobs, self.ctx.settings.retention_hours)
            except Exception as exc:
                log.error("retention cleanup failed type=%s", type(exc).__name__)


def create_app(settings: Settings | None = None, planner: SchemaPlanner | None = None,
               webhook_sender: Sender | None = None) -> FastAPI:
    """Build the app. Tests pass their own settings, planner and webhook sender."""
    settings = settings or Settings.from_env()
    settings.data_dir = Path(settings.data_dir)
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = SQLiteStore(settings.data_dir / "synthetic.db")
        blobs = LocalBlobStore(settings.data_dir / "blobs")
        settings.extra["link_secret"] = load_or_create_secret(settings.data_dir, settings.secret_key)
        dispatcher = WebhookDispatcher(store, settings.webhook_retry_delays, settings.webhook_max_age_s,
                                       settings.webhook_timeout_s, settings.webhook_poll_interval_s,
                                       sender=webhook_sender)
        ctx = AppContext(settings=settings, store=store, blobs=blobs, dispatcher=dispatcher,
                         planner=planner or get_planner(settings.schema_planner))
        ctx.runner = JobRunner(ctx, settings.workers)
        app.state.ctx = ctx
        app.state.store = store
        app.state.rate_limiter = RateLimiter(settings.rate_limit_per_minute)
        if settings.dev_bootstrap:
            dev_bootstrap(ctx)
        housekeeper = Housekeeper(ctx)
        dispatcher.start()
        housekeeper.start()
        requeued = ctx.runner.requeue_unfinished()
        if requeued:
            log.info("re-queued %d unfinished job(s) after restart", requeued)
        try:
            yield
        finally:
            housekeeper.stop()
            dispatcher.stop()
            ctx.runner.shutdown()
            store.close()

    app = FastAPI(title="Synthetic API", version=__version__, description=DESCRIPTION, lifespan=lifespan,
                  openapi_url="/openapi.json", docs_url="/docs", redoc_url=None)
    install_error_handlers(app)
    app.add_middleware(RequestContextMiddleware)
    for module in (schemas, uploads, previews, datasets, recipes, webhooks, account):
        app.include_router(module.router, prefix="/v1")
    app.include_router(datasets.files_router, prefix="/v1")

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict:
        return {"ok": True}

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


def __getattr__(name: str):
    # ``uvicorn synthetic.api.app:app`` builds the app lazily from the environment.
    if name == "app":
        return create_app()
    raise AttributeError(name)
