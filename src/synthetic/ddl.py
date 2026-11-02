"""Import a schema from SQL DDL (Postgres, MySQL) or a dbt ``schema.yml`` (FR2).

We use sqlglot (MIT licensed) to turn SQL text into a syntax tree, then walk
the tree to find tables, columns, keys and CHECK constraints. Anything we
cannot interpret is kept as a *warning* on the schema instead of silently
disappearing, so the user can see what will not be enforced.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import sqlglot
import yaml
from sqlglot import exp
from sqlglot.errors import ParseError

from synthetic.errors import DDLParseError
from synthetic.schema import CheckConstraint, Column, ForeignKey, Schema, Table
from synthetic.semantics import infer_semantic

log = logging.getLogger(__name__)

SUPPORTED_DIALECTS = ("postgres", "mysql")

_INT = {
    "TINYINT", "SMALLINT", "MEDIUMINT", "INT", "BIGINT", "SERIAL", "SMALLSERIAL", "BIGSERIAL",
    "UTINYINT", "USMALLINT", "UMEDIUMINT", "UINT", "UBIGINT", "INT128", "INT256", "YEAR",
}
_UNSIGNED = {"UTINYINT", "USMALLINT", "UMEDIUMINT", "UINT", "UBIGINT", "UDECIMAL", "UDOUBLE"}
_FLOAT = {"FLOAT", "DOUBLE", "UDOUBLE", "DECIMAL", "UDECIMAL", "MONEY", "SMALLMONEY",
          "BIGDECIMAL", "DECIMAL32", "DECIMAL64", "DECIMAL128", "DECIMAL256"}
_BOOL = {"BOOLEAN", "BIT"}
_STRING = {"VARCHAR", "CHAR", "NVARCHAR", "NCHAR", "TEXT", "MEDIUMTEXT", "LONGTEXT", "TINYTEXT",
           "NAME", "CITEXT", "BPCHAR", "STRING"}
_DATE = {"DATE", "DATE32"}
_DATETIME = {"DATETIME", "DATETIME2", "DATETIME64", "TIMESTAMP", "TIMESTAMPTZ", "TIMESTAMPLTZ",
             "TIMESTAMPNTZ", "TIMESTAMP_S", "TIMESTAMP_MS", "TIMESTAMP_NS", "SMALLDATETIME"}
_UUID = {"UUID", "UNIQUEIDENTIFIER"}
_ENUM = {"ENUM", "ENUM8", "ENUM16"}


class _TableDraft:
    """Mutable scratch space while we walk one CREATE TABLE statement."""

    def __init__(self, name: str):
        self.name = name
        self.columns: dict[str, dict[str, Any]] = {}
        self.primary_key: list[str] = []
        self.unique_together: list[list[str]] = []
        self.checks: list[CheckConstraint] = []
        # (child column, parent table, parent column or None)
        self.references: list[tuple[str, str, str | None]] = []


def parse_ddl(sql: str, dialect: str = "postgres", name: str = "schema") -> Schema:
    """Parse ``CREATE TABLE`` statements into a :class:`Schema`.

    Supports column and table level PRIMARY KEY, FOREIGN KEY / REFERENCES,
    NOT NULL, UNIQUE, simple CHECK constraints (comparisons, IN, BETWEEN, AND),
    MySQL ``ENUM`` and Postgres ``CREATE TYPE ... AS ENUM``, and
    ``ALTER TABLE ... ADD CONSTRAINT`` (as produced by ``pg_dump``).
    """
    dialect = dialect.lower()
    if dialect in ("postgresql", "pg"):
        dialect = "postgres"
    if dialect not in SUPPORTED_DIALECTS:
        raise DDLParseError(
            "unsupported_dialect",
            f"Dialect '{dialect}' is not supported yet. Use one of: {', '.join(SUPPORTED_DIALECTS)}.",
            param="dialect",
        )
    warnings: list[str] = []
    statements = _parse_statements(sql, dialect, warnings)

    enums: dict[str, list[Any]] = {}
    drafts: dict[str, _TableDraft] = {}
    for stmt in statements:
        if isinstance(stmt, exp.Create) and str(stmt.args.get("kind", "")).upper() == "TYPE":
            dtype = stmt.args.get("expression")
            if isinstance(dtype, exp.DataType) and dtype.this.name in _ENUM:
                enums[stmt.this.name.lower()] = [_literal(e) for e in dtype.expressions]
    for stmt in statements:
        if isinstance(stmt, exp.Create) and str(stmt.args.get("kind", "")).upper() == "TABLE":
            draft = _read_create_table(stmt, enums, warnings)
            if draft is None:
                continue
            if draft.name in drafts:
                warnings.append(f"Table '{draft.name}' is defined twice; keeping the last definition.")
            drafts[draft.name] = draft
    for stmt in statements:
        if isinstance(stmt, exp.Alter):
            _read_alter_table(stmt, drafts, warnings)

    if not drafts:
        raise DDLParseError(
            "no_tables_found",
            "No CREATE TABLE statements were found. Paste the DDL for at least one table.",
            param="ddl",
        )
    tables = [_finish_table(d, drafts, warnings) for d in drafts.values()]
    try:
        return Schema(name=name, tables=tables, warnings=warnings)
    except ValueError as exc:  # pydantic ValidationError is a ValueError
        raise DDLParseError("invalid_schema", _first_error(exc), param="ddl") from None


def _first_error(exc: Exception) -> str:
    errors = getattr(exc, "errors", None)
    if callable(errors):
        msgs = [str(e.get("msg", "")).removeprefix("Value error, ") for e in errors()]
        return "; ".join(m for m in msgs if m) or "The schema is invalid."
    return str(exc)


def _parse_statements(sql: str, dialect: str, warnings: list[str]) -> list[exp.Expression]:
    """Parse the whole script; if that fails, parse statement by statement."""
    try:
        return [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except ParseError:
        pass
    out: list[exp.Expression] = []
    for index, chunk in enumerate(_split_statements(sql), start=1):
        if not chunk.strip():
            continue
        try:
            out.extend(s for s in sqlglot.parse(chunk, read=dialect) if s is not None)
        except ParseError:
            if re.search(r"\bcreate\s+table\b", chunk, re.IGNORECASE):
                warnings.append(f"Statement {index} could not be parsed and was skipped.")
    if not out:
        raise DDLParseError(
            "ddl_parse_failed",
            f"The SQL could not be parsed as {dialect} DDL. Check for typos or unsupported syntax.",
            param="ddl",
        )
    return out


def _split_statements(sql: str) -> list[str]:
    """Split on semicolons that are not inside quotes."""
    parts, buf, quote = [], [], None
    for ch in sql:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in "'\"`":
            quote = ch
            buf.append(ch)
        elif ch == ";":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


def _ident(node: exp.Expression) -> str:
    return node.name if hasattr(node, "name") else str(node)


def _literal(node: exp.Expression | None) -> Any:
    """Turn a literal node (``5``, ``-3``, ``'x'``, ``DATE '2020-01-01'``) into Python."""
    if node is None:
        return None
    if isinstance(node, exp.Paren):
        return _literal(node.this)
    if isinstance(node, exp.Neg):
        inner = _literal(node.this)
        return -inner if isinstance(inner, int | float) else None
    if isinstance(node, exp.Cast):
        return _literal(node.this)
    if isinstance(node, exp.Boolean):
        return bool(node.this)
    if isinstance(node, exp.Literal):
        if node.is_string:
            return node.this
        text = node.this
        try:
            return int(text)
        except ValueError:
            return float(text)
    return None


def _is_literal(node: exp.Expression | None) -> bool:
    return node is not None and _literal(node) is not None


def _read_create_table(stmt: exp.Create, enums: dict, warnings: list[str]) -> _TableDraft | None:
    schema_node = stmt.this
    if not isinstance(schema_node, exp.Schema):
        warnings.append("CREATE TABLE ... AS SELECT is not supported and was skipped.")
        return None
    table_name = schema_node.this.name
    draft = _TableDraft(table_name)
    for item in schema_node.expressions:
        if isinstance(item, exp.ColumnDef):
            _read_column(item, draft, enums, warnings)
    for item in schema_node.expressions:
        if not isinstance(item, exp.ColumnDef):
            _read_table_constraint(item, draft, warnings)
    return draft


def _read_column(node: exp.ColumnDef, draft: _TableDraft, enums: dict, warnings: list[str]) -> None:
    name = node.name
    col: dict[str, Any] = {"name": name}
    dtype = node.args.get("kind")
    col.update(_map_type(dtype, enums, f"{draft.name}.{name}", warnings))
    for constraint in node.args.get("constraints") or []:
        kind = constraint.args.get("kind")
        if isinstance(kind, exp.NotNullColumnConstraint):
            if not kind.args.get("allow_null"):
                col["nullable"] = False
        elif isinstance(kind, exp.PrimaryKeyColumnConstraint):
            draft.primary_key = [name]
        elif isinstance(kind, exp.UniqueColumnConstraint):
            col["unique"] = True
        elif isinstance(kind, exp.Reference):
            target = kind.this
            parent = target.this.name if isinstance(target, exp.Schema) else _ident(target)
            cols = [_ident(e) for e in target.expressions] if isinstance(target, exp.Schema) else []
            draft.references.append((name, parent, cols[0] if cols else None))
        elif isinstance(kind, exp.CheckColumnConstraint):
            _read_check(kind.this, draft, col_defs={name: col}, warnings=warnings)
    placeholder = draft.columns.get(name)
    if placeholder and placeholder.get("_placeholder"):
        placeholder.pop("_placeholder")
        col = {**placeholder, **col}
    draft.columns[name] = col


def _map_type(dtype: exp.DataType | None, enums: dict, where: str, warnings: list[str]) -> dict:
    """Map an SQL type to our column type plus any facts it implies (length, scale)."""
    if dtype is None:
        return {"type": "string"}
    tname = dtype.this.name
    params = [_literal(p.this) if isinstance(p, exp.DataTypeParam) else _literal(p)
              for p in dtype.expressions]
    out: dict[str, Any] = {}
    if tname in _INT:
        if tname == "TINYINT" and params[:1] == [1]:
            return {"type": "bool"}
        out["type"] = "int"
        if tname in _UNSIGNED:
            out["min"] = 0
    elif tname in _FLOAT:
        out["type"] = "float"
        if tname in _UNSIGNED:
            out["min"] = 0.0
        if len(params) >= 2 and isinstance(params[1], int):
            out["decimals"] = params[1]
            if isinstance(params[0], int) and params[0] > params[1]:
                out["_precision_max"] = float(10 ** (params[0] - params[1])) - 10 ** -params[1]
        elif tname in ("MONEY", "SMALLMONEY"):
            out["decimals"] = 2
    elif tname in _BOOL:
        out["type"] = "bool"
    elif tname in _STRING:
        out["type"] = "string"
        if params and isinstance(params[0], int):
            out["max_length"] = params[0]
    elif tname in _DATE:
        out["type"] = "date"
    elif tname in _DATETIME:
        out["type"] = "datetime"
    elif tname in _UUID:
        out["type"] = "uuid"
    elif tname in _ENUM:
        out["type"] = "category"
        out["allowed_values"] = [p for p in params if p is not None]
    elif tname == "USERDEFINED":
        kind = dtype.args.get("kind")
        key = _ident(kind).lower() if kind is not None else ""
        if key in enums:
            out["type"] = "category"
            out["allowed_values"] = list(enums[key])
        else:
            warnings.append(f"{where}: unknown type '{key}'; treated as text.")
            out["type"] = "string"
    elif tname in ("JSON", "JSONB"):
        warnings.append(f"{where}: JSON columns are generated as plain strings in this version.")
        out["type"] = "string"
    else:
        warnings.append(f"{where}: type {tname} is not supported yet; treated as text.")
        out["type"] = "string"
    return out


def _read_table_constraint(item: exp.Expression, draft: _TableDraft, warnings: list[str]) -> None:
    if isinstance(item, exp.Constraint):
        for inner in item.expressions:
            _read_table_constraint(inner, draft, warnings)
    elif isinstance(item, exp.PrimaryKey):
        draft.primary_key = [_ident(e) for e in item.expressions]
    elif isinstance(item, exp.ForeignKey):
        _read_foreign_key(item, draft, warnings)
    elif isinstance(item, exp.UniqueColumnConstraint):
        target = item.this
        cols = [_ident(e) for e in target.expressions] if isinstance(target, exp.Schema) else []
        if len(cols) == 1 and cols[0] in draft.columns:
            draft.columns[cols[0]]["unique"] = True
        elif cols:
            draft.unique_together.append(cols)
    elif isinstance(item, exp.CheckColumnConstraint):
        _read_check(item.this, draft, col_defs=draft.columns, warnings=warnings)
    elif isinstance(item, exp.IndexColumnConstraint):
        pass  # plain indexes do not change what valid data looks like
    elif isinstance(item, exp.PrimaryKeyColumnConstraint):
        pass
    else:
        warnings.append(f"Table '{draft.name}': a table constraint was not recognised and was skipped.")


def _read_foreign_key(item: exp.ForeignKey, draft: _TableDraft, warnings: list[str]) -> None:
    child_cols = [_ident(e) for e in item.expressions]
    ref = item.args.get("reference")
    if ref is None:
        return
    target = ref.this
    parent = target.this.name if isinstance(target, exp.Schema) else _ident(target)
    parent_cols = [_ident(e) for e in target.expressions] if isinstance(target, exp.Schema) else []
    if len(child_cols) != 1:
        warnings.append(
            f"Table '{draft.name}': composite foreign key ({', '.join(child_cols)}) is not "
            "supported yet and will not be enforced."
        )
        return
    draft.references.append((child_cols[0], parent, parent_cols[0] if parent_cols else None))


def _read_alter_table(stmt: exp.Alter, drafts: dict[str, _TableDraft], warnings: list[str]) -> None:
    table_name = stmt.this.name
    draft = drafts.get(table_name)
    if draft is None:
        return
    for action in stmt.args.get("actions") or []:
        if isinstance(action, exp.AddConstraint):
            for inner in action.expressions:
                _read_table_constraint(inner, draft, warnings)


_OPS = {exp.GT: ">", exp.GTE: ">=", exp.LT: "<", exp.LTE: "<=", exp.EQ: "=", exp.NEQ: "!="}
_FLIP = {">": "<", ">=": "<=", "<": ">", "<=": ">=", "=": "=", "!=": "!="}


def _read_check(node: exp.Expression, draft: _TableDraft, col_defs: dict, warnings: list[str]) -> None:
    """Interpret one CHECK expression; anything unsupported becomes a warning."""
    if isinstance(node, exp.Paren):
        return _read_check(node.this, draft, col_defs, warnings)
    if isinstance(node, exp.And):
        _read_check(node.this, draft, col_defs, warnings)
        _read_check(node.expression, draft, col_defs, warnings)
        return None
    sql = node.sql()
    if isinstance(node, exp.In) and isinstance(node.this, exp.Column):
        values = [_literal(v) for v in node.expressions]
        if all(v is not None for v in values) and values:
            _column(col_defs, draft, node.this.name)["allowed_values"] = values
            return None
    if isinstance(node, exp.Between) and isinstance(node.this, exp.Column):
        low, high = _literal(node.args.get("low")), _literal(node.args.get("high"))
        if low is not None and high is not None:
            name = node.this.name
            draft.checks.append(CheckConstraint(left=name, op=">=", value=low, sql=sql))
            draft.checks.append(CheckConstraint(left=name, op="<=", value=high, sql=sql))
            _tighten(_column(col_defs, draft, name), ">=", low)
            _tighten(_column(col_defs, draft, name), "<=", high)
            return None
    if isinstance(node, exp.Not) and isinstance(node.this, exp.Is):
        inner = node.this
        if isinstance(inner.this, exp.Column) and isinstance(inner.expression, exp.Null):
            _column(col_defs, draft, inner.this.name)["nullable"] = False
            return None
    op = _OPS.get(type(node))
    if op is not None:
        left, right = node.this, node.expression
        if isinstance(left, exp.Column) and isinstance(right, exp.Column):
            draft.checks.append(
                CheckConstraint(left=left.name, op=op, right_column=right.name, sql=sql)
            )
            return None
        if isinstance(right, exp.Column) and _is_literal(left):
            left, right, op = right, left, _FLIP[op]
        if isinstance(left, exp.Column) and _is_literal(right):
            value = _literal(right)
            if op == "=":
                _column(col_defs, draft, left.name)["allowed_values"] = [value]
            else:
                draft.checks.append(CheckConstraint(left=left.name, op=op, value=value, sql=sql))
                _tighten(_column(col_defs, draft, left.name), op, value)
            return None
    warnings.append(f"Table '{draft.name}': CHECK ({sql}) is too complex to enforce yet; skipped.")
    return None


def _column(col_defs: dict, draft: _TableDraft, name: str) -> dict:
    if name in col_defs:
        return col_defs[name]
    if name in draft.columns:
        return draft.columns[name]
    # The check mentions a column defined later; create a placeholder that the
    # real definition will be merged into.
    return draft.columns.setdefault(name, {"name": name, "_placeholder": True})


def _tighten(col: dict, op: str, value: Any) -> None:
    """Record a literal bound as the column's min or max."""
    if op in (">", ">="):
        current = col.get("min")
        col["min"] = value if current is None or _gt(value, current) else current
    elif op in ("<", "<="):
        current = col.get("max")
        col["max"] = value if current is None or _gt(current, value) else current


