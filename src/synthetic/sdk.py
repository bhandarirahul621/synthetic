"""Python SDK: a thin, typed-ish wrapper over the ``/v1`` REST API (PRD §9.1.7).

Example::

    from synthetic.sdk import Client

    client = Client(api_key="sk_test_...", base_url="http://localhost:8000")
    schema = client.schemas.create(ddl=open("examples/ecommerce.sql").read())
    ds = client.datasets.create(schema_id=schema["id"], rows={"customers": 2000, "orders": 50000},
                                seed=42, formats=["parquet"]).wait()
    ds.download("./out")
    print(client.reports.get(ds.id)["summary"])

Every POST gets an automatic ``Idempotency-Key``, and retries (network
errors, 429, 5xx) reuse it, so a retry never creates a second job (FR14).
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from synthetic.api.webhooks import verify_signature

DEFAULT_BASE_URL = "http://localhost:8000"

__all__ = ["Client", "Dataset", "SyntheticAPIError", "JobFailed", "verify_signature"]


class SyntheticAPIError(Exception):
    """An error response from the API, with the §9.1.5 fields as attributes."""

    def __init__(self, status: int, error: dict[str, Any]):
        self.status = status
        self.type = error.get("type")
        self.code = error.get("code")
        self.message = error.get("message", "")
        self.param = error.get("param")
        self.request_id = error.get("request_id")
        super().__init__(f"{status} {self.code}: {self.message} (request_id={self.request_id})")


class JobFailed(Exception):
    """Raised by :meth:`Dataset.wait` when the job ends in ``failed``."""

    def __init__(self, dataset: Dataset):
        self.dataset = dataset
        err = dataset.data.get("error") or {}
        super().__init__(f"dataset {dataset.id} failed: {err.get('code')}: {err.get('message')}")


class Client:
    """Entry point. Reads ``SYNTHETIC_API_KEY`` and ``SYNTHETIC_BASE_URL`` if not given."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None, *, timeout: float = 60.0,
                 max_retries: int = 2, http_client: httpx.Client | None = None):
        self.api_key = api_key or os.environ.get("SYNTHETIC_API_KEY")
        if not self.api_key:
            raise ValueError("No API key: pass api_key=... or set SYNTHETIC_API_KEY.")
        self.base_url = (base_url or os.environ.get("SYNTHETIC_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.max_retries = max_retries
        self._http = http_client or httpx.Client(base_url=self.base_url, timeout=timeout)
        self._owns_http = http_client is None
        self.schemas = Schemas(self)
        self.uploads = Uploads(self)
        self.previews = Previews(self)
        self.datasets = Datasets(self)
        self.reports = Reports(self)
        self.recipes = Recipes(self)
        self.webhooks = Webhooks(self)

    # ----- plumbing ---------------------------------------------------------
    def request(self, method: str, path: str, *, json: Any = None, params: dict | None = None,
                files: Any = None, data: dict | None = None, idempotency_key: str | None = None,
                auth: bool = True) -> httpx.Response:
        """Send a request; raise :class:`SyntheticAPIError` on error responses."""
        headers = {"Authorization": f"Bearer {self.api_key}"} if auth else {}
        if method == "POST":
            headers["Idempotency-Key"] = idempotency_key or str(uuid.uuid4())
        attempt = 0
        while True:
            try:
                response = self._http.request(method, path, json=json, params=params, files=files,
                                              data=data, headers=headers)
            except httpx.TransportError:
                if attempt >= self.max_retries:
                    raise
            else:
                retryable = response.status_code == 429 or response.status_code >= 500
                if not retryable or attempt >= self.max_retries:
                    break
            attempt += 1
            time.sleep(min(8.0, 0.5 * 2**attempt))
            if files is not None:
                for value in (files.values() if isinstance(files, dict) else []):
                    handle = value[1] if isinstance(value, tuple) else value
                    if hasattr(handle, "seek"):
                        handle.seek(0)
        if response.status_code >= 400:
            try:
                error = response.json().get("error", {})
            except ValueError:
                error = {"message": response.text[:200]}
            raise SyntheticAPIError(response.status_code, error)
        return response

    def _json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        return self.request(method, path, **kwargs).json()

    def usage(self) -> dict[str, Any]:
        """``GET /v1/usage``."""
        return self._json("GET", "/v1/usage")

    def download_url(self, url: str, dest: str | Path) -> Path:
        """Download a signed file link to ``dest``."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        response = self.request("GET", url, auth=False)
        dest.write_bytes(response.content)
        return dest

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _clean(**kwargs: Any) -> dict[str, Any]:
    return {k: v for k, v in kwargs.items() if v is not None}


class _Resource:
    def __init__(self, client: Client):
        self._client = client


class Schemas(_Resource):
    def create(self, *, ddl: str | None = None, dialect: str | None = None, schema: dict | None = None,
               yaml: str | None = None, dbt_yaml: str | None = None, prompt: str | None = None,
               upload_id: str | None = None, table_name: str | None = None, name: str | None = None,
               idempotency_key: str | None = None) -> dict[str, Any]:
        """``POST /v1/schemas``: pass exactly one source."""
        body = _clean(ddl=ddl, dialect=dialect, schema=schema, yaml=yaml, dbt_yaml=dbt_yaml, prompt=prompt,
                      upload_id=upload_id, table_name=table_name, name=name)
        return self._client._json("POST", "/v1/schemas", json=body, idempotency_key=idempotency_key)

    def get(self, schema_id: str) -> dict[str, Any]:
        return self._client._json("GET", f"/v1/schemas/{schema_id}")

    def list(self) -> list[dict[str, Any]]:
        return self._client._json("GET", "/v1/schemas")["data"]

    def update(self, schema_id: str, *, schema: dict | None = None, columns: dict | None = None,
               name: str | None = None) -> dict[str, Any]:
        """``PATCH /v1/schemas/{id}``, e.g. ``columns={"customers.email": {"pii": True}}``."""
        return self._client._json("PATCH", f"/v1/schemas/{schema_id}",
                                  json=_clean(schema=schema, columns=columns, name=name))


class Uploads(_Resource):
    def create(self, path: str | Path, *, table_name: str | None = None,
               retention_hours: float | None = None) -> dict[str, Any]:
        """``POST /v1/uploads`` (multipart)."""
        path = Path(path)
        with path.open("rb") as fh:
            return self._client._json("POST", "/v1/uploads", files={"file": (path.name, fh)},
                                      data=_clean(table_name=table_name, retention_hours=retention_hours))

    def get(self, upload_id: str) -> dict[str, Any]:
        return self._client._json("GET", f"/v1/uploads/{upload_id}")

    def delete(self, upload_id: str) -> dict[str, Any]:
        return self._client._json("DELETE", f"/v1/uploads/{upload_id}")


class Previews(_Resource):
    def create(self, *, schema_id: str | None = None, schema: dict | None = None, recipe_id: str | None = None,
               upload_id: str | None = None, sample_table: str | None = None, rows: dict | None = None,
               seed: int = 0, scenarios: list[dict] | None = None) -> dict[str, Any]:
        """``POST /v1/previews``: at most 100 rows per table."""
        body = _clean(schema_id=schema_id, schema=schema, recipe_id=recipe_id, upload_id=upload_id,
                      sample_table=sample_table, rows=rows, seed=seed, scenarios=scenarios)
        return self._client._json("POST", "/v1/previews", json=body)


class Dataset:
    """A dataset job. ``wait()`` polls until it finishes."""

    def __init__(self, client: Client, data: dict[str, Any]):
        self._client = client
        self.data = data

    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def status(self) -> str:
        return self.data["status"]

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __repr__(self) -> str:
        return f"Dataset(id={self.id!r}, status={self.status!r}, progress={self.data.get('progress')})"

    def refresh(self) -> Dataset:
        self.data = self._client._json("GET", f"/v1/datasets/{self.id}")
        return self

    def wait(self, timeout: float = 600.0, poll_interval: float = 1.0) -> Dataset:
        """Poll until ``succeeded`` (returns self) or ``failed`` (raises :class:`JobFailed`)."""
        deadline = time.monotonic() + timeout
        while self.status not in ("succeeded", "failed"):
            if time.monotonic() > deadline:
                raise TimeoutError(f"dataset {self.id} still {self.status} after {timeout}s")
            time.sleep(poll_interval)
            self.refresh()
        if self.status == "failed":
            raise JobFailed(self)
        return self

    def files(self) -> list[dict[str, Any]]:
        return self._client.datasets.files(self.id)

    def download(self, out_dir: str | Path, formats: list[str] | None = None) -> list[Path]:
        return self._client.datasets.download(self.id, out_dir, formats)

    def report(self, format: str = "json") -> Any:
        return self._client.reports.get(self.id, format=format)


class Datasets(_Resource):
    def create(self, *, schema_id: str | None = None, recipe_id: str | None = None,
               recipe_version: int | None = None, upload_id: str | None = None, sample_table: str | None = None,
               rows: dict[str, int] | None = None, scenarios: list[dict] | None = None, seed: int | None = None,
               formats: list[str] | None = None, name: str | None = None, pii_columns: list[str] | None = None,
               idempotency_key: str | None = None) -> Dataset:
        """``POST /v1/datasets`` → a :class:`Dataset` (status ``queued``)."""
        body = _clean(schema_id=schema_id, recipe_id=recipe_id, recipe_version=recipe_version,
                      upload_id=upload_id, sample_table=sample_table, rows=rows, scenarios=scenarios,
                      seed=seed, formats=formats, name=name, pii_columns=pii_columns)
        data = self._client._json("POST", "/v1/datasets", json=body, idempotency_key=idempotency_key)
        return Dataset(self._client, data)

    def get(self, dataset_id: str) -> Dataset:
        return Dataset(self._client, self._client._json("GET", f"/v1/datasets/{dataset_id}"))

    def list(self, limit: int = 20) -> list[Dataset]:
        data = self._client._json("GET", "/v1/datasets", params={"limit": limit})["data"]
        return [Dataset(self._client, d) for d in data]

    def files(self, dataset_id: str) -> list[dict[str, Any]]:
        """Signed download links (``GET /v1/datasets/{id}/files``)."""
        return self._client._json("GET", f"/v1/datasets/{dataset_id}/files")["data"]

    def download(self, dataset_id: str, out_dir: str | Path, formats: list[str] | None = None) -> list[Path]:
        """Download every table file (optionally only some formats) into ``out_dir``."""
        paths = []
        for f in self.files(dataset_id):
            if f["table"] is None and f["format"] != "schema":
                continue
            if formats and f["format"] not in formats and f["format"] != "schema":
                continue
            paths.append(self._client.download_url(f["url"], Path(out_dir) / f["filename"]))
        return paths

    def deliver(self, dataset_id: str, dsn: str, *, target_schema: str = "public",
                if_exists: str = "fail") -> dict[str, Any]:
        """``POST /v1/datasets/{id}/deliveries`` (Postgres)."""
        return self._client._json("POST", f"/v1/datasets/{dataset_id}/deliveries",
                                  json={"type": "postgres", "dsn": dsn, "target_schema": target_schema,
                                        "if_exists": if_exists})

    def delete(self, dataset_id: str) -> dict[str, Any]:
        return self._client._json("DELETE", f"/v1/datasets/{dataset_id}")


class Reports(_Resource):
    def get(self, dataset_id: str, format: str = "json") -> Any:
        """The report as a dict (``json``) or an HTML string (``html``)."""
        response = self._client.request("GET", f"/v1/datasets/{dataset_id}/report", params={"format": format})
        return response.json() if format == "json" else response.text


class Recipes(_Resource):
    def create(self, *, name: str, schema_id: str, rows: dict[str, int] | None = None,
               scenarios: list[dict] | None = None, seed: int = 0, formats: list[str] | None = None,
               upload_id: str | None = None, sample_table: str | None = None,
               description: str | None = None) -> dict[str, Any]:
        """Save a recipe; the same ``name`` again creates a new version."""
        body = _clean(name=name, schema_id=schema_id, rows=rows, scenarios=scenarios, seed=seed,
                      formats=formats, upload_id=upload_id, sample_table=sample_table, description=description)
        return self._client._json("POST", "/v1/recipes", json=body)

    def list(self) -> list[dict[str, Any]]:
        return self._client._json("GET", "/v1/recipes")["data"]

    def get(self, recipe_id: str) -> dict[str, Any]:
        return self._client._json("GET", f"/v1/recipes/{recipe_id}")

    def versions(self, recipe_id: str) -> list[dict[str, Any]]:
        return self._client._json("GET", f"/v1/recipes/{recipe_id}/versions")["data"]


class Webhooks(_Resource):
    def create(self, url: str, events: list[str] | None = None) -> dict[str, Any]:
        """Subscribe; the response's ``secret`` is shown once."""
        return self._client._json("POST", "/v1/webhooks", json=_clean(url=url, events=events))

    def list(self) -> list[dict[str, Any]]:
        return self._client._json("GET", "/v1/webhooks")["data"]

    def delete(self, webhook_id: str) -> dict[str, Any]:
        return self._client._json("DELETE", f"/v1/webhooks/{webhook_id}")
