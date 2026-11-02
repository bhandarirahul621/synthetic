"""``/v1/previews``: up to 100 rows per table, synchronously (FR5).

Previews have no side effects, so an ``Idempotency-Key`` header is accepted
but not needed: repeating the call returns the same rows for the same seed.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from synthetic.api.auth import Principal, require
from synthetic.api.deps import ctx, load, parse_schema
from synthetic.api.errors import APIError
from synthetic.api.models import PreviewCreate
from synthetic.engine.fit import read_sample
from synthetic.engine.ordering import topological_order
from synthetic.engine.version import ENGINE_VERSION
from synthetic.export import frame_records
from synthetic.pipeline import run as run_pipeline
from synthetic.schema import Schema

router = APIRouter(tags=["previews"])

DEFAULT_PREVIEW_ROWS = 10


def trim_preview(schema: Schema, tables: dict, limit: int) -> dict:
    """Keep at most ``limit`` rows per table while every foreign key still resolves."""
    kept: dict = {}
    for name in topological_order(schema):
        df = tables[name]
        table = schema.table(name)
        for col in table.foreign_keys:
            fk = col.foreign_key
            if fk is None or fk.table == name or fk.table not in kept:
                continue
            parents = set(kept[fk.table][fk.column].dropna().tolist())
            df = df[df[col.name].isna() | df[col.name].isin(parents)]
        kept[name] = df.head(limit).reset_index(drop=True)
    return {name: kept[name] for name in tables}


@router.post("/previews", summary="Preview rows (max 100 per table)")
def create_preview(body: PreviewCreate, request: Request,
                   principal: Principal = Depends(require("datasets:write"))):
    """Generate a small preview for a schema, recipe or sample without starting a job."""
    c = ctx(request)
    limit = c.settings.preview_max_rows
    too_big = [t for t, n in body.rows.items() if n > limit or n < 0]
    if too_big:
        raise APIError(400, "preview_limit_exceeded",
                       f"Previews return at most {limit} rows per table (asked too many for: "
                       f"{', '.join(too_big)}). Start a dataset job for more.", param="rows")
    schema = None
    upload_id, sample_table, seed, scenarios = body.upload_id, body.sample_table, body.seed, body.scenarios
    if body.recipe_id:
        recipe = load(request, "recipe", body.recipe_id, principal, param="recipe_id")
        config = recipe["versions"][-1]["config"]
        schema = Schema.from_dict(config["schema_snapshot"])
        upload_id = upload_id or config.get("upload_id")
        sample_table = sample_table or config.get("sample_table")
    elif body.schema_id:
        schema = Schema.from_dict(load(request, "schema", body.schema_id, principal)["schema"])
    elif body.schema_ is not None:
        schema = parse_schema(body.schema_)
    sample = None
    if upload_id:
        upload = load(request, "upload", upload_id, principal, param="upload_id")
        if upload.get("status") == "deleted":
            raise APIError(422, "upload_deleted", "That upload was deleted; upload the sample again.",
                           param="upload_id")
        sample = read_sample(c.blobs.local_path(upload["blob_key"]), filename=upload["filename"])
        sample_table = sample_table or upload.get("table_name")
    if schema is None and sample is None:
        raise APIError(400, "schema_required", "Provide schema_id, schema, recipe_id or upload_id.")

    rows = dict(body.rows)
    if schema is not None:
        for table in schema.tables:
            if not table.foreign_keys and table.name not in rows:
                rows[table.name] = min(DEFAULT_PREVIEW_ROWS, limit)
    if sample is not None and sample_table and sample_table not in rows:
        rows[sample_table] = min(DEFAULT_PREVIEW_ROWS, limit)
    result = run_pipeline(schema, rows=rows, seed=seed, scenarios=scenarios, sample=sample,
                          sample_table=sample_table, with_report=False)
    tables = trim_preview(result.schema, result.tables, limit)
    return {
        "object": "preview", "engine_version": ENGINE_VERSION, "seed": seed,
        "row_counts": {k: len(v) for k, v in tables.items()},
        "tables": {name: {"columns": list(df.columns),
                          "rows": frame_records(df, result.schema.table(name))}
                   for name, df in tables.items()},
    }
