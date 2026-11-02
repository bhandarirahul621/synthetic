"""The schema model: what a dataset should look like.

Think of a schema as the blueprint of a house: it lists the rooms (tables),
what goes in each room (columns), and how rooms connect (foreign keys). The
engine reads the blueprint and builds the data; the report checks the result
against the blueprint.

Everything here is a Pydantic model, so it validates itself and converts to and
from JSON or YAML with one call.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ColumnType = Literal[
    "int",
    "float",
    "bool",
    "string",
    "category",
    "date",
    "datetime",
    "uuid",
    "email",
    "name",
    "phone",
    "address",
    "text",
]

#: Column types whose values are numbers or points in time (ordered values).
NUMERIC_TYPES = frozenset({"int", "float"})
TEMPORAL_TYPES = frozenset({"date", "datetime"})
ORDERED_TYPES = NUMERIC_TYPES | TEMPORAL_TYPES
#: Types that describe people and are personal data by default.
PERSONAL_TYPES = frozenset({"email", "name", "phone", "address"})

CheckOp = Literal[">", ">=", "<", "<=", "=", "!="]
Scalar = int | float | str | bool

_CHECK_PATTERN = re.compile(r"^\s*([A-Za-z_]\w*)\s*(>=|<=|!=|<>|>|<|==|=)\s*(.+?)\s*$")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChildCount(_Model):
    """How many child rows each parent row gets (a one-to-many relationship).

    Real data is skewed: most customers place a few orders and a few place many.
    ``negative_binomial`` (the default) captures that skew; ``poisson`` is more
    even; ``uniform`` picks any count between ``min`` and ``max``; ``fixed``
    gives every parent exactly ``mean`` children.

    When the caller also fixes the child table's total row count, the engine
    keeps the total exact and uses this distribution only for the shape.
    """

    distribution: Literal["negative_binomial", "poisson", "uniform", "fixed"] = (
        "negative_binomial"
    )
    mean: float | None = Field(default=None, gt=0)
    min: int = Field(default=0, ge=0)
    max: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _check_bounds(self) -> ChildCount:
        if self.max is not None and self.max < self.min:
            raise ValueError("child count max must be >= min")
        return self


class ForeignKey(_Model):
    """A link from this column to a key column in a parent table."""

    table: str
    column: str
    children: ChildCount | None = None


class CheckConstraint(_Model):
    """A simple row-level rule such as ``end_date > start_date`` or ``amount > 0``.

    The left side is always a column. The right side is either another column
    (``right_column``) or a literal ``value``. You can also write the rule as a
    string: ``CheckConstraint.parse("end_date > start_date")``.

    Like SQL ``CHECK``, a row where either side is NULL counts as satisfying it.
    """

    left: str
    op: CheckOp
    right_column: str | None = None
    value: Scalar | None = None
    sql: str | None = Field(default=None, description="Original SQL text, if imported.")

    @model_validator(mode="after")
    def _one_right_side(self) -> CheckConstraint:
        if (self.right_column is None) == (self.value is None):
            raise ValueError("a check needs exactly one of right_column or value")
        return self

    @classmethod
    def parse(cls, text: str) -> CheckConstraint:
        """Parse ``"<column> <op> <column or literal>"`` into a constraint."""
        match = _CHECK_PATTERN.match(text)
        if not match:
            raise ValueError(f"cannot parse check {text!r}; expected e.g. 'end_date > start_date'")
        left, op, right = match.groups()
        op = {"==": "=", "<>": "!="}.get(op, op)
        if re.fullmatch(r"[A-Za-z_]\w*", right) and right.lower() not in ("true", "false"):
            return cls(left=left, op=op, right_column=right, sql=text)
        return cls(left=left, op=op, value=_parse_literal(right), sql=text)

    def describe(self) -> str:
        """Human-readable form, e.g. ``end_date > start_date``."""
        right = self.right_column if self.right_column is not None else repr(self.value)
        return f"{self.left} {self.op} {right}"


def _parse_literal(text: str) -> Scalar:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return text[1:-1]
    if text.lower() in ("true", "false"):
        return text.lower() == "true"
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


class Column(_Model):
    """One column and the rules its values must follow."""

    name: str
    type: ColumnType = "string"
    subtype: str | None = Field(
        default=None,
        description=(
            "Optional semantic hint, e.g. 'first'/'last'/'full' for names, "
            "'city'/'state'/'zip'/'country'/'street' for addresses, 'ssn', 'ipv4', 'url'."
        ),
    )
    description: str | None = None

    # Keys and nullability
    primary_key: bool = False
    unique: bool = False
    nullable: bool = True
    null_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    foreign_key: ForeignKey | None = None

    # Value ranges (numbers, or ISO dates/datetimes as strings)
    min: Scalar | None = None
    max: Scalar | None = None
    decimals: int | None = Field(default=None, ge=0, le=10)
    max_length: int | None = Field(default=None, ge=1)
    distribution: Literal["uniform", "normal", "lognormal", "exponential"] | None = None
    mean: float | None = None
    std: float | None = Field(default=None, gt=0)

    # Categories and booleans
    allowed_values: list[Scalar] | None = None
    weights: list[float] | None = None
    p_true: float | None = Field(default=None, ge=0.0, le=1.0)

    # Privacy: PII columns are always generated fresh, never learned or copied.
    pii: bool = False

    @model_validator(mode="after")
    def _normalise(self) -> Column:
        if self.primary_key:
            self.nullable = False
        if not self.nullable:
            self.null_rate = 0.0
        if self.weights is not None:
            if not self.allowed_values or len(self.weights) != len(self.allowed_values):
                raise ValueError(f"column {self.name!r}: weights must match allowed_values")
            if any(w < 0 for w in self.weights) or sum(self.weights) <= 0:
                raise ValueError(f"column {self.name!r}: weights must be non-negative")
        if self.allowed_values is not None and len(self.allowed_values) == 0:
            raise ValueError(f"column {self.name!r}: allowed_values cannot be empty")
        return self


class Table(_Model):
    """A table: its columns, keys and row-level checks."""

    name: str
    description: str | None = None
    columns: list[Column]
    primary_key: list[str] = Field(default_factory=list)
    unique_together: list[list[str]] = Field(default_factory=list)
    checks: list[CheckConstraint] = Field(default_factory=list)
    rows: int | None = Field(default=None, ge=0, description="Default row count.")

    @field_validator("checks", mode="before")
    @classmethod
    def _parse_check_strings(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [CheckConstraint.parse(v) if isinstance(v, str) else v for v in value]
        return value

    @model_validator(mode="after")
    def _normalise_keys(self) -> Table:
        names = [c.name for c in self.columns]
        if len(set(names)) != len(names):
            raise ValueError(f"table {self.name!r} has duplicate column names")
        flagged = [c.name for c in self.columns if c.primary_key]
        if flagged and not self.primary_key:
            self.primary_key = flagged
        for key in self.primary_key:
            if key not in names:
                raise ValueError(f"table {self.name!r}: primary key column {key!r} not found")
        for col in self.columns:
            if col.name in self.primary_key:
                col.primary_key = True
                col.nullable = False
                col.null_rate = 0.0
                if len(self.primary_key) == 1:
                    col.unique = True
        for group in self.unique_together:
            for key in group:
                if key not in names:
                    raise ValueError(f"table {self.name!r}: unique column {key!r} not found")
        for check in self.checks:
            for ref in (check.left, check.right_column):
                if ref is not None and ref not in names:
                    raise ValueError(
                        f"table {self.name!r}: check '{check.describe()}' uses unknown column {ref!r}"
                    )
        return self

    def column(self, name: str) -> Column:
        """Return the column called ``name`` (raises ``KeyError`` if missing)."""
        for col in self.columns:
            if col.name == name:
                return col
        raise KeyError(f"{self.name}.{name}")

    @property
    def foreign_keys(self) -> list[Column]:
        """Columns of this table that reference another table."""
        return [c for c in self.columns if c.foreign_key is not None]


class Relationship(_Model):
    """A read-only view of one foreign key, from the parent's point of view."""

    parent_table: str
    parent_column: str
    child_table: str
    child_column: str
    children: ChildCount | None = None


