"""The relational orchestrator: generate every table of a schema, parents first.

How one run works (think of an assembly line):

1. Sort tables so parents come before children (:mod:`.ordering`).
2. For each table, decide how many rows it gets. For a child table, first
   decide how many children *each parent* gets (skewed, like real data), then
   the child rows point at those parents, so every foreign key resolves (FR4).
3. Fill each column with its type generator, or from a fitted model when the
   table was learned from a sample (FR3).
4. Apply scenarios (e.g. 2% fraud), repair row checks like
   ``end_date > start_date``, then add nulls where allowed.
5. Validate every rule. If anything still breaks, fail loudly instead of
   returning bad data.

A single ``numpy.random.Generator`` created from the seed is passed through
every step in a fixed order, so the same schema + seed + engine version always
gives the same values (FR10).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from synthetic.engine.base import TabularModel
from synthetic.engine.constraints import (
    DAY,
    as_numeric,
    check_mask,
    numeric_bounds,
    step,
    validate_table,
)
from synthetic.engine.generators import apply_nulls, emails_from_names, generate_column
from synthetic.engine.ordering import topological_order
from synthetic.engine.scenarios import Scenario, apply_rare_event, validate_scenarios
from synthetic.engine.version import ENGINE_VERSION
from synthetic.errors import ConstraintError, SchemaError
from synthetic.schema import ORDERED_TYPES, ChildCount, Column, Schema, Table

DEFAULT_ROOT_ROWS = 100
DEFAULT_CHILDREN_MEAN = 3.0

ProgressFn = Callable[[float, str], None]


class GenerationCancelled(Exception):
    """Raised when a caller asks a running generation to stop."""


@dataclass
class GenerationResult:
    """Generated tables plus metadata for audit (PRD §8.1 observability)."""

    tables: dict[str, pd.DataFrame]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def row_counts(self) -> dict[str, int]:
        return {name: len(df) for name, df in self.tables.items()}


# ---------------------------------------------------------------------------
# children per parent
# ---------------------------------------------------------------------------


def allocate_children(n_parents: int, spec: ChildCount | None, total: int | None,
                      rng: np.random.Generator, where: str = "") -> np.ndarray:
    """Return how many children each parent gets.

    If ``total`` is given, the counts add up to exactly ``total`` and the
    distribution only shapes the skew. Otherwise each parent's count is drawn
    from the distribution directly.
    """
    spec = spec or ChildCount()
    if n_parents == 0:
        if total:
            raise ConstraintError("no_parents", f"{where}: cannot create child rows without parent rows.")
        return np.zeros(0, dtype=np.int64)
    lo = spec.min
    hi = spec.max
    if total is not None:
        mean = total / n_parents
        if n_parents * lo > total or (hi is not None and n_parents * hi < total):
            raise ConstraintError(
                "child_count_unsatisfiable",
                f"{where}: {total} child rows cannot be split across {n_parents} parents with "
                f"between {lo} and {hi if hi is not None else 'any'} children each.",
            )
    else:
        mean = spec.mean if spec.mean is not None else DEFAULT_CHILDREN_MEAN

    if total is None:
        if spec.distribution == "fixed":
            counts = np.full(n_parents, int(round(mean)), dtype=np.int64)
        elif spec.distribution == "poisson":
            counts = rng.poisson(mean, n_parents)
        elif spec.distribution == "uniform":
            top = hi if hi is not None else max(lo, int(round(2 * mean)))
            counts = rng.integers(lo, top, size=n_parents, endpoint=True)
        else:
            r = 2.0  # dispersion: smaller = more skewed
            counts = rng.negative_binomial(r, r / (r + mean), n_parents)
        return np.clip(counts, lo, hi if hi is not None else None).astype(np.int64)

    # Fixed total: spread the rows using weights shaped like the distribution.
    if spec.distribution == "fixed":
        weights = np.ones(n_parents)
    elif spec.distribution == "poisson":
        weights = np.ones(n_parents)
    elif spec.distribution == "uniform":
        weights = rng.uniform(0.05, 1.0, n_parents)
    else:
        weights = rng.gamma(2.0, 1.0, n_parents)  # Poisson-gamma mix = negative binomial
    counts = np.full(n_parents, lo, dtype=np.int64)
    remaining = total - lo * n_parents
    if spec.distribution == "fixed":
        base, extra = divmod(remaining, n_parents)
        counts += base
        if extra:
            counts[rng.choice(n_parents, size=extra, replace=False)] += 1
        return counts
    p = weights / weights.sum()
    counts += rng.multinomial(remaining, p)
    if hi is not None:
        for _ in range(100):
            over = counts > hi
            if not over.any():
                break
            excess = int((counts[over] - hi).sum())
            counts[over] = hi
            room = counts < hi
            p_room = np.where(room, p, 0.0)
            counts += rng.multinomial(excess, p_room / p_room.sum())
        counts = np.minimum(counts, hi)
    return counts


def _popularity(n: int, rng: np.random.Generator) -> np.ndarray:
    """Zipf-like weights: a few parents (e.g. best-selling products) are picked often."""
    ranks = rng.permutation(n) + 1
    w = 1.0 / ranks**0.7
    return w / w.sum()


# ---------------------------------------------------------------------------
# writing numeric values back into typed columns
# ---------------------------------------------------------------------------


def _from_numeric(values: np.ndarray, col: Column) -> pd.Series:
    mask = np.isnan(values)
    if col.type == "int":
        out = pd.array(np.where(mask, 0, np.rint(values)).astype(np.int64), dtype="Int64")
        out[mask] = pd.NA
        return pd.Series(out)
    if col.type == "float":
        decimals = col.decimals if col.decimals is not None else 2
        return pd.Series(np.round(values, decimals), dtype="float64")
    if col.type == "date":
        values = np.floor(values / DAY) * DAY
    secs = np.where(mask, 0, values).astype(np.int64).astype("datetime64[s]")
    series = pd.Series(secs)
    series[mask] = pd.NaT
    return series


# ---------------------------------------------------------------------------
# check repair
# ---------------------------------------------------------------------------


def repair_checks(df: pd.DataFrame, table: Table, rng: np.random.Generator,
                  regenerate: Callable[[str, int], pd.Series]) -> pd.DataFrame:
    """Fix rows that break a row check, keeping values within their own bounds."""
    for _round in range(3):
        clean = True
        for check in table.checks:
            bad = ~check_mask(df, table, check)
            if not bad.any():
                continue
            clean = False
            left = table.column(check.left)
            if check.right_column is not None and left.type in ORDERED_TYPES \
                    and table.column(check.right_column).type in ORDERED_TYPES:
                _repair_ordered_pair(df, table, check.left, check.op, check.right_column, bad, rng)
            else:
                k = int(bad.sum())
                df.loc[bad, check.left] = regenerate(check.left, k).to_numpy()
        if clean:
            break
    return df


def _repair_ordered_pair(df: pd.DataFrame, table: Table, left_name: str, op: str, right_name: str,
                         bad: np.ndarray, rng: np.random.Generator) -> None:
    left, right = table.column(left_name), table.column(right_name)
    L = as_numeric(df[left_name], left)
    R = as_numeric(df[right_name], right)
    if op in ("=", "!="):
        if op == "=":
            L[bad] = R[bad]
        else:
            L[bad] = R[bad] + step(left)
        df[left_name] = _from_numeric(L, left)
        return
    # Normalise to "big > small" (or >=).
    if op in (">", ">="):
        big_c, small_c, big, small = left, right, L, R
    else:
        big_c, small_c, big, small = right, left, R, L
    strict = op in (">", "<")
    big_lo, big_hi = numeric_bounds(big_c, table)
    small_lo, small_hi = numeric_bounds(small_c, table)

    # 1) Swapping the two values keeps both marginal distributions intact.
    swap = bad & (big < small) & (small <= big_hi) & (small >= big_lo) & (big >= small_lo) & (big <= small_hi)
    big[swap], small[swap] = small[swap].copy(), big[swap].copy()

    def violated() -> np.ndarray:
        with np.errstate(invalid="ignore"):
            ok = (big > small) if strict else (big >= small)
        return bad & ~ok & ~np.isnan(big) & ~np.isnan(small)

    # 2) Push the bigger side up by a small realistic gap.
    still = violated()
    if still.any():
        gap_unit = max(step(big_c), step(small_c))
        spread = max((big_hi - big_lo) * 0.05, gap_unit)
        gap = gap_unit + np.floor(rng.random(int(still.sum())) * spread / gap_unit) * gap_unit
        big[still] = np.minimum(small[still] + gap, big_hi)
    # 3) If the bigger side hit its ceiling, pull the smaller side down instead.
    still = violated()
    if still.any():
        gap_unit = max(step(big_c), step(small_c))
        small[still] = np.maximum(big[still] - gap_unit, small_lo)
    if big_c.name == left_name:
        df[left_name], df[right_name] = _from_numeric(big, big_c), _from_numeric(small, small_c)
    else:
        df[right_name], df[left_name] = _from_numeric(big, big_c), _from_numeric(small, small_c)


# ---------------------------------------------------------------------------
# the orchestrator
# ---------------------------------------------------------------------------


def _unique_capacity(table: Table, driving: Column, done: dict[str, pd.DataFrame]) -> int | None:
    """Max children per parent allowed by a composite key such as (order_id, product_id).

    Each order can contain each product only once, so an order can have at
    most as many items as there are products.
    """
    groups = list(table.unique_together)
    if len(table.primary_key) > 1:
        groups.append(table.primary_key)
    best: int | None = None
    for group in groups:
        if driving.name not in group:
            continue
        capacity = 1
        for name in group:
            if name == driving.name:
                continue
            col = table.column(name)
            if col.foreign_key is not None and col.foreign_key.table in done:
                capacity *= int(done[col.foreign_key.table][col.foreign_key.column].nunique())
            elif col.type == "category" and col.allowed_values:
                capacity *= len(col.allowed_values)
            elif col.type == "bool":
                capacity *= 2
            else:
                capacity = -1  # effectively unbounded
                break
        if capacity >= 0:
            best = capacity if best is None else min(best, capacity)
    return best


def _cap_children(spec: ChildCount | None, cap: int | None) -> ChildCount | None:
    if cap is None:
        return spec
    spec = spec or ChildCount()
    if spec.max is not None and spec.max <= cap:
        return spec
    return spec.model_copy(update={"max": cap, "min": min(spec.min, cap)})


def _driving_fk(table: Table) -> Column | None:
    """The foreign key that decides row counts: the first one with ``children``, else the first."""
    fks = [c for c in table.foreign_keys if c.foreign_key and c.foreign_key.table != table.name]
    with_spec = [c for c in fks if c.foreign_key and c.foreign_key.children is not None]
    return (with_spec or fks or [None])[0]


def generate(
    schema: Schema,
    rows: dict[str, int] | None = None,
    seed: int = 0,
    scenarios: list[Scenario] | None = None,
    models: dict[str, TabularModel] | None = None,
    no_copy: dict[str, Any] | None = None,
    progress: ProgressFn | None = None,
    should_cancel: Callable[[], bool] | None = None,
    rng: np.random.Generator | None = None,
) -> GenerationResult:
    """Generate all tables of ``schema``.

    Args:
        rows: requested rows per table. Child tables without a count get one
            from their child-count settings; root tables default to their
            ``rows`` field or 100.
        seed: the only source of randomness (FR10).
        scenarios: e.g. ``[Scenario(column="orders.is_fraud", rate=0.02)]``.
        models: fitted models per table name (sample learning, FR3).
        no_copy: per table, a filter with ``matches(df) -> bool array`` that
            flags rows identical to a source row; those rows are resampled
            (FR8).
        progress: callback ``(fraction 0..1, message)``.
        should_cancel: callback; return True to stop between tables.
        rng: an existing generator to continue from (the pipeline passes the
            one it already used for fitting); defaults to ``default_rng(seed)``.
    """
    rows = dict(rows or {})
    scenarios = list(scenarios or [])
    models = models or {}
    no_copy = no_copy or {}
    unknown = [t for t in rows if t not in schema.table_names]
    if unknown:
        raise SchemaError("unknown_table", f"Row counts given for unknown table(s): {', '.join(unknown)}.",
                          param="rows")
    if any(v < 0 for v in rows.values()):
        raise SchemaError("invalid_rows", "Row counts must be zero or positive.", param="rows")
    validate_scenarios(schema, scenarios)

    order = topological_order(schema)
    rng = rng if rng is not None else np.random.default_rng(seed)
    tables: dict[str, pd.DataFrame] = {}
    timings: dict[str, float] = {}
    dropped: dict[str, int] = {}
    started = time.perf_counter()

    for index, name in enumerate(order):
        if should_cancel and should_cancel():
            raise GenerationCancelled()
        t0 = time.perf_counter()
        table = schema.table(name)
        df, n_dropped = _generate_table(table, tables, rows, scenarios, models.get(name),
                                        no_copy.get(name), rng)
        tables[name] = df
        if n_dropped:
            dropped[name] = n_dropped
        timings[name] = round(time.perf_counter() - t0, 4)
        if progress:
            progress((index + 1) / len(order), f"generated {name}")

    # Keep the original schema order for output.
    ordered = {t: tables[t] for t in schema.table_names}
    metadata = {
        "engine_version": ENGINE_VERSION,
        "seed": seed,
        "rows": {k: len(v) for k, v in ordered.items()},
        "table_order": order,
        "models": {k: m.name for k, m in models.items()},
        "scenarios": [s.model_dump() for s in scenarios],
        "rows_dropped_no_copy": dropped,
        "timings_s": {**timings, "total": round(time.perf_counter() - started, 4)},
    }
    return GenerationResult(tables=ordered, metadata=metadata)


def _generate_table(table: Table, done: dict[str, pd.DataFrame], rows: dict[str, int],
                    scenarios: list[Scenario], model: TabularModel | None, no_copy: Any,
                    rng: np.random.Generator) -> tuple[pd.DataFrame, int]:
    driving = _driving_fk(table)
    counts = None
    if driving is not None:
        fk = driving.foreign_key
        assert fk is not None
        parent_keys = done[fk.table][fk.column].dropna().reset_index(drop=True)
        spec = _cap_children(fk.children, _unique_capacity(table, driving, done))
        counts = allocate_children(len(parent_keys), spec, rows.get(table.name), rng,
                                   where=f"{table.name}.{driving.name}")
        n = int(counts.sum())
    else:
        n = rows.get(table.name, table.rows if table.rows is not None else DEFAULT_ROOT_ROWS)

    modeled: pd.DataFrame | None = None
    if model is not None:
        modeled = model.sample(n, rng).reset_index(drop=True)
        if no_copy is not None:
            modeled = _resample_copies(modeled, model, no_copy, rng)

    def regenerate(col_name: str, k: int) -> pd.Series:
        """New values for ``k`` rows of one column (used by repairs)."""
        col = table.column(col_name)
        if modeled is not None and col_name in modeled.columns:
            return model.sample(k, rng)[col_name].reset_index(drop=True)  # type: ignore[union-attr]
        if col.foreign_key is not None and col.foreign_key.table in done:
            keys = done[col.foreign_key.table][col.foreign_key.column].dropna().to_numpy()
            return pd.Series(keys[rng.integers(0, len(keys), size=k)])
        return generate_column(col, table, k, rng)

    data: dict[str, pd.Series] = {}
    self_refs: list[Column] = []
    for col in table.columns:
        fk = col.foreign_key
        if modeled is not None and col.name in modeled.columns:
            data[col.name] = modeled[col.name]
        elif fk is not None and fk.table == table.name:
            self_refs.append(col)
            data[col.name] = pd.Series([None] * n, dtype=object)
        elif fk is not None:
            keys = done[fk.table][fk.column].dropna().reset_index(drop=True)
            if col is driving:
                assert counts is not None
                values = np.repeat(keys.to_numpy(), counts)
                values = values[rng.permutation(len(values))]
            elif len(keys) == 0:
                if not col.nullable:
                    raise ConstraintError("no_parents", f"{table.name}.{col.name}: parent table "
                                          f"'{fk.table}' has no rows.")
                values = np.array([None] * n, dtype=object)
            else:
                values = keys.to_numpy()[rng.choice(len(keys), size=n, p=_popularity(len(keys), rng))]
            data[col.name] = pd.Series(values, dtype=keys.dtype if len(keys) else object)
        else:
            data[col.name] = generate_column(col, table, n, rng)
    df = pd.DataFrame(data)

    for col in self_refs:
        df[col.name] = _self_reference(df, table, col, rng)

    _align_emails_with_names(df, table, set(modeled.columns) if modeled is not None else set(), rng)

    _enforce_unique_groups(df, table, driving, regenerate)

    for sc in scenarios:
        t_name, c_name = sc.target()
        if t_name == table.name:
            col = table.column(c_name)
            df = apply_rare_event(df, c_name, sc, col.type, col.allowed_values, col.weights, rng)

    df = repair_checks(df, table, rng, regenerate)

    for col in table.columns:
        is_modeled = modeled is not None and col.name in modeled.columns
        if not is_modeled and col not in self_refs:
            df[col.name] = apply_nulls(df[col.name], col, rng)

    n_dropped = 0
    if no_copy is not None:
        copies = no_copy.matches(df)
        n_dropped = int(copies.sum())
        if n_dropped:
            df = df[~copies].reset_index(drop=True)

    violations = validate_table(df, table)
    if violations:
        first = violations[0]
        raise ConstraintError(
            "constraint_unsatisfiable",
            f"Could not satisfy rule '{first.rule}' on {table.name}.{', '.join(first.columns)} "
            f"for {first.count} row(s). Loosen the constraint or change the row counts.",
            param=table.name,
        )
    return df, n_dropped


def _resample_copies(modeled: pd.DataFrame, model: TabularModel, no_copy: Any,
                     rng: np.random.Generator, rounds: int = 10) -> pd.DataFrame:
    """Replace sampled rows that exactly equal a source row with fresh samples (FR8)."""
    for _ in range(rounds):
        copies = no_copy.matches(modeled)
        if not copies.any():
            break
        fresh = model.sample(int(copies.sum()), rng).reset_index(drop=True)
        idx = np.flatnonzero(copies)
        for col in modeled.columns:
            modeled.loc[idx, col] = fresh[col].to_numpy()
    return modeled


def _align_emails_with_names(df: pd.DataFrame, table: Table, modeled: set[str],
                             rng: np.random.Generator) -> None:
    """If a table has first/last (or full) name columns, derive its emails from them."""
    names = {c.subtype or "full": c.name for c in table.columns if c.type == "name" and c.name not in modeled}
    if "first" in names and "last" in names:
        first, last = df[names["first"]], df[names["last"]]
    elif "full" in names:
        parts = df[names["full"]].astype(str).str.split(" ", n=1, expand=True)
        if parts.shape[1] < 2:
            return
        first, last = parts[0], parts[1].fillna("")
    else:
        return
    for col in table.columns:
        if col.type == "email" and col.name not in modeled and not col.foreign_key:
            df[col.name] = emails_from_names(first, last, col.unique, rng)
            if col.max_length:
                df[col.name] = df[col.name].str.slice(0, col.max_length)


def _self_reference(df: pd.DataFrame, table: Table, col: Column, rng: np.random.Generator) -> pd.Series:
    """Point each row at an earlier row of the same table (e.g. an employee's manager)."""
    fk = col.foreign_key
    assert fk is not None
    keys = df[fk.column].to_numpy()
    n = len(df)
    out = np.empty(n, dtype=object)
    if n == 0:
        return pd.Series(out)
    # Row i points at a random row j < i, so the result is a tree (no cycles).
    picks = np.floor(rng.random(n) * np.arange(n)).astype(np.int64)
    out[:] = keys[picks]
    if col.nullable:
        out[0] = None
        if col.null_rate > 0:
            out[rng.random(n) < col.null_rate] = None
    return pd.Series(pd.array(out, dtype=df[fk.column].dtype))


def _enforce_unique_groups(df: pd.DataFrame, table: Table, driving: Column | None,
                           regenerate: Callable[[str, int], pd.Series]) -> None:
    """Make composite primary keys and UNIQUE (a, b) groups hold."""
    groups = list(table.unique_together)
    if len(table.primary_key) > 1:
        groups.append(table.primary_key)
    for group in groups:
        free = [c for c in group if not (driving is not None and c == driving.name)]
        if not free:
            continue
        target = free[-1]
        for _ in range(30):
            dup = df.duplicated(subset=group).to_numpy()
            if not dup.any():
                break
            df.loc[dup, target] = regenerate(target, int(dup.sum())).to_numpy()
        if df.duplicated(subset=group).any():
            raise ConstraintError(
                "unique_unsatisfiable",
                f"Could not make ({', '.join(group)}) unique in table '{table.name}'. "
                "There may be too few distinct values (for example, more items per order than products).",
                param=table.name,
            )
