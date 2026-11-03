"""API behaviour: auth, scopes, jobs, idempotency, errors, previews, webhooks, OpenAPI, retention."""

import json
import time

from conftest import wait_dataset, wait_until
from synthetic.api.retention import cleanup_expired_uploads
from synthetic.api.webhooks import verify_signature
from synthetic.schema import Schema


def _schema(api, headers, ddl):
    r = api.client.post("/v1/schemas", json={"ddl": ddl}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _assert_envelope(response, status, code=None):
    assert response.status_code == status, response.text
    err = response.json()["error"]
    assert set(err) == {"type", "code", "message", "param", "request_id"}
    assert err["request_id"].startswith("req_")
    assert response.headers["Request-Id"] == err["request_id"]
    if code:
        assert err["code"] == code
    return err


def test_auth_401_and_scopes_403(api, ecommerce_sql):
    _assert_envelope(api.client.get("/v1/usage"), 401, "invalid_api_key")
    _assert_envelope(api.client.get("/v1/usage", headers={"Authorization": "Bearer sk_test_nope"}), 401)
    reader = api.key(["datasets:read"])
    _assert_envelope(api.client.post("/v1/schemas", json={"ddl": ecommerce_sql}, headers=reader), 403,
                     "missing_scope")
    writer = api.key(["datasets:write", "recipes:read"])  # a typical CI key
    sid = _schema(api, writer, ecommerce_sql)
    assert api.client.get(f"/v1/schemas/{sid}", headers=writer).status_code == 200  # write implies read
    assert api.client.get("/v1/recipes", headers=writer).status_code == 200
    _assert_envelope(api.client.post("/v1/webhooks", json={"url": "https://example.com/h"}, headers=writer), 403)
    _assert_envelope(api.client.post("/v1/uploads", files={"file": ("a.csv", b"x\n1\n")}, headers=writer), 403)


def test_revoked_key_is_rejected(api):
    raw = api.raw_key(["admin"])
    headers = {"Authorization": f"Bearer {raw}"}
    key_id = api.client.get("/v1/keys", headers=headers).json()["data"][0]["id"]
    assert api.client.delete(f"/v1/keys/{key_id}", headers=headers).status_code == 200
    _assert_envelope(api.client.get("/v1/usage", headers=headers), 401)


def test_keys_are_stored_hashed(api):
    raw = api.raw_key(["admin"])
    db = (api.settings.data_dir / "synthetic.db").read_bytes()
    assert raw.encode() not in db


def test_dataset_job_flow(api, ecommerce_sql):
    h = api.key()
    sid = _schema(api, h, ecommerce_sql)
    started = time.perf_counter()
    r = api.client.post("/v1/datasets", headers=h, json={
        "schema_id": sid, "rows": {"customers": 200, "orders": 2000}, "seed": 42, "formats": ["csv", "parquet"],
        "scenarios": [{"type": "rare_event", "column": "orders.is_fraud", "rate": 0.02}]})
    assert r.status_code == 202
    assert time.perf_counter() - started < 0.5  # FR13 (single in-process measurement, not a p95)
    body = r.json()
    assert body["status"] in ("queued", "running") and body["engine_version"] and body["seed"] == 42
    done = wait_dataset(api.client, h, body["id"])
    assert done["status"] == "succeeded" and done["progress"] == 100
    assert done["row_counts"]["orders"] == 2000 and done["report"]["status"] == "pass"
    files = api.client.get(f"/v1/datasets/{body['id']}/files", headers=h).json()["data"]
    formats = {(f["table"], f["format"]) for f in files}
    assert ("orders", "csv") in formats and ("orders", "parquet") in formats
    csv_link = next(f for f in files if f["table"] == "customers" and f["format"] == "csv")
    download = api.client.get(csv_link["url"])  # signed link: no API key
    assert download.status_code == 200 and download.text.startswith("id,email")
    _assert_envelope(api.client.get(csv_link["url"] + "x"), 404, "link_invalid")
    report = api.client.get(f"/v1/datasets/{body['id']}/report", headers=h).json()
    assert report["integrity"]["fk_resolved_pct"] == 100.0
    assert "<html" in api.client.get(f"/v1/datasets/{body['id']}/report?format=html", headers=h).text
    _assert_envelope(api.client.get(f"/v1/datasets/{body['id']}/report?format=pdf", headers=h), 501)
    usage = api.client.get("/v1/usage", headers=h).json()
    assert usage["rows_generated"] == sum(done["row_counts"].values())


def test_failed_job_reports_error(api):
    h = api.key()
    schema = {"tables": [{"name": "t", "columns": [{"name": "id", "type": "int", "primary_key": True},
                                                   {"name": "u", "type": "int", "unique": True, "min": 1, "max": 5}]}]}
    sid = api.client.post("/v1/schemas", json={"schema": schema}, headers=h).json()["id"]
    ds = api.client.post("/v1/datasets", json={"schema_id": sid, "rows": {"t": 50}}, headers=h).json()
    done = wait_dataset(api.client, h, ds["id"])
    assert done["status"] == "failed" and done["error"]["code"] == "unique_range_too_small"


def test_idempotency_never_creates_a_second_job(api, ecommerce_sql):
    h = api.key()
    sid = _schema(api, h, ecommerce_sql)
    body = {"schema_id": sid, "rows": {"customers": 50}, "seed": 1}
    first = api.client.post("/v1/datasets", json=body, headers={**h, "Idempotency-Key": "k-1"})
    second = api.client.post("/v1/datasets", json=body, headers={**h, "Idempotency-Key": "k-1"})
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    assert second.headers.get("Idempotent-Replayed") == "true"
    assert len(api.client.get("/v1/datasets", headers=h).json()["data"]) == 1
    _assert_envelope(api.client.post("/v1/datasets", json={**body, "seed": 2},
                                     headers={**h, "Idempotency-Key": "k-1"}), 409, "idempotency_conflict")
    third = api.client.post("/v1/datasets", json=body, headers={**h, "Idempotency-Key": "k-2"})
    assert third.json()["id"] != first.json()["id"]


def test_error_envelope_everywhere(api, ecommerce_sql):
    h = api.key()
    _assert_envelope(api.client.get("/v1/does-not-exist", headers=h), 404, "not_found")
    _assert_envelope(api.client.get("/v1/datasets/ds_missing", headers=h), 404, "dataset_not_found")
    err = _assert_envelope(api.client.post("/v1/datasets", json={"rows": "lots"}, headers=h), 400,
                           "validation_error")
    assert "rows" in err["message"] and "lots" not in err["message"]  # no input values echoed
    _assert_envelope(api.client.post("/v1/schemas", json={"ddl": "SELECT 1"}, headers=h), 400, "no_tables_found")
    err = _assert_envelope(api.client.post("/v1/schemas", json={"ddl": "CREATE TABLE o (id int PRIMARY KEY, "
                                           "c int REFERENCES customers (id));"}, headers=h), 400, "invalid_schema")
    assert "customers" in err["message"]
    _assert_envelope(api.client.post("/v1/schemas", json={"ddl": ecommerce_sql, "yaml": "x"}, headers=h), 400,
                     "one_source_required")
    _assert_envelope(api.client.post("/v1/schemas", json={"prompt": "an online shop"}, headers=h), 501,
                     "planner_not_configured")


def test_planner_interface_is_pluggable(api_factory, fintech_yaml):
    class FakePlanner:
        name = "fake"

        def plan(self, prompt, max_tables=20):
            return Schema.from_yaml(fintech_yaml)

    with api_factory(planner=FakePlanner()) as api:
        r = api.client.post("/v1/schemas", json={"prompt": "a bank"}, headers=api.key())
        assert r.status_code == 201 and r.json()["source"] == "prompt:fake"


def test_preview_limits_and_integrity(api, ecommerce_sql):
    h = api.key()
    sid = _schema(api, h, ecommerce_sql)
    _assert_envelope(api.client.post("/v1/previews", json={"schema_id": sid, "rows": {"customers": 101}},
                                     headers=h), 400, "preview_limit_exceeded")
    r = api.client.post("/v1/previews", json={"schema_id": sid, "rows": {"customers": 100}, "seed": 3}, headers=h)
    assert r.status_code == 200
    tables = r.json()["tables"]
    assert all(len(t["rows"]) <= 100 for t in tables.values())
    assert len(tables["customers"]["rows"]) == 100
    customer_ids = {row["id"] for row in tables["customers"]["rows"]}
    assert {row["customer_id"] for row in tables["orders"]["rows"]} <= customer_ids


def test_webhooks_signed_and_retried(api, ecommerce_sql):
    h = api.key()
    hook = api.client.post("/v1/webhooks", json={"url": "https://hooks.example.com/x"}, headers=h).json()
    assert hook["secret"].startswith("whsec_")
    api.sink.fail_first = 2  # first two attempts fail → retried with backoff
    sid = _schema(api, h, ecommerce_sql)
    ds = api.client.post("/v1/datasets", json={"schema_id": sid, "rows": {"customers": 20}}, headers=h).json()
    assert wait_dataset(api.client, h, ds["id"])["status"] == "succeeded"
    assert wait_until(lambda: sum(1 for d in api.store.list_deliveries(hook["id"]) if d["status"] == "delivered") == 2)
    events = [json.loads(c["body"]) for c in api.sink.calls]
    assert {e["type"] for e in events} == {"dataset.succeeded", "report.ready"}
    assert len(api.sink.calls) == 4  # 2 failures + 2 deliveries
    for call in api.sink.calls:
        assert verify_signature(hook["secret"], call["headers"]["Synthetic-Signature"], call["body"])
        assert not verify_signature("whsec_wrong", call["headers"]["Synthetic-Signature"], call["body"])
    retried = [d for d in api.store.list_deliveries(hook["id"]) if d["attempts"] > 1]
    assert retried


def test_openapi_covers_all_mvp_endpoints(api):
    spec = api.client.get("/openapi.json").json()
    paths = {(m.upper(), p) for p, ops in spec["paths"].items() for m in ops}
    required = {
        ("POST", "/v1/schemas"), ("GET", "/v1/schemas/{schema_id}"), ("PATCH", "/v1/schemas/{schema_id}"),
        ("POST", "/v1/uploads"), ("POST", "/v1/previews"), ("POST", "/v1/datasets"),
        ("GET", "/v1/datasets/{dataset_id}"), ("GET", "/v1/datasets/{dataset_id}/files"),
        ("POST", "/v1/datasets/{dataset_id}/deliveries"), ("DELETE", "/v1/datasets/{dataset_id}"),
        ("GET", "/v1/datasets/{dataset_id}/report"), ("POST", "/v1/recipes"), ("GET", "/v1/recipes"),
        ("GET", "/v1/recipes/{recipe_id}/versions"), ("POST", "/v1/webhooks"), ("GET", "/v1/usage"),
    }
    assert required <= paths, required - paths
    assert api.client.get("/docs").status_code == 200
    assert "HTTPBearer" in spec["components"]["securitySchemes"]


def test_rate_limit_headers_and_429(api_factory):
    with api_factory(rate_limit_per_minute=3) as api:
        h = api.key()
        r = api.client.get("/v1/usage", headers=h)
        assert r.headers["RateLimit-Limit"] == "3" and r.headers["RateLimit-Remaining"] == "2"
        api.client.get("/v1/usage", headers=h)
        api.client.get("/v1/usage", headers=h)
        err = _assert_envelope(api.client.get("/v1/usage", headers=h), 429, "rate_limited")
        assert err["type"] == "rate_limit_error"


def test_test_key_row_limit(api_factory, ecommerce_sql):
    with api_factory(test_key_max_rows=1000) as api:
        h = api.key()
        sid = _schema(api, h, ecommerce_sql)
        _assert_envelope(api.client.post("/v1/datasets", json={"schema_id": sid, "rows": {"orders": 5000}},
                                         headers=h), 400, "test_key_row_limit")
        live = api.key(mode="live")
        assert api.client.post("/v1/datasets", json={"schema_id": sid, "rows": {"customers": 5, "orders": 5000}},
                               headers=live).status_code == 202


def test_schema_patch_and_recipes(api, ecommerce_sql):
    h = api.key()
    sid = _schema(api, h, ecommerce_sql)
    patched = api.client.patch(f"/v1/schemas/{sid}", headers=h,
                               json={"columns": {"customers.phone": {"null_rate": 0.5}}}).json()
    assert patched["version"] == 2
    _assert_envelope(api.client.patch(f"/v1/schemas/{sid}", headers=h,
                                      json={"columns": {"customers.nope": {"pii": True}}}), 404)
    v1 = api.client.post("/v1/recipes", headers=h, json={"name": "orders", "schema_id": sid,
                                                          "rows": {"customers": 30}, "seed": 7}).json()
    v2 = api.client.post("/v1/recipes", headers=h, json={"name": "orders", "schema_id": sid,
                                                          "rows": {"customers": 40}, "seed": 7}).json()
    assert v1["id"] == v2["id"] and (v1["version"], v2["version"]) == (1, 2)
    versions = api.client.get(f"/v1/recipes/{v1['id']}/versions", headers=h).json()["data"]
    assert [v["version"] for v in versions] == [2, 1]
    ds = api.client.post("/v1/datasets", json={"recipe_id": v1["id"], "recipe_version": 1}, headers=h).json()
    done = wait_dataset(api.client, h, ds["id"])
    assert done["row_counts"]["customers"] == 30 and done["seed"] == 7


def test_upload_generate_and_retention(api, sample_csv):
    h = api.key()
    up = api.client.post("/v1/uploads", headers=h, data={"table_name": "customers"},
                         files={"file": ("customers.csv", sample_csv.read_bytes(), "text/csv")})
    assert up.status_code == 201, up.text
    up = up.json()
    assert up["rows"] == 2000 and any(c["name"] == "email" and c["pii"] for c in up["columns"])
    ds = api.client.post("/v1/datasets", json={"upload_id": up["id"], "rows": {"customers": 500}, "seed": 1},
                         headers=h).json()
    done = wait_dataset(api.client, h, ds["id"])
    assert done["status"] == "succeeded", done
    report = api.client.get(f"/v1/datasets/{ds['id']}/report", headers=h).json()
    assert report["mode"] == "sample" and report["privacy"]["applicable"]
    blob = api.ctx.blobs.local_path(api.store.get("upload", up["id"])["blob_key"])
    assert blob.exists()
    # Before the window: kept. After 24 h: deleted (FR11).
    assert cleanup_expired_uploads(api.store, api.ctx.blobs, 24, at=time.time() + 3600) == []
    assert cleanup_expired_uploads(api.store, api.ctx.blobs, 24, at=time.time() + 24 * 3600 + 5) == [up["id"]]
    assert not blob.exists()
    assert api.client.get(f"/v1/uploads/{up['id']}", headers=h).json()["status"] == "deleted"
    _assert_envelope(api.client.post("/v1/datasets", json={"upload_id": up["id"]}, headers=h), 422,
                     "upload_deleted")


def test_zero_retention_deletes_right_after_job(api, sample_csv):
    h = api.key()
    up = api.client.post("/v1/uploads", headers=h, data={"retention_hours": "0"},
                         files={"file": ("c.csv", sample_csv.read_bytes())}).json()
    ds = api.client.post("/v1/datasets", json={"upload_id": up["id"], "rows": {"c": 100}}, headers=h).json()
    assert wait_dataset(api.client, h, ds["id"])["status"] == "succeeded"
    assert wait_until(lambda: api.store.get("upload", up["id"])["status"] == "deleted")


def test_delete_dataset_removes_outputs_and_source(api, sample_csv):
    h = api.key()
    up = api.client.post("/v1/uploads", headers=h, files={"file": ("c.csv", sample_csv.read_bytes())}).json()
    ds = api.client.post("/v1/datasets", json={"upload_id": up["id"], "rows": {"c": 100}}, headers=h).json()
    wait_dataset(api.client, h, ds["id"])
    out_dir = api.settings.data_dir / "blobs" / "datasets" / "ws_default" / ds["id"]
    assert out_dir.exists()
    assert api.client.delete(f"/v1/datasets/{ds['id']}", headers=h).json()["deleted"]
    assert not out_dir.exists()
    assert api.store.get("upload", up["id"])["status"] == "deleted"
    _assert_envelope(api.client.get(f"/v1/datasets/{ds['id']}", headers=h), 404)


def test_delivery_without_postgres_driver_or_with_it(api, ecommerce_sql):
    h = api.key()
    sid = _schema(api, h, ecommerce_sql)
    ds = api.client.post("/v1/datasets", json={"schema_id": sid, "rows": {"customers": 5}}, headers=h).json()
    wait_dataset(api.client, h, ds["id"])
    r = api.client.post(f"/v1/datasets/{ds['id']}/deliveries", headers=h,
                        json={"dsn": "postgresql://u:secret@127.0.0.1:1/none"})
    try:
        import psycopg  # noqa: F401
    except ImportError:
        _assert_envelope(r, 501, "connector_unavailable")
        return
    assert r.status_code == 202
    assert wait_until(lambda: api.client.get(f"/v1/datasets/{ds['id']}", headers=h).json()["deliveries"][0]["status"]
                      in ("failed", "succeeded"))
    doc = api.client.get(f"/v1/datasets/{ds['id']}", headers=h).json()
    assert "secret" not in json.dumps(doc)  # the DSN password is never stored or echoed


def test_web_ui_served(api):
    r = api.client.get("/")
    assert r.status_code == 200 and "Synthetic" in r.text
    assert api.client.get("/static/app.js").status_code == 200
