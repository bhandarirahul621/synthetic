"""MCP server: lets AI agents (Claude Code and other MCP clients) use Synthetic (PRD F6, §9.1.7).

MCP (Model Context Protocol) is a standard way for an AI assistant to call
tools. This server is a thin layer over the SDK, which calls the REST API,
so agents get exactly the same behaviour as the UI and CLI (G4).

Tools return **small previews and links, never full datasets**, so the
agent's context window stays small.

Run (stdio transport)::

    SYNTHETIC_API_KEY=sk_test_... SYNTHETIC_BASE_URL=http://localhost:8000 synthetic mcp
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from synthetic.sdk import Client, SyntheticAPIError

#: At most this many rows per table are returned to the agent by ``preview``.
MCP_PREVIEW_ROWS = 20

INSTRUCTIONS = (
    "Synthetic generates privacy-safe synthetic datasets. Typical flow: create_schema (from SQL DDL or a "
    "JSON schema) -> preview -> create_dataset -> get_dataset until status is 'succeeded' -> get_report. "
    "Datasets are returned as download links, never inline."
)


def build_server(client_factory: Callable[[], Client] | None = None) -> MCPServer:
    """Create the MCP server. ``client_factory`` lets tests inject an SDK client."""
    factory = client_factory or (lambda: Client(api_key=os.environ.get("SYNTHETIC_API_KEY"),
                                                base_url=os.environ.get("SYNTHETIC_BASE_URL")))
    server = MCPServer(name="synthetic", instructions=INSTRUCTIONS)
    state: dict[str, Client] = {}

    def client() -> Client:
        if "client" not in state:
            state["client"] = factory()
        return state["client"]

    def absolute(url: str) -> str:
        return url if url.startswith("http") else client().base_url + url

    def call(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except SyntheticAPIError as exc:
            raise ToolError(f"{exc.code}: {exc.message} (request_id={exc.request_id})") from None

    @server.tool()
    def create_schema(ddl: str | None = None, dialect: str = "postgres", schema: dict | None = None,
                      name: str | None = None) -> dict:
        """Create a schema from SQL DDL (Postgres or MySQL) or a Synthetic JSON schema.

        Returns the schema id, its tables and any import warnings.
        """
        if (ddl is None) == (schema is None):
            raise ToolError("Pass exactly one of 'ddl' or 'schema'.")
        result = call(lambda: client().schemas.create(ddl=ddl, dialect=dialect if ddl else None,
                                                      schema=schema, name=name))
        return {"id": result["id"], "version": result["version"], "tables": result["tables"],
                "warnings": result["warnings"]}

    @server.tool()
    def preview(schema_id: str, rows: dict[str, int] | None = None, seed: int = 0,
                scenarios: list[dict] | None = None) -> dict:
        """Preview a few rows per table (at most 20 here) for a schema, without starting a job."""
        capped = {t: min(n, MCP_PREVIEW_ROWS) for t, n in (rows or {}).items()}
        result = call(lambda: client().previews.create(schema_id=schema_id, rows=capped or None, seed=seed,
                                                       scenarios=scenarios))
        tables = {name: {"columns": t["columns"], "rows": t["rows"][:MCP_PREVIEW_ROWS]}
                  for name, t in result["tables"].items()}
        return {"seed": result["seed"], "engine_version": result["engine_version"], "tables": tables}

    @server.tool()
    def create_dataset(schema_id: str | None = None, recipe_id: str | None = None,
                       rows: dict[str, int] | None = None, seed: int | None = None,
                       scenarios: list[dict] | None = None, formats: list[str] | None = None) -> dict:
        """Start a generation job. Example scenario: {"type": "rare_event", "column": "orders.is_fraud", "rate": 0.02}.

        Returns immediately with the dataset id; poll get_dataset for progress.
        """
        ds = call(lambda: client().datasets.create(schema_id=schema_id, recipe_id=recipe_id, rows=rows,
                                                   seed=seed, scenarios=scenarios, formats=formats))
        return {"id": ds.id, "status": ds.status, "seed": ds["seed"], "engine_version": ds["engine_version"],
                "links": ds["links"]}

    @server.tool()
    def get_dataset(dataset_id: str) -> dict:
        """Job status and progress; once succeeded, row counts and download links (they expire)."""
        ds = call(lambda: client().datasets.get(dataset_id))
        out: dict[str, Any] = {"id": ds.id, "status": ds.status, "progress": ds["progress"],
                               "row_counts": ds["row_counts"], "error": ds["error"]}
        if ds.status == "succeeded":
            out["report"] = ds["report"]
            out["files"] = [{"table": f["table"], "format": f["format"], "rows": f.get("rows"),
                             "bytes": f.get("bytes"), "url": absolute(f["url"]), "expires_at": f["expires_at"]}
                            for f in call(lambda: client().datasets.files(dataset_id))]
        return out

    @server.tool()
    def get_report(dataset_id: str) -> dict:
        """The Fidelity and Privacy Report summary: overall status, scores, privacy checks, summary text."""
        report = call(lambda: client().reports.get(dataset_id))
        privacy = report.get("privacy", {})
        return {
            "overall": report["overall"], "summary": report["summary"],
            "integrity": {"status": report["integrity"]["status"],
                          "fk_resolved_pct": report["integrity"]["fk_resolved_pct"],
                          "constraint_violations": report["integrity"]["constraint_violations"]["total"]},
            "fidelity": {"status": report["fidelity"]["status"], "score": report["fidelity"]["score"]},
            "privacy": {"status": privacy.get("status"),
                        "checks": [{"name": c["name"], "value": c["value"], "status": c["status"]}
                                   for c in privacy.get("checks", [])]},
            "html_report": absolute(f"/v1/datasets/{dataset_id}/report?format=html"),
        }

    @server.tool()
    def list_recipes() -> dict:
        """Saved, versioned generation recipes (name, latest version, row counts)."""
        recipes = call(lambda: client().recipes.list())
        return {"recipes": [{"id": r["id"], "name": r["name"], "version": r["version"],
                             "rows": r["config"]["rows"], "seed": r["config"]["seed"]} for r in recipes]}

    return server


def main() -> None:
    """Entry point for ``synthetic mcp`` (stdio transport)."""
    build_server().run("stdio")


if __name__ == "__main__":
    main()
