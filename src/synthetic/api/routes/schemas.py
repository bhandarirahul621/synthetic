"""``/v1/schemas``: create, read and edit schemas (FR1, FR2, F2)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request

from synthetic.api.auth import Principal, require
from synthetic.api.deps import ctx, load, parse_schema
from synthetic.api.errors import APIError
from synthetic.api.ids import new_id
from synthetic.api.idempotency import run_idempotent
from synthetic.api.models import SchemaCreate, SchemaPatch
from synthetic.api.planner import MAX_TABLES
from synthetic.api.serializers import schema_out
from synthetic.ddl import parse_ddl, parse_dbt_yaml
from synthetic.engine.fit import infer_table, read_sample
from synthetic.schema import Schema

router = APIRouter(tags=["schemas"])

_SOURCES = ("ddl", "dbt_yaml", "schema_", "yaml", "prompt", "upload_id")


def _schema_from_body(request: Request, body: SchemaCreate, principal: Principal) -> tuple[Schema, str]:
    given = [s for s in _SOURCES if getattr(body, s) is not None]
    if len(given) != 1:
        raise APIError(400, "one_source_required",
                       "Provide exactly one of: ddl, dbt_yaml, schema, yaml, prompt, upload_id.")
    source = given[0]
    name = body.name or "schema"
    if source == "ddl":
        return parse_ddl(body.ddl or "", dialect=body.dialect, name=name), f"ddl:{body.dialect}"
    if source == "dbt_yaml":
        return parse_dbt_yaml(body.dbt_yaml or "", name=name), "dbt"
    if source == "schema_":
        data = dict(body.schema_ or {})
        data.setdefault("name", name)
        return parse_schema(data), "json"
    if source == "yaml":
        try:
            schema = Schema.from_yaml(body.yaml or "")
        except ValueError as exc:
            from pydantic import ValidationError

            from synthetic.api.deps import validation_messages
            detail = validation_messages(exc) if isinstance(exc, ValidationError) else "not a valid YAML mapping"
            raise APIError(422, "invalid_schema", f"The YAML schema is invalid: {detail}.", param="yaml",
                           type="schema_error") from None
        return schema, "yaml"
    if source == "prompt":
        planner = ctx(request).settings.extra.get("planner")
        if planner is None:
            raise APIError(
                501, "planner_not_configured",
                "Natural-language schema creation needs a schema planner (an LLM), and none is configured "
                "on this server. It is planned for the next milestone. For now, send 'ddl', 'schema' or "
                "'yaml' instead.", param="prompt")
        schema = planner.plan(body.prompt or "", max_tables=MAX_TABLES)
        if len(schema.tables) > MAX_TABLES:
            raise APIError(422, "too_many_tables", f"The planner returned more than {MAX_TABLES} tables.",
                           param="prompt")
        return schema, f"prompt:{planner.name}"
    upload = load(request, "upload", body.upload_id or "", principal, param="upload_id")
    if upload.get("status") == "deleted":
        raise APIError(422, "upload_deleted", "That upload was deleted under the retention policy. "
                       "Upload the sample again.", param="upload_id")
    df = read_sample(ctx(request).blobs.local_path(upload["blob_key"]), filename=upload["filename"])
    table_name = body.table_name or Path(upload["filename"]).stem.replace("-", "_").replace(" ", "_")
    return Schema(name=name, tables=[infer_table(df, table_name)]), "upload"


@router.post("/schemas", status_code=201, summary="Create a schema")
def create_schema(body: SchemaCreate, request: Request,
                  principal: Principal = Depends(require("datasets:write"))):
    """Create a schema from SQL DDL, dbt YAML, JSON/YAML, a sample upload, or a prompt (FR1, FR2)."""

    def handler() -> tuple[int, dict[str, Any]]:
        schema, source = _schema_from_body(request, body, principal)
        doc = {"id": new_id("sch"), "workspace_id": principal.workspace_id, "version": 1, "source": source,
               "schema": schema.to_dict()}
        ctx(request).store.put("schema", doc)
        return 201, schema_out(doc)

    return run_idempotent(request, principal, "POST /v1/schemas", body.model_dump(by_alias=True), handler)


@router.get("/schemas", summary="List schemas")
def list_schemas(request: Request, limit: int = 50, principal: Principal = Depends(require("datasets:read"))):
    docs = ctx(request).store.list("schema", principal.workspace_id, limit=min(max(limit, 1), 200))
    return {"object": "list", "data": [schema_out(d) for d in docs]}


@router.get("/schemas/{schema_id}", summary="Get a schema")
def get_schema(schema_id: str, request: Request, principal: Principal = Depends(require("datasets:read"))):
    return schema_out(load(request, "schema", schema_id, principal))


@router.patch("/schemas/{schema_id}", summary="Edit a schema")
def patch_schema(schema_id: str, body: SchemaPatch, request: Request,
                 principal: Principal = Depends(require("datasets:write"))):
    """Edit tables, columns, relationships, constraints and PII flags. Each edit bumps ``version``."""
    doc = load(request, "schema", schema_id, principal)
    data = dict(body.schema_) if body.schema_ is not None else dict(doc["schema"])
    if body.name is not None:
        data["name"] = body.name
    for ref, changes in (body.columns or {}).items():
        table_name, _, col_name = ref.partition(".")
        table = next((t for t in data["tables"] if t["name"] == table_name), None)
        column = next((c for c in (table or {}).get("columns", []) if c["name"] == col_name), None)
        if column is None:
            raise APIError(404, "column_not_found", f"Column '{ref}' is not in the schema.", param="columns")
        column.update(changes)
    schema = parse_schema(data)
    doc["schema"] = schema.to_dict()
    doc["version"] = int(doc["version"]) + 1
    ctx(request).store.put("schema", doc)
    return schema_out(doc)
