"""FR15: no source-data values appear in API logs, errors or webhooks (automated log scan)."""

import json
import logging

from conftest import wait_dataset
from synthetic.engine.fit import read_sample

SECRETS = ["QUASAR-7731", "zelda.secret@private.invalid", "Ophelia Wintermute", "424242.17"]


def test_no_source_values_in_logs_errors_or_webhooks(api, sample_csv, caplog, tmp_path):
    caplog.set_level(logging.DEBUG)
    df = read_sample(sample_csv)
    df["plan"] = df["plan"].where(df.index % 50 != 0, "QUASAR-7731")  # a learnable category value
    df.loc[0, "email"] = "zelda.secret@private.invalid"
    df.loc[1, "full_name"] = "Ophelia Wintermute"
    df["monthly_spend"] = df["monthly_spend"].astype(float)
    df.loc[2, "monthly_spend"] = 424242.17
    path = tmp_path / "customers.csv"
    df.to_csv(path, index=False)
    raw = path.read_bytes()

    h = api.key()
    api.client.post("/v1/webhooks", json={"url": "https://hooks.example.com/x"}, headers=h)
    up = api.client.post("/v1/uploads", headers=h, files={"file": ("customers.csv", raw)}).json()
    api.client.post("/v1/previews", json={"upload_id": up["id"], "rows": {"customers": 50}}, headers=h)
    ds = api.client.post("/v1/datasets", json={"upload_id": up["id"], "rows": {"customers": 500}}, headers=h).json()
    assert wait_dataset(api.client, h, ds["id"])["status"] == "succeeded"
    report = api.client.get(f"/v1/datasets/{ds['id']}/report", headers=h).text

    # Error paths that see source bytes: a corrupt "parquet" with the values inside, and bad JSON input.
    bad = api.client.post("/v1/uploads", headers=h, files={"file": ("x.parquet", raw)})
    invalid = api.client.post("/v1/previews", json={"upload_id": up["id"], "rows": {"customers": "QUASAR-7731"}},
                              headers=h)
    errors = bad.text + invalid.text
    assert bad.status_code == 422 and invalid.status_code == 400

    webhook_bodies = " ".join(c["body"].decode() for c in api.sink.calls)
    haystack = caplog.text + errors + webhook_bodies
    for secret in SECRETS:
        assert secret not in haystack, secret
    # PII and extreme values must not reach the report either (the category is a learned, non-PII value).
    for secret in SECRETS[1:]:
        assert secret not in report
    assert json.loads(report)["mode"] == "sample"
    assert "request method=POST path=/v1/uploads" in caplog.text  # the scan really saw the logs
    files = api.client.get(f"/v1/datasets/{ds['id']}/files", headers=h).json()["data"]
    api.client.get(files[0]["url"])
    server_log = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("synthetic"))
    assert files[0]["url"].split("/")[-1] not in server_log  # download tokens are redacted