class Schema(_Model):
    """A whole dataset blueprint: several tables and their relationships."""

    name: str = "schema"
    version: int = Field(default=1, ge=1)
    tables: list[Table]
    warnings: list[str] = Field(
        default_factory=list,
        description="Notes from import, e.g. CHECK constraints we could not interpret.",
    )

    @model_validator(mode="after")
    def _check_references(self) -> Schema:
        by_name = {t.name: t for t in self.tables}
        if len(by_name) != len(self.tables):
            raise ValueError("schema has duplicate table names")
        for table in self.tables:
            for col in table.foreign_keys:
                fk = col.foreign_key
                assert fk is not None
                parent = by_name.get(fk.table)
                if parent is None:
                    raise ValueError(
                        f"{table.name}.{col.name} references {fk.table}.{fk.column}, "
                        f"but table '{fk.table}' is not in the schema."
                    )
                try:
                    target = parent.column(fk.column)
                except KeyError:
                    raise ValueError(
                        f"{table.name}.{col.name} references {fk.table}.{fk.column}, "
                        f"but column '{fk.column}' does not exist."
                    ) from None
                if not (target.unique or target.primary_key):
                    raise ValueError(
                        f"{table.name}.{col.name} references {fk.table}.{fk.column}, "
                        "which is neither a primary key nor unique."
                    )
        return self

    # ----- lookup helpers -------------------------------------------------
    def table(self, name: str) -> Table:
        """Return the table called ``name`` (raises ``KeyError`` if missing)."""
        for table in self.tables:
            if table.name == name:
                return table
        raise KeyError(name)

    @property
    def table_names(self) -> list[str]:
        return [t.name for t in self.tables]

    def relationships(self) -> list[Relationship]:
        """All foreign keys as parent → child relationships."""
        out = []
        for table in self.tables:
            for col in table.foreign_keys:
                fk = col.foreign_key
                assert fk is not None
                out.append(
                    Relationship(
                        parent_table=fk.table,
                        parent_column=fk.column,
                        child_table=table.name,
                        child_column=col.name,
                        children=fk.children,
                    )
                )
        return out

    # ----- serialization --------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """Plain dict, without unset optional fields (keeps files short)."""
        return self.model_dump(mode="json", exclude_none=True, exclude_defaults=False)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), sort_keys=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Schema:
        return cls.model_validate(data)

    @classmethod
    def from_json(cls, text: str) -> Schema:
        return cls.model_validate_json(text)

    @classmethod
    def from_yaml(cls, text: str) -> Schema:
        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            raise ValueError("YAML schema must be a mapping with a 'tables' key")
        return cls.model_validate(data)


def load_schema(path: str | Path, dialect: str = "postgres") -> Schema:
    """Load a schema file by extension: ``.sql`` (DDL), ``.json``, ``.yaml``/``.yml``."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix == ".sql":
        from synthetic.ddl import parse_ddl

        return parse_ddl(text, dialect=dialect, name=path.stem)
    if suffix == ".json":
        return Schema.from_json(text)
    if suffix in (".yaml", ".yml"):
        return Schema.from_yaml(text)
    raise ValueError(f"unsupported schema file type {suffix!r}; use .sql, .json or .yaml")
