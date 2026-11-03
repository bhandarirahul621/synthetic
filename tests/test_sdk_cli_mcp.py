"""SDK round trip, SDK/OpenAPI contract, CLI local generate, and the MCP tools."""

import asyncio
import json
import re

import pandas as pd
import pytest
from typer.testing import CliRunner

from synthetic.cli import app as cli_app
from synthetic.mcp_server import build_server
from synthetic.sdk import Client, JobFailed, SyntheticAPIError


@pytest.fixture
def sdk(api):
    client = Client(api_key=api.raw_key(["admin"]), base_url="http://testserver", http_client=api.client)
    yield client


def test_sdk_round_trip(sdk, tmp_path, ecommerce_sql):
    schema = sdk.schemas.create(ddl=ecommerce_sql)
    preview = sdk.previews.create(schema_id=schema["id"], rows={"customers": 5})
    assert len(preview["tables"]["customers"]["rows"]) == 5
    ds = sdk.datasets.create(schema_id=schema["id"], rows={"customers": 100, "orders": 500}, seed=42,
                             formats=["parquet"],
                             scenarios=[{"type": "rare_event", "column": "orders.is_fraud", "rate": 0.02}])
    ds.wait(timeout=60, poll_interval=0.05)
    assert ds.status == "succeeded"
    paths = ds.download(tmp_path)
    orders = pd.read_parquet(tmp_path / "orders.parquet")
    assert len(orders) == 500 and int(orders["is_fraud"].sum()) == 10
    assert any(p.name == "schema.json" for p in paths)
    report = sdk.reports.get(ds.id)
    assert report["overall"]["status"] == "pass"
    assert sdk.usage()["rows_generated"] > 0
    recipe = sdk.recipes.create(name="ci", schema_id=schema["id"], rows={"customers": 10})
    assert sdk.recipes.versions(recipe["id"])[0]["version"] == 1
    with pytest.raises(SyntheticAPIError) as e:
        sdk.datasets.get("ds_missing")
    assert e.value.status == 404 and e.value.request_id.startswith("req_")


def test_sdk_wait_raises_on_failure(sdk):
    schema = sdk.schemas.create(schema={"tables": [{"name": "t", "columns": [
        {"name": "id", "type": "int", "primary_key": True},
        {"name": "u", "type": "category", "unique": True, "allowed_values": ["a"]}]}]})
    with pytest.raises(JobFailed):
        sdk.datasets.create(schema_id=schema["id"], rows={"t": 5}).wait(timeout=30, poll_interval=0.05)


def test_sdk_retry_reuses_idempotency_key(sdk, ecommerce_sql):
    schema = sdk.schemas.create(ddl=ecommerce_sql)
    a = sdk.datasets.create(schema_id=schema["id"], rows={"customers": 5}, idempotency_key="same")
    b = sdk.datasets.create(schema_id=schema["id"], rows={"customers": 5}, idempotency_key="same")
    assert a.id == b.id


def test_sdk_paths_exist_in_openapi(api):
    """Contract test: every path the SDK calls is in the published OpenAPI spec (FR12)."""
    import inspect

    import synthetic.sdk as sdk_module

    spec_paths = set(api.client.get("/openapi.json").json()["paths"])
    templates = {re.sub(r"\{[^}]+\}", "{}", p) for p in spec_paths}
    used = set(re.findall(r'"(/v1/[^"]*)"', inspect.getsource(sdk_module)))
    used |= {re.sub(r"\{[^}]+\}", "{}", p) for p in re.findall(r'f"(/v1/[^"]*)"', inspect.getsource(sdk_module))}
    assert used, "no paths found"
    for path in used:
        assert re.sub(r"\{[^}]+\}", "{}", path) in templates, path


def test_cli_local_generate_and_report(tmp_path):
    runner = CliRunner()
    out = tmp_path / "out"
    result = runner.invoke(cli_app, ["generate", "--schema", "examples/ecommerce.sql",
                                     "--rows", "customers=200,orders=1000", "--seed", "42", "--out", str(out),
                                     "--format", "parquet,csv", "--scenario", "orders.is_fraud=0.02"])
    assert result.exit_code == 0, result.output
    assert pd.read_parquet(out / "orders.parquet").shape[0] == 1000
    assert (out / "report.json").exists() and (out / "schema.json").exists()
    again = runner.invoke(cli_app, ["generate", "--schema", "examples/ecommerce.sql",
                                    "--rows", "customers=200,orders=1000", "--seed", "42", "--out",
                                    str(tmp_path / "again"), "--format", "csv", "--scenario", "orders.is_fraud=0.02"])
    assert again.exit_code == 0
    assert (out / "orders.csv").read_bytes() == (tmp_path / "again" / "orders.csv").read_bytes()
    report = runner.invoke(cli_app, ["report", "--data", str(out)])
    assert report.exit_code == 0 and "Overall: pass" in report.output
    bad = runner.invoke(cli_app, ["generate", "--schema", "examples/ecommerce.sql", "--rows", "nope=1",
                                  "--out", str(tmp_path / "bad")])
    assert bad.exit_code == 1 and "unknown" in bad.output.lower()


def test_cli_sample_generate(tmp_path, sample_csv):
    runner = CliRunner()
    out = tmp_path / "s"
    result = runner.invoke(cli_app, ["generate", "--sample", str(sample_csv), "--table", "customers",
                                     "--rows", "customers=300", "--seed", "3", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "exact copy" in result.output
    report = runner.invoke(cli_app, ["report", "--data", str(out), "--sample", str(sample_csv)])
    assert report.exit_code == 0 and "membership-inference" in report.output


def test_cli_keys_create(tmp_path):
    runner = CliRunner()
    result = runner.invoke(cli_app, ["keys", "create", "--scopes", "datasets:read,datasets:write",
                                     "--data-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert re.search(r"sk_test_\S+", result.output)
    listed = runner.invoke(cli_app, ["keys", "list", "--data-dir", str(tmp_path)])
    assert "datasets:read,datasets:write" in listed.output and "sk_test_" in listed.output
    bad = runner.invoke(cli_app, ["keys", "create", "--scopes", "root", "--data-dir", str(tmp_path)])
    assert bad.exit_code == 1


def test_mcp_tools(sdk, ecommerce_sql):
    server = build_server(lambda: sdk)

    async def scenario():
        names = {t.name for t in await server.list_tools()}
        assert names == {"create_schema", "preview", "create_dataset", "get_dataset", "get_report", "list_recipes"}

        async def call(name, args):
            result = await server.call_tool(name, args)
            return json.loads(result.content[0].text)

        schema = await call("create_schema", {"ddl": ecommerce_sql})
        preview = await call("preview", {"schema_id": schema["id"], "rows": {"customers": 80}})
        assert len(preview["tables"]["customers"]["rows"]) == 20  # capped for agent context
        ds = await call("create_dataset", {"schema_id": schema["id"], "rows": {"customers": 50}, "seed": 1})
        for _ in range(400):
            status = await call("get_dataset", {"dataset_id": ds["id"]})
            if status["status"] == "succeeded":
                break
            await asyncio.sleep(0.05)
        assert status["status"] == "succeeded"
        assert all(f["url"].startswith("http://testserver/v1/files/") for f in status["files"])
        assert "rows" not in json.dumps(status["files"][0]).replace('"rows":', "")  # links, not data
        report = await call("get_report", {"dataset_id": ds["id"]})
        assert report["overall"]["status"] == "pass"
        assert (await call("list_recipes", {}))["recipes"] == []

    asyncio.run(scenario())