def _gt(a: Any, b: Any) -> bool:
    try:
        return a > b
    except TypeError:
        return False


def _finish_table(draft: _TableDraft, drafts: dict[str, _TableDraft], warnings: list[str]) -> Table:
    """Resolve references and apply name-based semantics, then build the Table."""
    for child, parent, parent_col in draft.references:
        if child not in draft.columns:
            warnings.append(f"Table '{draft.name}': foreign key column '{child}' not found; skipped.")
            continue
        if parent_col is None:
            parent_draft = drafts.get(parent)
            if parent_draft is None or len(parent_draft.primary_key) != 1:
                parent_col = "id"
            else:
                parent_col = parent_draft.primary_key[0]
        draft.columns[child]["foreign_key"] = {"table": parent, "column": parent_col}

    columns = []
    for raw in draft.columns.values():
        raw = dict(raw)
        if raw.pop("_placeholder", False) and "type" not in raw:
            warnings.append(f"Table '{draft.name}': CHECK refers to unknown column '{raw['name']}'.")
            continue
        _apply_semantics(raw, draft)
        precision_max = raw.pop("_precision_max", None)
        if precision_max is not None and raw.get("max") is None:
            raw["max"] = precision_max
        columns.append(Column(**raw))
    # Checks must refer to existing columns; drop the ones that do not.
    names = {c.name for c in columns}
    checks = [
        c for c in draft.checks
        if c.left in names and (c.right_column is None or c.right_column in names)
    ]
    return Table(
        name=draft.name,
        columns=columns,
        primary_key=[k for k in draft.primary_key if k in names],
        unique_together=[g for g in draft.unique_together if all(k in names for k in g)],
        checks=checks,
    )


