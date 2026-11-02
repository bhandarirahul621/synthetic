"""Fidelity: how closely the synthetic data matches the source or the spec.

Two modes:

* **Sample mode** (a source sample was uploaded). For each learned column:

  - numbers and dates: ``1 - KS``. The Kolmogorov-Smirnov statistic is the
    biggest vertical gap between the two cumulative distribution curves; 0
    means identical shapes, so ``1 - KS`` is a similarity from 0 to 1.
  - categories and booleans: ``1 - TVD``. Total variation distance is half the
    sum of absolute differences in category shares ("how much probability
    would you have to move to make them equal").

  Plus a *correlation* similarity: we build a matrix of pairwise
  associations (Spearman for number-number, Cramér's V for
  category-category, correlation ratio for number-category) for both
  datasets and compare them.

* **Spec mode** (schema only). There is no real data to compare against, so
  we check *conformance*: values inside their ranges, category shares close
  to the declared weights, null rates and scenario rates as requested, and
  children-per-parent close to the declared mean.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from synthetic.engine.constraints import as_numeric, numeric_bounds
from synthetic.engine.fit import coerce
from synthetic.schema import ORDERED_TYPES, Column, Schema, Table

ORDERED = ORDERED_TYPES


def _numeric(series: pd.Series, col: Column) -> np.ndarray:
    values = as_numeric(series, col)
    return values[~np.isnan(values)]


def ks_similarity(real: np.ndarray, synth: np.ndarray) -> float:
    """``1 - KS statistic`` between two numeric samples (1 = identical shape)."""
    if len(real) == 0 or len(synth) == 0:
        return 0.0
    return float(1.0 - stats.ks_2samp(real, synth).statistic)


def tvd_similarity(real: pd.Series, synth: pd.Series) -> float:
    """``1 - total variation distance`` between two categorical samples."""
    r = real.dropna().astype(str).value_counts(normalize=True)
    s = synth.dropna().astype(str).value_counts(normalize=True)
    if r.empty and s.empty:
        return 1.0
    idx = r.index.union(s.index)
    return float(1.0 - 0.5 * np.abs(r.reindex(idx, fill_value=0) - s.reindex(idx, fill_value=0)).sum())


def _cramers_v(a: pd.Series, b: pd.Series) -> float:
    table = pd.crosstab(a, b)
    if table.shape[0] < 2 or table.shape[1] < 2:
        return 0.0
    chi2 = stats.chi2_contingency(table, correction=False)[0]
    n = table.to_numpy().sum()
    k = min(table.shape) - 1
    return float(np.sqrt(chi2 / (n * k))) if n and k else 0.0


def _correlation_ratio(categories: pd.Series, values: pd.Series) -> float:
    frame = pd.DataFrame({"c": categories, "v": values}).dropna()
    if frame.empty or frame["v"].var() == 0:
        return 0.0
    grand = frame["v"].mean()
    groups = frame.groupby("c", observed=True)["v"]
    between = (groups.count() * (groups.mean() - grand) ** 2).sum()
    total = ((frame["v"] - grand) ** 2).sum()
    return float(np.sqrt(between / total)) if total else 0.0


def association_matrix(df: pd.DataFrame, columns: list[Column]) -> np.ndarray:
    """Pairwise association between columns, all on a 0..1 (or -1..1) scale."""
    prepared = {}
    for col in columns:
        if col.type in ORDERED:
            prepared[col.name] = ("num", pd.Series(as_numeric(df[col.name], col)))
        else:
            prepared[col.name] = ("cat", df[col.name].astype(object).where(df[col.name].notna(), None))
    k = len(columns)
    M = np.eye(k)
    for i in range(k):
        for j in range(i + 1, k):
            ki, a = prepared[columns[i].name]
            kj, b = prepared[columns[j].name]
            if ki == "num" and kj == "num":
                frame = pd.DataFrame({"a": a, "b": b}).dropna()
                v = frame["a"].corr(frame["b"], method="spearman") if len(frame) > 2 else 0.0
            elif ki == "cat" and kj == "cat":
                v = _cramers_v(a.astype(str), b.astype(str))
            elif ki == "cat":
                v = _correlation_ratio(a.astype(str), b)
            else:
                v = _correlation_ratio(b.astype(str), a)
            M[i, j] = M[j, i] = 0.0 if v is None or np.isnan(v) else v
    return M


def sample_fidelity(source: pd.DataFrame, synthetic: pd.DataFrame, columns: list[Column]) -> dict[str, Any]:
    """Compare learned columns of ``synthetic`` against the real ``source``."""
    per_column = []
    real_typed = pd.DataFrame({c.name: coerce(source[c.name], c) for c in columns})
    synth_typed = pd.DataFrame({c.name: coerce(synthetic[c.name], c) for c in columns})
    for col in columns:
        if col.type in ORDERED:
            sim = ks_similarity(_numeric(real_typed[col.name], col), _numeric(synth_typed[col.name], col))
            metric = "1 - KS statistic"
        else:
            sim = tvd_similarity(real_typed[col.name], synth_typed[col.name])
            metric = "1 - total variation distance"
        per_column.append({"column": col.name, "type": col.type, "metric": metric,
                           "similarity": round(sim, 4),
                           "null_rate_source": round(float(real_typed[col.name].isna().mean()), 4),
                           "null_rate_synthetic": round(float(synth_typed[col.name].isna().mean()), 4)})
    column_score = float(np.mean([c["similarity"] for c in per_column])) if per_column else 1.0
    corr: dict[str, Any] = {"applicable": len(columns) >= 2}
    corr_score = None
    if len(columns) >= 2:
        real_m = association_matrix(real_typed, columns)
        synth_m = association_matrix(synth_typed, columns)
        upper = np.triu_indices(len(columns), k=1)
        diff = np.abs(real_m[upper] - synth_m[upper])
        corr_score = float(max(0.0, 1.0 - diff.mean()))
        corr.update({
            "metric": "1 - mean absolute difference of pairwise associations",
            "similarity": round(corr_score, 4),
            "max_abs_difference": round(float(diff.max()), 4),
            "columns": [c.name for c in columns],
            "source_matrix": np.round(real_m, 3).tolist(),
            "synthetic_matrix": np.round(synth_m, 3).tolist(),
        })
    score = column_score if corr_score is None else 0.7 * column_score + 0.3 * corr_score
    return {"mode": "sample", "score": round(100 * score, 1), "column_score": round(100 * column_score, 1),
            "correlation_score": None if corr_score is None else round(100 * corr_score, 1),
            "columns": per_column, "correlation": corr}


# ---------------------------------------------------------------------------
# spec mode
# ---------------------------------------------------------------------------


def _expected_shares(col: Column, rate_override: tuple[Any, float] | None) -> dict[str, float] | None:
    if col.type == "bool":
        p = 0.5 if col.p_true is None else col.p_true
        if rate_override is not None:
            value, rate = rate_override
            p = rate if value in (None, True) else 1 - rate
        return {"True": p, "False": 1 - p}
    if col.type == "category" and col.allowed_values:
        values = [str(v) for v in col.allowed_values]
        w = np.asarray(col.weights if col.weights else [1.0] * len(values), dtype=float)
        shares = dict(zip(values, w / w.sum(), strict=True))
        if rate_override is not None:
            value, rate = rate_override
            rest = {k: v for k, v in shares.items() if k != str(value)}
            total = sum(rest.values()) or 1.0
            shares = {k: (1 - rate) * v / total for k, v in rest.items()}
            shares[str(value)] = rate
        return shares
    return None


def spec_fidelity(schema: Schema, tables: dict[str, pd.DataFrame],
                  scenarios: list[dict] | None = None, skip: set[str] | None = None,
                  requested_rows: dict[str, int] | None = None) -> dict[str, Any]:
    """Check generated tables against what the schema (and scenarios) asked for.

    ``requested_rows`` lists tables whose total the caller fixed; for those the
    children-per-parent mean is decided by the caller, not the spec, so it is
    not scored.
    """
    overrides = {}
    for sc in scenarios or []:
        overrides[sc["column"]] = (sc.get("value"), float(sc["rate"]))
    skip = skip or set()
    per_column = []
    for table in schema.tables:
        df = tables.get(table.name)
        if df is None or len(df) == 0:
            continue
        for col in table.columns:
            key = f"{table.name}.{col.name}"
            if key in skip or col.foreign_key is not None or col.primary_key:
                continue
            per_column.append(_column_conformance(df[col.name], col, table, overrides.get(key)))
    relationships = relationship_stats(schema, tables, fixed=set(requested_rows or {}))
    rel_scores = [r["similarity"] for r in relationships if r.get("similarity") is not None]
    scores = [c["similarity"] for c in per_column] + rel_scores
    score = float(np.mean(scores)) if scores else 1.0
    return {"mode": "spec", "score": round(100 * score, 1), "columns": per_column,
            "relationships": relationships,
            "note": "No source data was used, so fidelity measures conformance to the schema spec."}


def _column_conformance(series: pd.Series, col: Column, table: Table,
                        override: tuple[Any, float] | None) -> dict[str, Any]:
    parts: dict[str, float] = {}
    observed_null = float(series.isna().mean())
    parts["null_rate"] = 1.0 - abs(observed_null - (col.null_rate if col.nullable else 0.0))
    detail: dict[str, Any] = {"null_rate_expected": col.null_rate if col.nullable else 0.0,
                              "null_rate_observed": round(observed_null, 4)}
    if col.type in ORDERED:
        lo, hi = numeric_bounds(col, table)
        values = _numeric(series, col)
        parts["in_range"] = float(((values >= lo) & (values <= hi)).mean()) if len(values) else 1.0
    expected = _expected_shares(col, override)
    if expected is not None:
        observed = series.dropna().astype(str).value_counts(normalize=True)
        idx = sorted(set(expected) | set(observed.index))
        exp_s = pd.Series(expected).reindex(idx, fill_value=0.0)
        obs_s = observed.reindex(idx, fill_value=0.0)
        parts["shares"] = float(1.0 - 0.5 * np.abs(exp_s - obs_s).sum())
        if override is not None:
            value = "True" if override[0] in (None, True) else str(override[0])
            detail["scenario_rate_expected"] = override[1]
            detail["scenario_rate_observed"] = round(float(obs_s.get(value, 0.0)) * (1 - observed_null), 4)
    sim = float(np.mean(list(parts.values())))
    return {"column": f"{table.name}.{col.name}", "type": col.type, "metric": "spec conformance",
            "similarity": round(sim, 4), "checks": {k: round(v, 4) for k, v in parts.items()}, **detail}


def relationship_stats(schema: Schema, tables: dict[str, pd.DataFrame],
                       fixed: set[str] | None = None) -> list[dict[str, Any]]:
    """Children-per-parent statistics for every foreign key (cross-table fidelity)."""
    out = []
    for rel in schema.relationships():
        parent = tables.get(rel.parent_table)
        child = tables.get(rel.child_table)
        if parent is None or child is None or rel.parent_table == rel.child_table:
            continue
        counts = child[rel.child_column].dropna().value_counts()
        per_parent = counts.reindex(parent[rel.parent_column].dropna().unique(), fill_value=0)
        stats_ = {
            "relationship": f"{rel.parent_table}.{rel.parent_column} -> {rel.child_table}.{rel.child_column}",
            "parents": int(len(per_parent)),
            "children_mean": round(float(per_parent.mean()), 3) if len(per_parent) else 0.0,
            "children_p50": float(per_parent.median()) if len(per_parent) else 0.0,
            "children_p90": float(per_parent.quantile(0.9)) if len(per_parent) else 0.0,
            "children_max": int(per_parent.max()) if len(per_parent) else 0,
            "parents_without_children_pct": round(100 * float((per_parent == 0).mean()), 2)
            if len(per_parent) else 0.0,
            "similarity": None,
        }
        spec = rel.children
        if spec is not None and len(per_parent):
            ok_min = float((per_parent >= spec.min).mean())
            ok_max = float((per_parent <= spec.max).mean()) if spec.max is not None else 1.0
            sim = (ok_min + ok_max) / 2
            if spec.mean and rel.child_table not in (fixed or set()):
                sim = (sim + max(0.0, 1 - abs(per_parent.mean() - spec.mean) / spec.mean)) / 2
            stats_["similarity"] = round(sim, 4)
            stats_["expected"] = spec.model_dump(exclude_none=True)
        out.append(stats_)
    return out
