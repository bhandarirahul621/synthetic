"""``/v1/recipes``: saved, versioned generation configs (U8).

A recipe is a saved order: "this schema, these row counts, this seed".
Saving the same name again adds a new *version*; old versions stay
available, so CI can pin ``recipe_version=3`` and get byte-identical output
forever (FR10). Each version stores a snapshot of the schema it used.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from synthetic.api.auth import Principal, require
from synthetic.api.deps import ctx, load
from synthetic.api.idempotency import run_idempotent
from synthetic.api.ids import new_id, now
from synthetic.api.models import RecipeCreate
from synthetic.api.serializers import recipe_out
from synthetic.engine.scenarios import validate_scenarios
from synthetic.schema import Schema

router = APIRouter(tags=["recipes"])


@router.post("/recipes", status_code=201, summary="Save a recipe (new name or new version)")
def create_recipe(body: RecipeCreate, request: Request,
                  principal: Principal = Depends(require("recipes:write"))):
    c = ctx(request)

    def handler() -> tuple[int, dict[str, Any]]:
        schema_doc = load(request, "schema", body.schema_id, principal, param="schema_id")
        schema = Schema.from_dict(schema_doc["schema"])
        if body.upload_id is None:
            validate_scenarios(schema, body.scenarios)
        else:
            load(request, "upload", body.upload_id, principal, param="upload_id")
        config = {"schema_id": schema_doc["id"], "schema_version": schema_doc["version"],
                  "schema_snapshot": schema_doc["schema"], "rows": body.rows,
                  "scenarios": [s.model_dump() for s in body.scenarios], "seed": body.seed,
                  "formats": body.formats, "upload_id": body.upload_id, "sample_table": body.sample_table}
        existing = next((r for r in c.store.list("recipe", principal.workspace_id, limit=10_000)
                         if r["name"] == body.name), None)
        doc = existing or {"id": new_id("rcp"), "workspace_id": principal.workspace_id, "name": body.name,
                           "versions": []}
        doc["versions"].append({"version": len(doc["versions"]) + 1, "created_at": now(),
                                "description": body.description, "config": config})
        c.store.put("recipe", doc)
        return 201, recipe_out(doc)

    return run_idempotent(request, principal, "POST /v1/recipes", body.model_dump(mode="json"), handler)


@router.get("/recipes", summary="List recipes (latest versions)")
def list_recipes(request: Request, principal: Principal = Depends(require("recipes:read"))):
    docs = ctx(request).store.list("recipe", principal.workspace_id, limit=500)
    return {"object": "list", "data": [recipe_out(d) for d in docs]}


@router.get("/recipes/{recipe_id}", summary="Get a recipe")
def get_recipe(recipe_id: str, request: Request, principal: Principal = Depends(require("recipes:read"))):
    return recipe_out(load(request, "recipe", recipe_id, principal))


@router.get("/recipes/{recipe_id}/versions", summary="List a recipe's versions")
def list_versions(recipe_id: str, request: Request, principal: Principal = Depends(require("recipes:read"))):
    doc = load(request, "recipe", recipe_id, principal)
    return {"object": "list", "data": [recipe_out(doc, v) for v in reversed(doc["versions"])]}
