"""Constraint helpers: value bounds, repairs and validation (FR4).

Two jobs live here:

1. **Bounds.** Work out the real range a column may take, combining its
   ``min``/``max``, sensible defaults and literal checks like ``amount > 0``.
2. **Validation.** Check a generated table against every declared rule (not
   null, unique, ranges, allowed values, row checks, foreign keys) and count
   violations. The engine runs this before returning data, the report shows
   it, and the tests assert it is zero.

Dates and datetimes are handled as whole seconds since 1970 ("epoch seconds"),
so the same arithmetic works for numbers and times.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from synthetic.errors import ConstraintError
from synthetic.schema import ORDERED_TYPES, TEMPORAL_TYPES, CheckConstraint, Column, Schema, Table

DAY = 86_400
DEFAULT_DATE_RANGE = ("2021-01-01", "2026-10-31")
DEFAULT_WIDTH = {"int": 999, "float": 1000.0}


def to_epoch(value: Any) -> int:
    """Convert a date/datetime literal (``"2024-05-01"``) to epoch seconds."""
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return int(ts.value // 1_000_000_000)


def step(col: Column) -> float:
    """Smallest meaningful difference between two values of this column."""
    if col.type == "int":
        return 1
    if col.type == "float":
        return 10.0 ** -(col.decimals if col.decimals is not None else 2)
    if col.type == "date":
        return DAY
    return 1  # datetime: one second


def _raw(col: Column, value: Any) -> float:
    if col.type in TEMPORAL_TYPES:
        return float(to_epoch(value))
    return float(value)


def numeric_bounds(col: Column, table: Table | None = None) -> tuple[float, float]:
    """Inclusive (low, high) range for an ordered column, in numeric space.

    Literal checks on the column (``amount > 0``) tighten the range, honouring
    strictness: ``> 0`` on a 2-decimal float becomes ``>= 0.01``.
    """
    if col.type not in ORDERED_TYPES:
        raise ValueError(f"{col.name} is not an ordered column")
    lo = _raw(col, col.min) if col.min is not None else None
    hi = _raw(col, col.max) if col.max is not None else None
    for check in (table.checks if table else []):
        if check.left != col.name or check.value is None or isinstance(check.value, bool):
            continue
        try:
            v = _raw(col, check.value)
        except (TypeError, ValueError):
            continue
        if check.op == ">":
            lo = max(lo, v + step(col)) if lo is not None else v + step(col)
        elif check.op == ">=":
            lo = max(lo, v) if lo is not None else v
        elif check.op == "<":
            hi = min(hi, v - step(col)) if hi is not None else v - step(col)
        elif check.op == "<=":
            hi = min(hi, v) if hi is not None else v
    if lo is not None and hi is not None and lo > hi and not _is_explicit(col, table):
        hi = lo + _default_width(col)
    if col.type in TEMPORAL_TYPES:
        dlo, dhi = (float(to_epoch(d)) for d in DEFAULT_DATE_RANGE)
        width = dhi - dlo
    else:
        default_lo = 1.0 if col.type == "int" else 0.0
        width = _default_width(col)
        dlo, dhi = default_lo, default_lo + width
    if lo is None and hi is None:
        lo, hi = dlo, dhi
    elif lo is None:
        lo = min(hi - width, hi) if hi is not None else dlo
    elif hi is None:
        hi = lo + width
    if col.type == "int":
        lo, hi = float(np.ceil(lo)), float(np.floor(hi))
    if col.type == "date":
        lo, hi = float(np.ceil(lo / DAY) * DAY), float(np.floor(hi / DAY) * DAY)
    if lo > hi:
        raise ConstraintError(
            "empty_range",
            f"Column '{col.name}' has no valid values: its minimum is above its maximum. "
            "Loosen the min/max or the CHECK constraints.",
            param=col.name,
        )
    return lo, hi


def _is_explicit(col: Column, table: Table | None) -> bool:
    return col.min is not None and col.max is not None


def _default_width(col: Column) -> float:
    if col.type in TEMPORAL_TYPES:
        return float(to_epoch(DEFAULT_DATE_RANGE[1]) - to_epoch(DEFAULT_DATE_RANGE[0]))
    return float(DEFAULT_WIDTH["int" if col.type == "int" else "float"])


def as_numeric(series: pd.Series, col: Column) -> np.ndarray:
    """Values of an ordered column as float64 (epoch seconds for times); NaN for nulls."""
    if col.type in TEMPORAL_TYPES:
        values = pd.to_datetime(series, errors="coerce")
        out = np.full(len(series), np.nan)
        mask = values.notna().to_numpy()
        out[mask] = values[mask].astype("datetime64[s]").astype("int64").to_numpy()
        return out
    return pd.to_numeric(series, errors="coerce").astype("float64").to_numpy(na_value=np.nan)


def compare(left: np.ndarray, op: str, right: np.ndarray | float) -> np.ndarray:
    """Element-wise comparison. NULL on either side counts as satisfied (SQL semantics)."""
    with np.errstate(invalid="ignore"):
        if op == ">":
            ok = left > right
        elif op == ">=":
            ok = left >= right
        elif op == "<":
            ok = left < right
        elif op == "<=":
            ok = left <= right
        elif op == "=":
            ok = left == right
        else:
            ok = left != right
    null = np.isnan(left) | (np.isnan(right) if isinstance(right, np.ndarray) else np.isnan(right))
    return ok | null


def check_mask(df: pd.DataFrame, table: Table, check: CheckConstraint) -> np.ndarray:
    """Boolean array: True where the row satisfies ``check``."""
    col = table.column(check.left)
    if check.right_column is not None:
        right_col = table.column(check.right_column)
        if col.type in ORDERED_TYPES and right_col.type in ORDERED_TYPES:
            return compare(as_numeric(df[col.name], col), check.op, as_numeric(df[right_col.name], right_col))
        left_v, right_v = df[col.name], df[right_col.name]
        null = (left_v.isna() | right_v.isna()).to_numpy()
        eq = (left_v.astype(object) == right_v.astype(object)).to_numpy()
        if check.op == "=":
            return null | eq
        if check.op == "!=":
            return null | ~eq
        return np.ones(len(df), bool)  # ordering text columns is not supported
    if col.type in ORDERED_TYPES and not isinstance(check.value, bool):
        try:
            value = _raw(col, check.value)
        except (TypeError, ValueError):
            return np.ones(len(df), bool)
        return compare(as_numeric(df[col.name], col), check.op, value)
    series = df[col.name]
    null = series.isna().to_numpy()
    eq = (series.astype(object) == check.value).to_numpy()
    if check.op == "=":
        return null | eq
    if check.op == "!=":
        return null | ~eq
    return np.ones(len(df), bool)


@dataclass
class Violation:
    """How many rows break one rule."""

    table: str
    rule: str
    columns: list[str]
    count: int

    def as_dict(self) -> dict[str, Any]:
        return {"table": self.table, "rule": self.rule, "columns": self.columns, "count": self.count}


def validate_table(df: pd.DataFrame, table: Table) -> list[Violation]:
    """Return every rule that at least one row of ``df`` breaks (FK checks excluded)."""
    out: list[Violation] = []

    def add(rule: str, cols: list[str], count: int) -> None:
        if count:
            out.append(Violation(table.name, rule, cols, int(count)))

    for col in table.columns:
        if col.name not in df.columns:
            add("missing_column", [col.name], len(df) or 1)
            continue
        series = df[col.name]
        nulls = series.isna()
        if not col.nullable:
            add("not_null", [col.name], nulls.sum())
        if col.unique:
            add("unique", [col.name], series[~nulls].duplicated().sum())
        if col.type in ORDERED_TYPES and (col.min is not None or col.max is not None):
            values = as_numeric(series, col)
            if col.min is not None:
                add("min", [col.name], (~compare(values, ">=", _raw(col, col.min))).sum())
            if col.max is not None:
                add("max", [col.name], (~compare(values, "<=", _raw(col, col.max))).sum())
        if col.allowed_values is not None:
            allowed = set(col.allowed_values)
            bad = ~series[~nulls].astype(object).isin(allowed)
            add("allowed_values", [col.name], bad.sum())
        if col.max_length is not None and col.type not in ORDERED_TYPES and col.type != "bool":
            lengths = series[~nulls].astype(str).str.len()
            add("max_length", [col.name], (lengths > col.max_length).sum())
    if len(table.primary_key) > 1:
        add("primary_key", table.primary_key, df.duplicated(subset=table.primary_key).sum())
    for group in table.unique_together:
        sub = df[group].dropna()
        add("unique_together", group, sub.duplicated().sum())
    for check in table.checks:
        add(f"check: {check.describe()}", [check.left] + ([check.right_column] if check.right_column else []),
            (~check_mask(df, table, check)).sum())
    return out


@dataclass
class ForeignKeyResult:
    """How many child foreign-key values point at an existing parent row."""

    child: str
    parent: str
    total: int
    resolved: int

    @property
    def resolved_pct(self) -> float:
        return 100.0 if self.total == 0 else 100.0 * self.resolved / self.total

    def as_dict(self) -> dict[str, Any]:
        return {"child": self.child, "parent": self.parent, "non_null": self.total,
                "resolved": self.resolved, "resolved_pct": round(self.resolved_pct, 4)}


def check_foreign_keys(schema: Schema, tables: dict[str, pd.DataFrame]) -> list[ForeignKeyResult]:
    """For every foreign key, count non-null values and how many resolve to a parent."""
    results = []
    for rel in schema.relationships():
        child_df = tables.get(rel.child_table)
        parent_df = tables.get(rel.parent_table)
        if child_df is None:
            continue
        values = child_df[rel.child_column].dropna()
        if parent_df is None:
            resolved = 0
        else:
            keys = parent_df[rel.parent_column].dropna()
            resolved = int(values.astype(object).isin(set(keys.astype(object))).sum())
        results.append(ForeignKeyResult(
            child=f"{rel.child_table}.{rel.child_column}",
            parent=f"{rel.parent_table}.{rel.parent_column}",
            total=int(len(values)),
            resolved=resolved,
        ))
    return results


def validate_dataset(schema: Schema, tables: dict[str, pd.DataFrame]) -> list[Violation]:
    """Validate every table plus foreign keys; return all violations."""
    out: list[Violation] = []
    for table in schema.tables:
        if table.name in tables:
            out.extend(validate_table(tables[table.name], table))
    for fk in check_foreign_keys(schema, tables):
        missing = fk.total - fk.resolved
        if missing:
            table, column = fk.child.split(".", 1)
            out.append(Violation(table, f"foreign_key -> {fk.parent}", [column], missing))
    return out
