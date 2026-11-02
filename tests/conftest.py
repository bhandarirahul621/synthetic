"""Shared fixtures: example files, a running API (in-process), keys and helpers."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from synthetic.api.app import create_app
from synthetic.api.auth import create_api_key
from synthetic.api.settings import Settings

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"


@pytest.fixture(scope="session")
def ecommerce_sql() -> str:
    return (EXAMPLES / "ecommerce.sql").read_text()


@pytest.fixture(scope="session")
def fintech_yaml() -> str:
    return (EXAMPLES / "fintech.yaml").read_text()


@pytest.fixture(scope="session")
def sample_csv() -> Path:
    return EXAMPLES / "sample_customers.csv"


class WebhookSink:
    """Captures webhook deliveries instead of sending HTTP; can fail on purpose."""

    def __init__(self):
        self.calls: list[dict] = []
        self.fail_first = 0

    def __call__(self, url: str, body: bytes, headers: dict, timeout: float) -> int:
        self.calls.append({"url": url, "body": body, "headers": headers, "at": time.time()})
        if self.fail_first > 0:
            self.fail_first -= 1
            return 500
        return 200


def make_settings(tmp_path: Path, **overrides) -> Settings:
    base = dict(data_dir=tmp_path / "var", rate_limit_per_minute=100_000, workers=2,
                webhook_retry_delays=(0.05, 0.05, 0.05, 0.05), webhook_poll_interval_s=0.05,
                housekeeping_interval_s=3600)
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def api_factory(tmp_path):
    """Start an API with custom settings: ``with api_factory(rate_limit_per_minute=3) as api: ...``."""
    from contextlib import contextmanager

    @contextmanager
    def factory(planner=None, **overrides):
        sink = WebhookSink()
        settings = make_settings(tmp_path, **overrides)
        app = create_app(settings, planner=planner, webhook_sender=sink)
        with TestClient(app) as client:
            ns = SimpleNamespace(client=client, app=app, settings=settings, sink=sink, store=app.state.store,
                                 ctx=app.state.ctx)

            def key(scopes=("admin",), mode="test"):
                raw, _ = create_api_key(app.state.store, list(scopes), mode=mode)
                return {"Authorization": f"Bearer {raw}"}

            ns.key = key
            ns.raw_key = lambda scopes=("admin",), mode="test": create_api_key(app.state.store, list(scopes),
                                                                                mode=mode)[0]
            yield ns

    return factory


@pytest.fixture
def api(api_factory):
    with api_factory() as ns:
        yield ns


def wait_dataset(client, headers, dataset_id, timeout=60.0) -> dict:
    """Poll a dataset until it finishes."""
    deadline = time.monotonic() + timeout
    while True:
        doc = client.get(f"/v1/datasets/{dataset_id}", headers=headers).json()
        if doc["status"] in ("succeeded", "failed") or time.monotonic() > deadline:
            return doc
        time.sleep(0.05)


def wait_until(predicate, timeout=10.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False