def _apply_semantics(raw: dict, draft: _TableDraft) -> None:
    """Use the column name to pick a more specific type and realistic defaults."""
    is_key = raw["name"] in draft.primary_key or "foreign_key" in raw
    if is_key:
        return
    base = raw.get("type", "string")
    sem = infer_semantic(raw["name"], draft.name, sql_type=base)
    if sem is None:
        return
    if sem.pii:
        raw["pii"] = True
    if base == "string":
        if sem.type == "category" and raw.get("allowed_values") is None:
            raw["type"] = "category"
        elif sem.type != "category":
            raw["type"] = sem.type
            if sem.subtype:
                raw["subtype"] = sem.subtype
        elif raw.get("allowed_values") is not None:
            raw["type"] = "category"
    elif base == sem.type or (base in ("int", "float") and sem.type in ("int", "float")):
        if sem.subtype:
            raw.setdefault("subtype", sem.subtype)
    elif base == "int" and sem.type == "bool":
        raw["type"] = "bool"
        raw.pop("min", None)
    else:
        return
    for key, value in sem.hints.items():
        if key in ("allowed_values", "weights"):
            continue
        if key == "decimals" and raw.get("type") != "float":
            continue
        raw.setdefault(key, value)
    if raw.get("type") == "category" and raw.get("allowed_values") is None:
        if "allowed_values" in sem.hints:
            raw["allowed_values"] = list(sem.hints["allowed_values"])
            if "weights" in sem.hints:
                raw["weights"] = list(sem.hints["weights"])


