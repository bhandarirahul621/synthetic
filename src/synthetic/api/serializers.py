"""Turn stored documents into public API responses (hide internal fields)."""

from __future__ import annotations

from typing import Any

from synthetic.api.ids import iso


def schema_out(doc: dict[str, Any]) -> dict[str, Any]:
    schema = doc["schema"]
    return {
        "id": doc["id"], "object": "schema", "name": schema.get("name"), "version": doc["version"],
        "source": doc.get("source"), "warnings": schema.get("warnings", []),
        "tables": [{"name": t["name"], "columns": len(t["columns"]),
                    "primary_key": t.get("primary_key", []),
                    "foreign_keys": [f"{c['name']} -> {c['foreign_key']['table']}.{c['foreign_key']['column']}"
                                     for c in t["columns"] if c.get("foreign_key")]}
                   for t in schema["tables"]],
        "schema": schema,
        "created_at": iso(doc["created_at"]), "updated_at": iso(doc.get("updated_at")),
        "links": {"self": f"/v1/schemas/{doc['id']}"},
    }


def upload_out(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": doc["id"], "object": "upload", "status": doc.get("status", "ready"),
        "filename": doc["filename"], "bytes": doc["bytes"], "rows": doc.get("rows"),
        "columns": doc.get("columns", []), "retention_hours": doc.get("retention_hours"),
        "created_at": iso(doc["created_at"]), "deleted_at": iso(doc.get("deleted_at")),
    }


def dataset_out(doc: dict[str, Any]) -> dict[str, Any]:
    ds_id = doc["id"]
    out = {
        "id": ds_id, "object": "dataset", "name": doc.get("name"), "status": doc["status"],
        "progress": doc.get("progress", 0), "engine_version": doc["engine_version"], "seed": doc["seed"],
        "schema_id": doc.get("schema_id"), "schema_version": doc.get("schema_version"),
        "recipe_id": doc.get("recipe_id"), "recipe_version": doc.get("recipe_version"),
        "upload_id": doc.get("upload_id"), "rows": doc.get("rows"), "row_counts": doc.get("row_counts"),
        "scenarios": doc.get("scenarios", []), "formats": doc.get("formats", []),
        "error": doc.get("error"), "report": doc.get("report_summary"),
        "deliveries": [{k: v for k, v in d.items()} for d in doc.get("deliveries", [])],
        "created_at": iso(doc["created_at"]), "started_at": iso(doc.get("started_at")),
        "completed_at": iso(doc.get("completed_at")),
        "links": {"self": f"/v1/datasets/{ds_id}", "files": f"/v1/datasets/{ds_id}/files",
                  "report": f"/v1/datasets/{ds_id}/report"},
    }
    return out


def recipe_out(doc: dict[str, Any], version: dict[str, Any] | None = None) -> dict[str, Any]:
    version = version or doc["versions"][-1]
    return {
        "id": doc["id"], "object": "recipe", "name": doc["name"], "version": version["version"],
        "versions": len(doc["versions"]), "description": version.get("description"),
        "config": version["config"], "created_at": iso(doc["created_at"]),
        "updated_at": iso(version["created_at"]),
        "links": {"self": f"/v1/recipes/{doc['id']}", "versions": f"/v1/recipes/{doc['id']}/versions"},
    }


def webhook_out(doc: dict[str, Any], include_secret: bool = False) -> dict[str, Any]:
    out = {"id": doc["id"], "object": "webhook", "url": doc["url"], "events": doc["events"],
           "description": doc.get("description"), "created_at": iso(doc["created_at"])}
    if include_secret:
        out["secret"] = doc["secret"]
    return out
