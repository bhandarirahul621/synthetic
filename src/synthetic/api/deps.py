"""Small helpers shared by the route modules."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from pydantic import ValidationError

from synthetic.api.auth import Principal
from synthetic.api.errors import APIError
from synthetic.api.jobs import AppContext
from synthetic.schema import Schema


def ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def load(request: Request, kind: str, doc_id: str, principal: Principal, param: str | None = None) -> dict:
    """Fetch a document of ``kind`` in the caller's workspace, or raise 404."""
    doc = ctx(request).store.get(kind, doc_id, principal.workspace_id)
    if doc is None:
        raise APIError(404, f"{kind}_not_found", f"No {kind} with id '{doc_id}' exists in this workspace.",
                       param=param or f"{kind}_id")
    return doc


def validation_messages(exc: ValidationError) -> str:
    """Pydantic errors as text: field paths and our messages, never the input values."""
    parts = []
    for err in exc.errors()[:5]:
        loc = ".".join(str(p) for p in err.get("loc", ()))
        msg = str(err.get("msg", "invalid")).removeprefix("Value error, ")
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts)


def parse_schema(data: dict[str, Any], param: str = "schema") -> Schema:
    """Validate a schema dict, turning problems into a 422 with a readable message."""
    try:
        return Schema.model_validate(data)
    except ValidationError as exc:
        raise APIError(422, "invalid_schema", f"The schema is invalid: {validation_messages(exc)}.",
                       param=param, type="schema_error") from None
