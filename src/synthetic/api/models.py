"""Request bodies for the ``/v1`` endpoints (Pydantic models → OpenAPI, FR12)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from synthetic.engine.scenarios import Scenario

Format = Literal["csv", "parquet", "json", "sql"]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SchemaCreate(_Body):
    """Provide exactly one source: ``ddl``, ``dbt_yaml``, ``schema``, ``yaml``, ``prompt`` or ``upload_id``."""

    name: str | None = Field(default=None, max_length=200)
    ddl: str | None = Field(default=None, description="SQL DDL (CREATE TABLE statements).")
    dialect: Literal["postgres", "mysql"] = "postgres"
    dbt_yaml: str | None = Field(default=None, description="A dbt schema.yml with models and tests.")
    schema_: dict[str, Any] | None = Field(default=None, alias="schema",
                                           description="A schema in Synthetic's JSON format.")
    yaml: str | None = Field(default=None, description="A schema in Synthetic's YAML format.")
    prompt: str | None = Field(default=None, max_length=4000,
                               description="Natural-language description (FR1). Needs a configured planner.")
    upload_id: str | None = Field(default=None, description="Infer the schema from an uploaded sample.")
    table_name: str | None = Field(default=None, description="Table name when inferring from an upload.")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SchemaPatch(_Body):
    """Edit a schema. ``schema`` replaces it entirely; ``columns`` edits individual columns."""

    name: str | None = None
    schema_: dict[str, Any] | None = Field(default=None, alias="schema")
    columns: dict[str, dict[str, Any]] | None = Field(
        default=None, description="Map of 'table.column' to fields to change, e.g. {'customers.email': {'pii': true}}.")
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class PreviewCreate(_Body):
    """A synchronous preview (FR5). At most 100 rows per table."""

    schema_id: str | None = None
    schema_: dict[str, Any] | None = Field(default=None, alias="schema", description="Inline schema.")
    recipe_id: str | None = None
    upload_id: str | None = None
    sample_table: str | None = None
    rows: dict[str, int] = Field(default_factory=dict, description="Rows per table (max 100 each).")
    seed: int = Field(default=0, ge=0, le=2**63 - 1)
    scenarios: list[Scenario] = Field(default_factory=list)
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class DatasetCreate(_Body):
    """Start a generation job (PRD §9.1.4)."""

    schema_id: str | None = None
    recipe_id: str | None = None
    recipe_version: int | None = Field(default=None, ge=1)
    upload_id: str | None = Field(default=None, description="Learn from this sample (FR3).")
    sample_table: str | None = Field(default=None, description="Which table the sample is.")
    pii_columns: list[str] = Field(default_factory=list, description="Extra sample columns to treat as PII.")
    rows: dict[str, int] | None = None
    scenarios: list[Scenario] | None = None
    seed: int | None = Field(default=None, ge=0, le=2**63 - 1,
                             description="Omit for a random seed; the chosen seed is returned (FR10).")
    formats: list[Format] | None = None
    name: str | None = Field(default=None, max_length=200)


class DeliveryCreate(_Body):
    """Push a dataset into a database (Postgres in this milestone)."""

    type: Literal["postgres"] = "postgres"
    dsn: str = Field(description="postgresql://user:password@host:5432/db. Used once, never stored or logged.")
    target_schema: str = Field(default="public", pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    if_exists: Literal["fail", "replace", "append"] = "fail"


class RecipeCreate(_Body):
    """Save a generation config. Saving the same ``name`` again creates a new version (U8)."""

    name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    description: str | None = Field(default=None, max_length=1000)
    schema_id: str
    upload_id: str | None = None
    sample_table: str | None = None
    rows: dict[str, int] = Field(default_factory=dict)
    scenarios: list[Scenario] = Field(default_factory=list)
    seed: int = Field(default=0, ge=0, le=2**63 - 1)
    formats: list[Format] = Field(default_factory=lambda: ["csv"])


class WebhookCreate(_Body):
    url: HttpUrl
    events: list[Literal["dataset.succeeded", "dataset.failed", "report.ready"]] = Field(
        default_factory=lambda: ["dataset.succeeded", "dataset.failed", "report.ready"], min_length=1)
    description: str | None = Field(default=None, max_length=200)


class KeyCreate(_Body):
    name: str | None = Field(default=None, max_length=100)
    scopes: list[str] = Field(min_length=1)
    mode: Literal["test", "live"] = "test"
