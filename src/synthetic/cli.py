"""The ``synthetic`` command line tool (PRD F6).

Local commands need no server::

    synthetic generate --schema examples/ecommerce.sql --rows customers=2000,orders=50000 \\
        --seed 42 --out ./out --format parquet
    synthetic report --data ./out

Server commands::

    synthetic serve                      # run the API + web UI
    synthetic keys create --scopes admin # create the first API key
    synthetic remote generate --recipe orders --rows orders=10000 --download ./out
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import typer

from synthetic.engine.version import ENGINE_VERSION

app = typer.Typer(help="Synthetic: privacy-safe synthetic data.", no_args_is_help=True, add_completion=False)
keys_app = typer.Typer(help="Manage API keys (writes directly to the local metadata store).", no_args_is_help=True)
remote_app = typer.Typer(help="Talk to a Synthetic server through the SDK.", no_args_is_help=True)
app.add_typer(keys_app, name="keys")
app.add_typer(remote_app, name="remote")


# ---------------------------------------------------------------------------
# argument parsing helpers
# ---------------------------------------------------------------------------


def parse_rows(text: str | None) -> dict[str, int]:
    """``"customers=2000,orders=50000"`` → ``{"customers": 2000, "orders": 50000}``."""
    out: dict[str, int] = {}
    for part in (text or "").split(","):
        part = part.strip()
        if not part:
            continue
        name, sep, value = part.partition("=")
        if not sep:
            raise typer.BadParameter(f"expected table=count, got {part!r}")
        try:
            out[name.strip()] = int(value.replace("_", ""))
        except ValueError:
            raise typer.BadParameter(f"row count for {name!r} must be an integer") from None
    return out


def parse_scenario(text: str) -> dict:
    """``"orders.is_fraud=0.02"`` or ``"orders.status:refunded=0.05"`` → a rare_event scenario."""
    target, sep, rate = text.rpartition("=")
    if not sep:
        raise typer.BadParameter(f"expected table.column=rate, got {text!r}")
    column, _, value = target.partition(":")
    scenario = {"type": "rare_event", "column": column, "rate": float(rate)}
    if value:
        scenario["value"] = value
    return scenario


def _split(text: str) -> list[str]:
    return [p.strip() for p in text.split(",") if p.strip()]


def _fail(exc: Exception) -> None:
    from synthetic.errors import SyntheticError

    if isinstance(exc, SyntheticError):
        typer.echo(f"error [{exc.code}]: {exc.message}", err=True)
    else:
        typer.echo(f"error: {exc}", err=True)
    raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# local commands
# ---------------------------------------------------------------------------


@app.command()
def version() -> None:
    """Print the package and engine versions."""
    from synthetic import __version__

    typer.echo(f"synthetic {__version__} (engine {ENGINE_VERSION})")


@app.command()
def generate(
    schema: Path | None = typer.Option(None, help="Schema file: .sql (DDL), .json or .yaml."),
    rows: str | None = typer.Option(None, help="Rows per table, e.g. customers=2000,orders=50000."),
    seed: int = typer.Option(0, help="Random seed. Same schema + seed + engine version = same bytes."),
    out: Path = typer.Option(Path("out"), help="Output directory."),
    format: str = typer.Option("csv", "--format", "-f", help="Comma-separated: csv,parquet,json,sql."),
    dialect: str = typer.Option("postgres", help="SQL dialect of a .sql schema: postgres or mysql."),
    scenario: list[str] = typer.Option([], help="Rare event, e.g. orders.is_fraud=0.02 (repeatable)."),
    sample: Path | None = typer.Option(None, help="CSV/Parquet sample to learn from (FR3)."),
    table: str | None = typer.Option(None, help="Table name of the sample (default: file name)."),
    pii: list[str] = typer.Option([], help="Extra sample column to treat as PII (repeatable)."),
    report: bool = typer.Option(True, help="Also write report.json and report.html."),
) -> None:
    """Generate a dataset locally (no server needed)."""
    from synthetic import pipeline
    from synthetic.engine.fit import read_sample
    from synthetic.engine.scenarios import Scenario
    from synthetic.export import write_dataset
    from synthetic.report.html import render_html
    from synthetic.schema import load_schema

    try:
        loaded = load_schema(schema, dialect=dialect) if schema else None
        sample_df = read_sample(sample) if sample else None
        sample_table = table or (sample.stem if sample else None)
        result = pipeline.run(loaded, rows=parse_rows(rows), seed=seed,
                              scenarios=[Scenario(**parse_scenario(s)) for s in scenario], sample=sample_df,
                              sample_table=sample_table, pii_columns=pii, with_report=report)
        files = write_dataset(result.tables, result.schema, out, _split(format))
        (out / "schema.json").write_text(result.schema.to_json(), encoding="utf-8")
        meta = {k: result.generation.metadata[k] for k in ("engine_version", "seed", "scenarios", "requested_rows",
                                                           "rows", "rows_dropped_no_copy")}
        meta["sample_table"] = sample_table
        (out / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        if report:
            (out / "report.json").write_text(json.dumps(result.report, indent=2, default=str), encoding="utf-8")
            (out / "report.html").write_text(render_html(result.report), encoding="utf-8")
    except Exception as exc:  # show a clean message instead of a traceback
        _fail(exc)
        return
    for f in files:
        typer.echo(f"{f['filename']:<28} {f['rows']:>10,} rows  {f['bytes']:>12,} bytes  sha256 {f['sha256'][:16]}…")
    if report:
        typer.echo(f"\nReport: {out / 'report.html'}\n{result.report['summary']}")


def _load_tables(schema, data: Path) -> dict:
    from synthetic.export import read_table_file

    tables = {}
    for name in schema.table_names:
        for suffix in (".parquet", ".csv"):
            path = data / f"{name}{suffix}"
            if path.exists():
                tables[name] = read_table_file(path)
                break
    return tables


@app.command("report")
def report_cmd(
    data: Path = typer.Option(..., help="Directory with generated table files (.parquet or .csv)."),
    schema: Path | None = typer.Option(None, help="Schema file (default: DATA/schema.json)."),
    sample: Path | None = typer.Option(None, help="The sample the data was learned from, if any."),
    table: str | None = typer.Option(None, help="Table name of the sample."),
    seed: int | None = typer.Option(None, help="Generation seed (default: from DATA/metadata.json, else 0)."),
    out: Path | None = typer.Option(None, help="Write report JSON here (default: DATA/report.json)."),
    html: Path | None = typer.Option(None, help="Write report HTML here (default: DATA/report.html)."),
) -> None:
    """Build a Fidelity and Privacy Report for files on disk."""
    import numpy as np

    from synthetic.engine.fit import learn_from_sample, read_sample
    from synthetic.report.build import build_report
    from synthetic.report.html import render_html
    from synthetic.schema import load_schema

    try:
        loaded = load_schema(schema or data / "schema.json")
        tables = _load_tables(loaded, data)
        meta_path = data / "metadata.json"
        metadata = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        seed = seed if seed is not None else int(metadata.get("seed", 0))
        metadata.update(seed=seed, engine_version=metadata.get("engine_version", ENGINE_VERSION))
        sample_info = None
        if sample:
            name = table or metadata.get("sample_table") or sample.stem
            src = read_sample(sample)
            fit = learn_from_sample(src, name, seed=seed, rng=np.random.default_rng(seed))
            sample_info = {"table": name, "source": src, "train": fit.train, "holdout": fit.holdout,
                           "columns": fit.modeled_columns, "detections": fit.detection_summary()}
        result = build_report(loaded, tables, metadata, sample=sample_info)
    except Exception as exc:
        _fail(exc)
        return
    out = out or data / "report.json"
    html = html or data / "report.html"
    out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    html.write_text(render_html(result), encoding="utf-8")
    typer.echo(result["summary"])
    typer.echo(f"\nWrote {out} and {html}")


# ---------------------------------------------------------------------------
# server and keys
# ---------------------------------------------------------------------------


def _settings(data_dir: Path | None):
    from synthetic.api.settings import Settings

    settings = Settings.from_env()
    if data_dir is not None:
        settings.data_dir = data_dir
    return settings


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Interface to bind (use 0.0.0.0 in Docker)."),
    port: int = typer.Option(8000),
    data_dir: Path | None = typer.Option(None, help="Override SYNTHETIC_DATA_DIR (default ./var)."),
    dev_bootstrap: bool = typer.Option(False, help="Create an admin test key on first start."),
) -> None:
    """Run the API server and web UI."""
    import uvicorn

    from synthetic.api.app import create_app

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = _settings(data_dir)
    settings.dev_bootstrap = settings.dev_bootstrap or dev_bootstrap
    # Uvicorn's access log prints full URLs (including signed download tokens); ours does not.
    uvicorn.run(create_app(settings), host=host, port=port, access_log=False, log_config=None)


@keys_app.command("create")
def keys_create(
    scopes: str = typer.Option(..., help="Comma-separated, e.g. datasets:read,datasets:write or admin."),
    live: bool = typer.Option(False, "--live", help="Create an sk_live_ key (default sk_test_)."),
    name: str | None = typer.Option(None),
    data_dir: Path | None = typer.Option(None, help="Override SYNTHETIC_DATA_DIR (default ./var)."),
) -> None:
    """Create an API key. The key is printed once and stored only as a hash."""
    from synthetic.api.auth import create_api_key
    from synthetic.api.store import SQLiteStore

    settings = _settings(data_dir)
    store = SQLiteStore(settings.data_dir / "synthetic.db")
    try:
        raw, record = create_api_key(store, _split(scopes), mode="live" if live else "test", name=name)
    except Exception as exc:
        _fail(exc)
        return
    finally:
        store.close()
    typer.echo(raw)
    typer.echo(f"id={record['id']} scopes={','.join(record['scopes'])} (store it now; it will not be shown again)",
               err=True)


@keys_app.command("list")
def keys_list(data_dir: Path | None = typer.Option(None)) -> None:
    """List keys (prefix, scopes, status). Secrets are never shown."""
    from synthetic.api.auth import public_key_record
    from synthetic.api.store import SQLiteStore

    store = SQLiteStore(_settings(data_dir).data_dir / "synthetic.db")
    for record in store.list_keys():
        pub = public_key_record(record)
        status = "revoked" if pub["revoked_at"] else "active"
        typer.echo(f"{pub['id']}  {pub['prefix']}  {status:<8} {','.join(pub['scopes'])}  {pub['name'] or ''}")
    store.close()


@keys_app.command("revoke")
def keys_revoke(key_id: str, data_dir: Path | None = typer.Option(None)) -> None:
    """Revoke a key by its id (``key_...``)."""
    from synthetic.api.auth import DEFAULT_WORKSPACE
    from synthetic.api.store import SQLiteStore

    store = SQLiteStore(_settings(data_dir).data_dir / "synthetic.db")
    ok = store.revoke_key(key_id, DEFAULT_WORKSPACE)
    store.close()
    typer.echo("revoked" if ok else "no such active key")
    if not ok:
        raise typer.Exit(code=1)


@app.command()
def cleanup(data_dir: Path | None = typer.Option(None)) -> None:
    """Delete uploaded source data whose retention window has passed (FR11)."""
    from synthetic.api.blobs import LocalBlobStore
    from synthetic.api.retention import cleanup_expired_uploads
    from synthetic.api.store import SQLiteStore

    settings = _settings(data_dir)
    store = SQLiteStore(settings.data_dir / "synthetic.db")
    deleted = cleanup_expired_uploads(store, LocalBlobStore(settings.data_dir / "blobs"), settings.retention_hours)
    store.close()
    typer.echo(f"deleted {len(deleted)} upload(s)")


@app.command()
def mcp() -> None:
    """Run the MCP server over stdio (for Claude Code and other MCP clients)."""
    from synthetic.mcp_server import main

    main()


# ---------------------------------------------------------------------------
# remote commands (SDK)
# ---------------------------------------------------------------------------


def _client(api_key: str | None, base_url: str | None):
    from synthetic.sdk import Client

    try:
        return Client(api_key=api_key, base_url=base_url)
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None


_KEY = typer.Option(None, envvar="SYNTHETIC_API_KEY", help="API key (or set SYNTHETIC_API_KEY).")
_URL = typer.Option(None, envvar="SYNTHETIC_BASE_URL", help="Server URL (default http://localhost:8000).")


@remote_app.command("generate")
def remote_generate(
    schema: Path | None = typer.Option(None, help="Schema file to upload first (.sql/.json/.yaml)."),
    schema_id: str | None = typer.Option(None, help="An existing schema id."),
    recipe: str | None = typer.Option(None, help="Recipe name or id."),
    rows: str | None = typer.Option(None, help="Rows per table, e.g. orders=10000."),
    seed: int | None = typer.Option(None),
    format: str | None = typer.Option(None, "--format", "-f"),
    dialect: str = typer.Option("postgres"),
    scenario: list[str] = typer.Option([]),
    wait: bool = typer.Option(True, help="Wait for the job to finish."),
    download: Path | None = typer.Option(None, help="Download files into this directory."),
    api_key: str | None = _KEY,
    base_url: str | None = _URL,
) -> None:
    """Start a dataset job on a server (e.g. from CI) and optionally download it."""
    from synthetic.sdk import JobFailed, SyntheticAPIError

    client = _client(api_key, base_url)
    try:
        recipe_id = None
        if recipe:
            matches = [r for r in client.recipes.list() if recipe in (r["id"], r["name"])]
            if not matches:
                typer.echo(f"error: no recipe named {recipe!r}", err=True)
                raise typer.Exit(code=1)
            recipe_id = matches[0]["id"]
        if schema is not None:
            text = schema.read_text(encoding="utf-8")
            kind = {".sql": "ddl", ".yaml": "yaml", ".yml": "yaml"}.get(schema.suffix.lower(), "schema")
            payload = {"ddl": text, "dialect": dialect} if kind == "ddl" else (
                {"yaml": text} if kind == "yaml" else {"schema": json.loads(text)})
            schema_id = client.schemas.create(**payload)["id"]
        ds = client.datasets.create(schema_id=schema_id, recipe_id=recipe_id, rows=parse_rows(rows) or None,
                                    seed=seed, formats=_split(format) if format else None,
                                    scenarios=[parse_scenario(s) for s in scenario] or None)
        typer.echo(f"dataset {ds.id} {ds.status} (seed {ds['seed']}, engine {ds['engine_version']})")
        if wait or download:
            ds.wait(poll_interval=1.0)
            typer.echo(f"dataset {ds.id} succeeded: {ds['row_counts']}")
            typer.echo(ds["report"]["summary"])
        if download:
            for path in ds.download(download):
                typer.echo(f"downloaded {path}")
    except (SyntheticAPIError, JobFailed) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from None
    finally:
        client.close()


@remote_app.command("report")
def remote_report(dataset_id: str, html: Path | None = typer.Option(None, help="Save the HTML report here."),
                  api_key: str | None = _KEY, base_url: str | None = _URL) -> None:
    """Print a dataset's report summary (and optionally save the HTML)."""
    client = _client(api_key, base_url)
    try:
        report = client.reports.get(dataset_id)
        typer.echo(report["summary"])
        if html:
            html.write_text(client.reports.get(dataset_id, format="html"), encoding="utf-8")
    finally:
        client.close()


@remote_app.command("recipes")
def remote_recipes(api_key: str | None = _KEY, base_url: str | None = _URL) -> None:
    """List recipes on the server."""
    client = _client(api_key, base_url)
    try:
        for r in client.recipes.list():
            typer.echo(f"{r['id']}  {r['name']}  v{r['version']}  rows={r['config']['rows']}")
    finally:
        client.close()


def main() -> None:  # pragma: no cover - console entry point
    app(sys.argv[1:])


if __name__ == "__main__":  # pragma: no cover
    main()