# ---------------------------------------------------------------------------
# dbt schema.yml
# ---------------------------------------------------------------------------

_DBT_TYPES = {
    "int": "int", "integer": "int", "bigint": "int", "smallint": "int", "number": "float",
    "numeric": "float", "decimal": "float", "float": "float", "double": "float",
    "boolean": "bool", "bool": "bool", "varchar": "string", "text": "string", "string": "string",
    "date": "date", "timestamp": "datetime", "datetime": "datetime", "timestamp_ntz": "datetime",
    "timestamptz": "datetime", "uuid": "uuid",
}


def parse_dbt_yaml(text: str, name: str = "schema") -> Schema:
    """Build a schema from a dbt ``schema.yml`` (models, columns and tests).

    Understands the generic tests ``unique``, ``not_null``, ``accepted_values``
    and ``relationships``, plus ``data_type`` on columns (dbt 1.5+ contracts).
    """
    data = yaml.safe_load(text) or {}
    models = data.get("models") if isinstance(data, dict) else None
    if not models:
        raise DDLParseError("no_models_found", "The dbt YAML has no 'models' list.", param="dbt")
    warnings: list[str] = []
    tables = []
    for model in models:
        tname = model["name"]
        cols = []
        pending_pk = []
        for c in model.get("columns") or []:
            raw: dict[str, Any] = {"name": c["name"]}
            dtype = str(c.get("data_type", "")).lower().split("(")[0].strip()
            raw["type"] = _DBT_TYPES.get(dtype, "string")
            tests = (c.get("data_tests") or c.get("tests") or []) + (c.get("constraints") or [])
            for t in tests:
                key, args = (t, {}) if isinstance(t, str) else next(iter(t.items()))
                if isinstance(t, dict) and "type" in t:
                    key, args = t["type"], t
                args = args or {}
                if "arguments" in args:
                    args = args["arguments"]
                if key == "unique":
                    raw["unique"] = True
                elif key == "not_null":
                    raw["nullable"] = False
                elif key == "primary_key":
                    pending_pk.append(c["name"])
                elif key == "accepted_values":
                    raw["type"] = "category"
                    raw["allowed_values"] = list(args.get("values", []))
                elif key == "relationships":
                    match = re.search(r"ref\(\s*['\"]([^'\"]+)['\"]\s*\)", str(args.get("to", "")))
                    if match:
                        raw["foreign_key"] = {"table": match.group(1),
                                              "column": args.get("field", "id")}
            cols.append(raw)
        draft = _TableDraft(tname)
        draft.primary_key = pending_pk or [
            r["name"] for r in cols
            if r.get("unique") and r.get("nullable") is False and "foreign_key" not in r
        ][:1]
        for raw in cols:
            draft.columns[raw["name"]] = raw
        for raw in cols:
            _apply_semantics(raw, draft)
        tables.append(Table(name=tname, columns=[Column(**r) for r in cols],
                            primary_key=draft.primary_key))
    try:
        return Schema(name=name, tables=tables, warnings=warnings)
    except ValueError as exc:
        raise DDLParseError("invalid_schema", _first_error(exc), param="dbt") from None
