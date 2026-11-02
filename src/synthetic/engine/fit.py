"""Learn from a sample table and generate new rows like it (FR3, FR8).

The model is a **Gaussian copula**. In plain words:

1. For each column we learn its *shape* on its own (its "marginal"): for
   numbers, a table of quantiles ("10% of orders are under $12, 50% under
   $48, ..."); for categories, how often each value appears.
2. We convert every column to a common bell-curve scale ("normal scores"),
   so a $48 order and a "gold" tier customer can be compared, and measure
   how the columns move together: the *correlation matrix*.
3. To make a new row we draw correlated bell-curve numbers and map each one
   back through its column's shape. The result keeps each column's
   distribution *and* the relationships between columns, without copying
   any row.

Privacy rules built in (thresholds in :mod:`synthetic.report.thresholds`):

* PII columns (flagged by the user or detected from names/values) and
  identifier-like or free-text columns are **never fitted**; they are
  generated fresh by the spec generators.
* Quantile tables skip the extreme tails, so the single largest real value
  (e.g. one person's salary) is not reproduced.
* Rare categories (seen fewer than ``FIT_MIN_CATEGORY_COUNT`` times) are not
  learned, because a rare value can identify a person.
* After sampling, any row identical to a source row is resampled; leftovers
  are dropped (FR8). Only row *hashes* of the source are kept for this check.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from synthetic.engine.base import TabularModel, register_model
from synthetic.errors import FitError
from synthetic.report import thresholds as T
from synthetic.schema import Column, Schema, Table
from synthetic.semantics import infer_semantic

_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
_PHONE = re.compile(r"^\+?[\d\s().-]{7,20}$")
_TRUE = {"true", "t", "yes", "y", "1"}
_FALSE = {"false", "f", "no", "n", "0"}

#: How a column is handled when learning from a sample.
ROLE_MODELED = "modeled"      # learned by the copula
ROLE_FRESH = "fresh"          # generated from scratch (PII, free text, identifiers)
ROLE_KEY = "primary_key"      # regenerated as a new key


# ---------------------------------------------------------------------------
# reading samples
# ---------------------------------------------------------------------------


def read_sample(path: str | Path | None = None, data: bytes | None = None,
                filename: str | None = None) -> pd.DataFrame:
    """Read a CSV or Parquet sample from a path or from raw bytes."""
    name = str(filename or path or "")
    try:
        if name.lower().endswith((".parquet", ".pq")):
            return pd.read_parquet(path if data is None else io.BytesIO(data))
        source = path if data is None else io.BytesIO(data)
        return pd.read_csv(source, low_memory=False)
    except Exception as exc:  # pandas raises many types; never echo file content
        raise FitError("unreadable_sample",
                       f"The sample could not be read as {'Parquet' if name.endswith('parquet') else 'CSV'} "
                       f"({type(exc).__name__}). Check the file format and encoding.") from None


# ---------------------------------------------------------------------------
# type detection
# ---------------------------------------------------------------------------


@dataclass
class DetectedColumn:
    """What we inferred about one sample column. Contains no data values."""

    column: Column
    role: str
    reason: str


def _share(mask: pd.Series) -> float:
    return float(mask.mean()) if len(mask) else 0.0


def detect_column(series: pd.Series, name: str, table_name: str = "",
                  force_pii: bool = False) -> DetectedColumn:
    """Infer the column type and decide whether it is modeled or generated fresh."""
    non_null = series.dropna()
    n = len(non_null)
    null_rate = round(1.0 - n / len(series), 4) if len(series) else 0.0
    nullable = null_rate > 0
    base = {"name": name, "nullable": nullable, "null_rate": null_rate}
    sem = infer_semantic(name, table_name)

    def fresh(col_type: str, reason: str, subtype: str | None = None, pii: bool = True) -> DetectedColumn:
        return DetectedColumn(Column(type=col_type, subtype=subtype, pii=pii, **base), ROLE_FRESH, reason)

    if n == 0:
        return fresh("string", "column is empty", pii=False)

    # 1) PII by name or by the user's flag: never learned.
    if force_pii or (sem is not None and sem.pii):
        col_type = sem.type if sem else "string"
        if col_type in ("int", "float", "category", "bool"):
            col_type = "string"
        return fresh(col_type, "flagged as PII" if force_pii else "PII detected from column name",
                     subtype=sem.subtype if sem else None)

    as_text = non_null.astype(str).str.strip()
    lowered = as_text.str.lower()
    distinct = int(non_null.nunique())

    # 2) Booleans.
    numeric_dtype = pd.api.types.is_numeric_dtype(non_null) and not pd.api.types.is_bool_dtype(non_null)
    if pd.api.types.is_bool_dtype(non_null):
        return DetectedColumn(Column(type="bool", **base), ROLE_MODELED, "boolean values")
    if not numeric_dtype and distinct <= 2 and lowered.isin(_TRUE | _FALSE).all():
        return DetectedColumn(Column(type="bool", **base), ROLE_MODELED, "boolean values")
    if numeric_dtype and sem is not None and sem.type == "bool" and set(non_null.unique()) <= {0, 1}:
        return DetectedColumn(Column(type="bool", **base), ROLE_MODELED, "0/1 flag")

    # 3) Numbers.
    if numeric_dtype:
        values = non_null.astype(float)
        is_int = bool(np.all(np.isclose(values, np.round(values))))
        if is_int and _looks_like_id(name, table_name):
            if distinct == n and null_rate == 0 and _is_own_key(name, table_name):
                return DetectedColumn(Column(name=name, type="int", primary_key=True), ROLE_KEY,
                                      "unique identifier (regenerated as a new key)")
            return fresh("int", "identifier-like column (never learned)", pii=False)
        if is_int:
            return DetectedColumn(Column(type="int", **base), ROLE_MODELED, "integer values")
        decimals = _decimals(values)
        return DetectedColumn(Column(type="float", decimals=decimals, **base), ROLE_MODELED, "decimal values")

    # 4) Dates and datetimes.
    parsed = _parse_dates(as_text)
    if parsed is not None:
        is_date = bool((parsed.dt.normalize() == parsed).all())
        return DetectedColumn(Column(type="date" if is_date else "datetime", **base), ROLE_MODELED,
                              "date values" if is_date else "datetime values")

    # 5) Strings with a recognisable format.
    if _share(as_text.str.match(_UUID)) >= 0.95:
        return fresh("uuid", "UUID identifiers (never learned)", pii=False)
    if _share(as_text.str.match(_EMAIL)) >= 0.9:
        return fresh("email", "email addresses detected from values")
    digits = as_text.str.replace(r"\D", "", regex=True).str.len()
    if _share(as_text.str.match(_PHONE) & (digits >= 7)) >= 0.9 and not _numeric_like(as_text):
        return fresh("phone", "phone numbers detected from values")

    # 6) Categories vs free text.
    if distinct <= T.FIT_MAX_CATEGORIES and distinct <= max(2, 0.5 * n):
        return DetectedColumn(Column(type="category", **base), ROLE_MODELED, "few distinct values")
    words = as_text.str.split().str.len().mean()
    if words >= 4:
        return fresh("text", "free text (may contain personal data; never learned)")
    if sem is not None and sem.type in ("address", "name", "string"):
        return fresh(sem.type, "high-cardinality text (never learned)", subtype=sem.subtype,
                     pii=sem.type != "address" or sem.subtype in ("street", "zip", None))
    return fresh("string", "high-cardinality text such as codes or names (never learned)")


def _looks_like_id(name: str, table_name: str = "") -> bool:
    lowered = name.lower()
    return lowered == "id" or lowered.endswith("_id") or lowered == f"{table_name.lower()}id"


def _is_own_key(name: str, table_name: str) -> bool:
    """``id`` or ``<table>_id`` (singular or plural) is the table's own key."""
    lowered, table = name.lower(), table_name.lower()
    return lowered == "id" or lowered in (f"{table}_id", f"{table.rstrip('s')}_id")


def _numeric_like(text: pd.Series) -> bool:
    return bool(pd.to_numeric(text, errors="coerce").notna().mean() >= 0.9)


def _decimals(values: pd.Series) -> int:
    for d in range(0, 7):
        if np.allclose(values, np.round(values, d), atol=10 ** -(d + 3)):
            return d
    return 6


def _parse_dates(text: pd.Series) -> pd.Series | None:
    """Parse text as dates if at least 95% of values parse; else ``None``."""
    if _numeric_like(text):
        return None
    sample = text.head(2000)
    for fmt in ("ISO8601", "mixed"):
        try:
            parsed = pd.to_datetime(sample, errors="coerce", format=fmt)
        except (ValueError, TypeError):
            continue
        if parsed.notna().mean() >= 0.95:
            full = pd.to_datetime(text, errors="coerce", format=fmt)
            if getattr(full.dt, "tz", None) is not None:
                full = full.dt.tz_convert("UTC").dt.tz_localize(None)
            return full.dropna().astype("datetime64[s]")
    return None


# ---------------------------------------------------------------------------
# coercion: turn raw sample columns into typed values
# ---------------------------------------------------------------------------


def coerce(series: pd.Series, col: Column) -> pd.Series:
    """Convert a raw sample column to the canonical typed form for ``col.type``."""
    if col.type in ("int", "float"):
        out = pd.to_numeric(series, errors="coerce").astype("float64")
        if col.type == "float" and col.decimals is not None:
            out = out.round(col.decimals)
        return out.round(0) if col.type == "int" else out
    if col.type in ("date", "datetime"):
        out = pd.to_datetime(series.astype(object).where(series.notna(), None), errors="coerce",
                             format="mixed")
        if getattr(out.dt, "tz", None) is not None:
            out = out.dt.tz_convert("UTC").dt.tz_localize(None)
        out = out.astype("datetime64[s]")
        return out.dt.normalize() if col.type == "date" else out
    if col.type == "bool":
        if pd.api.types.is_bool_dtype(series):
            return series.astype("boolean")
        if pd.api.types.is_numeric_dtype(series):
            return (series == 1).astype("boolean").mask(series.isna())
        low = series.astype(str).str.strip().str.lower()
        out = pd.Series(pd.NA, index=series.index, dtype="boolean")
        out[low.isin(_TRUE)] = True
        out[low.isin(_FALSE)] = False
        return out
    return series.astype(object).where(series.notna(), None).map(
        lambda v: v if v is None else str(v))


# ---------------------------------------------------------------------------
# the Gaussian copula model
# ---------------------------------------------------------------------------


@dataclass
class _Marginal:
    name: str
    kind: str  # "numeric" or "categorical"
    col: Column
    null_rate: float
    levels: np.ndarray | None = None   # quantile levels (0..1)
    values: np.ndarray | None = None   # quantile values
    categories: list = field(default_factory=list)
    cum_probs: np.ndarray | None = None


@register_model
class GaussianCopulaModel(TabularModel):
    """Empirical marginals + Gaussian copula. Stores only aggregates, never rows."""

    name = "gaussian_copula"

    def __init__(self) -> None:
        self._marginals: list[_Marginal] = []
        self._chol: np.ndarray | None = None
        self.correlation: np.ndarray | None = None

    @property
    def columns(self) -> list[str]:
        return [m.name for m in self._marginals]

    # ----- fitting -----------------------------------------------------------
    def fit(self, data: pd.DataFrame, columns: list[Column], rng: np.random.Generator) -> GaussianCopulaModel:
        if len(data) < 2:
            raise FitError("sample_too_small", "The sample needs at least 2 rows to learn from.")
        scores = []
        self._marginals = []
        for col in columns:
            typed = coerce(data[col.name], col)
            marginal, z = self._fit_column(typed, col, rng)
            if marginal is None:
                continue
            self._marginals.append(marginal)
            scores.append(z)
        if not self._marginals:
            self._chol = np.zeros((0, 0))
            return self
        Z = np.column_stack(scores)
        with np.errstate(invalid="ignore", divide="ignore"):
            R = np.corrcoef(Z, rowvar=False) if Z.shape[1] > 1 else np.ones((1, 1))
        R = np.atleast_2d(np.nan_to_num(R, nan=0.0))
        np.fill_diagonal(R, 1.0)
        R = _nearest_correlation(R)
        self.correlation = R
        self._chol = np.linalg.cholesky(R)
        return self

    def _fit_column(self, typed: pd.Series, col: Column, rng: np.random.Generator):
        n = len(typed)
        null = typed.isna().to_numpy()
        null_rate = float(null.mean())
        if col.type in ("int", "float", "date", "datetime"):
            numeric = _to_float(typed)
            observed = numeric[~null]
            if len(observed) == 0:
                return None, None
            tail = T.FIT_TAIL_QUANTILE
            levels = np.linspace(tail, 1 - tail, 199)
            values = np.quantile(observed, levels)
            # Extend slightly past the tails (no exact extremes are stored).
            lo_ext = values[0] - (values[1] - values[0])
            hi_ext = values[-1] + (values[-1] - values[-2])
            if observed.min() >= 0:
                lo_ext = max(lo_ext, 0.0)
            levels = np.concatenate([[0.0], levels, [1.0]])
            values = np.concatenate([[lo_ext], values, [hi_ext]])
            marginal = _Marginal(col.name, "numeric", col, null_rate, levels=levels, values=values)
            ranks = stats.rankdata(numeric[~null]) / (len(observed) + 1)
            u = rng.random(n)
            u[~null] = ranks
        else:
            values_s = typed[~null].astype(object)
            counts = values_s.value_counts()
            counts = counts[counts >= T.FIT_MIN_CATEGORY_COUNT]
            if counts.empty:
                return None, None
            # Deterministic order: most frequent first, ties by text value.
            frame = pd.DataFrame({"value": counts.index.astype(object), "count": counts.to_numpy()})
            frame["key"] = frame["value"].map(str)
            frame = frame.sort_values(["count", "key"], ascending=[False, True], kind="mergesort")
            cats = frame["value"].tolist()
            probs = frame["count"].to_numpy(dtype=float)
            probs = probs / probs.sum()
            cum = np.concatenate([[0.0], np.cumsum(probs)])
            cum[-1] = 1.0
            marginal = _Marginal(col.name, "categorical", col, null_rate, categories=cats, cum_probs=cum)
            index = {v: i for i, v in enumerate(cats)}
            codes = np.array([index.get(v, -1) for v in typed.astype(object).to_numpy()])
            u = rng.random(n)
            known = codes >= 0
            lo = cum[codes[known]]
            hi = cum[codes[known] + 1]
            u[known] = lo + (hi - lo) * rng.random(int(known.sum()))
        z = stats.norm.ppf(np.clip(u, 1e-6, 1 - 1e-6))
        return marginal, z

    # ----- sampling ------------------------------------------------------------
    def sample(self, n: int, rng: np.random.Generator) -> pd.DataFrame:
        k = len(self._marginals)
        if k == 0:
            return pd.DataFrame(index=range(n))
        assert self._chol is not None
        Z = rng.standard_normal((n, k)) @ self._chol.T
        U = stats.norm.cdf(Z)
        out = {}
        for j, m in enumerate(self._marginals):
            u = U[:, j]
            if m.kind == "numeric":
                assert m.levels is not None and m.values is not None
                raw = np.interp(u, m.levels, m.values)
                series = _from_float(raw, m.col)
            else:
                assert m.cum_probs is not None
                idx = np.clip(np.searchsorted(m.cum_probs, u, side="right") - 1, 0, len(m.categories) - 1)
                arr = np.array(m.categories, dtype=object)[idx]
                series = pd.Series(arr, dtype="boolean") if m.col.type == "bool" else pd.Series(arr, dtype=object)
            if m.null_rate > 0:
                series = series.mask(rng.random(n) < m.null_rate)
            out[m.name] = series
        return pd.DataFrame(out)

    def summary(self) -> dict:
        """Aggregate description of what was learned (no row values)."""
        return {"model": self.name, "columns": self.columns}


def _to_float(typed: pd.Series) -> np.ndarray:
    if pd.api.types.is_datetime64_any_dtype(typed):
        out = np.full(len(typed), np.nan)
        mask = typed.notna().to_numpy()
        out[mask] = typed[mask].astype("int64").to_numpy()
        return out
    return typed.astype("float64").to_numpy(na_value=np.nan)


def _from_float(raw: np.ndarray, col: Column) -> pd.Series:
    if col.type == "int":
        return pd.Series(np.rint(raw).astype(np.int64), dtype="Int64")
    if col.type == "float":
        return pd.Series(np.round(raw, col.decimals if col.decimals is not None else 2), dtype="float64")
    secs = np.rint(raw).astype(np.int64)
    if col.type == "date":
        secs = (secs // 86_400) * 86_400
    return pd.Series(secs.astype("datetime64[s]"))


def _nearest_correlation(R: np.ndarray) -> np.ndarray:
    """Make a correlation matrix positive definite (clip tiny eigenvalues)."""
    vals, vecs = np.linalg.eigh((R + R.T) / 2)
    vals = np.clip(vals, 1e-6, None)
    fixed = vecs @ np.diag(vals) @ vecs.T
    d = np.sqrt(np.diag(fixed))
    fixed = fixed / np.outer(d, d)
    np.fill_diagonal(fixed, 1.0)
    return fixed


# ---------------------------------------------------------------------------
# no-copy filter (FR8)
# ---------------------------------------------------------------------------


class NoCopyFilter:
    """Remembers *hashes* of source rows (not the rows) to spot exact copies."""

    def __init__(self, source: pd.DataFrame, columns: list[Column]):
        self.columns = columns
        self._hashes = np.unique(self._hash(source))

    def _hash(self, df: pd.DataFrame) -> np.ndarray:
        canonical = {}
        for col in self.columns:
            typed = coerce(df[col.name], col)
            if col.type in ("int", "float", "date", "datetime"):
                canonical[col.name] = _to_float(typed)
            else:
                canonical[col.name] = typed.astype(object).map(lambda v: "\x00null" if v is None or v is pd.NA
                                                               else str(v)).to_numpy()
        frame = pd.DataFrame(canonical)
        return pd.util.hash_pandas_object(frame, index=False).to_numpy()

    def matches(self, df: pd.DataFrame) -> np.ndarray:
        """Boolean array: True where the row equals some source row on the modeled columns."""
        if len(df) == 0 or not self.columns:
            return np.zeros(len(df), dtype=bool)
        return np.isin(self._hash(df), self._hashes)


# ---------------------------------------------------------------------------
# high-level: learn a table from a sample
# ---------------------------------------------------------------------------


@dataclass
class FitResult:
    """Everything the engine and the report need after learning a sample."""

    table: Table
    model: GaussianCopulaModel
    detections: dict[str, DetectedColumn]
    train: pd.DataFrame
    holdout: pd.DataFrame
    no_copy: NoCopyFilter
    modeled_columns: list[Column]

    def schema(self) -> Schema:
        return Schema(name=self.table.name, tables=[self.table])

    def detection_summary(self) -> list[dict]:
        """Column → detected type, role and reason (safe to log/return: no values)."""
        return [{"column": name, "type": d.column.type, "role": d.role, "pii": d.column.pii,
                 "reason": d.reason} for name, d in self.detections.items()]


def infer_table(df: pd.DataFrame, table_name: str, pii_columns: tuple[str, ...] | list[str] = ()) -> Table:
    """Infer a table schema from a sample without fitting a model."""
    detections = {c: detect_column(df[c], c, table_name, force_pii=c in pii_columns) for c in df.columns}
    return _table_from_detections(table_name, detections, None)


def _table_from_detections(table_name: str, detections: dict[str, DetectedColumn],
                           model: GaussianCopulaModel | None) -> Table:
    columns = []
    pk = [name for name, d in detections.items() if d.role == ROLE_KEY][:1]
    for name, det in detections.items():
        col = det.column
        if det.role == ROLE_KEY and name not in pk:
            col = col.model_copy(update={"primary_key": False})
        if model is not None and det.role == ROLE_MODELED:
            col = _describe_marginal(col, model)
        columns.append(col)
    return Table(name=table_name, columns=columns, primary_key=pk)


def _describe_marginal(col: Column, model: GaussianCopulaModel) -> Column:
    """Copy learned aggregates (clipped range, categories) into the column spec."""
    for m in model._marginals:
        if m.name != col.name:
            continue
        if m.kind == "numeric" and m.values is not None:
            lo, hi = float(m.values[0]), float(m.values[-1])
            if col.type == "int":
                return col.model_copy(update={"min": int(np.floor(lo)), "max": int(np.ceil(hi))})
            if col.type == "float":
                d = col.decimals if col.decimals is not None else 2
                return col.model_copy(update={"min": float(np.floor(lo * 10**d) / 10**d),
                                              "max": float(np.ceil(hi * 10**d) / 10**d)})
            unit = "D" if col.type == "date" else "s"
            fmt = "%Y-%m-%d" if col.type == "date" else "%Y-%m-%dT%H:%M:%S"
            lo_s = pd.Timestamp(np.datetime64(int(lo), "s")).floor(unit).strftime(fmt)
            hi_s = pd.Timestamp(np.datetime64(int(hi), "s")).ceil(unit).strftime(fmt)
            return col.model_copy(update={"min": lo_s, "max": hi_s})
        if m.kind == "categorical" and col.type == "category":
            return col.model_copy(update={"allowed_values": list(m.categories)})
    return col


def learn_from_sample(df: pd.DataFrame, table_name: str, seed: int = 0,
                      pii_columns: tuple[str, ...] | list[str] = (),
                      rng: np.random.Generator | None = None) -> FitResult:
    """Detect types, split off a holdout, fit the copula and build the no-copy filter.

    The holdout (``HOLDOUT_FRACTION`` of rows) is never shown to the model;
    the privacy report compares synthetic rows against it (DCR, membership
    inference).
    """
    if df.empty or len(df.columns) == 0:
        raise FitError("empty_sample", "The sample has no rows or no columns.")
    rng = rng if rng is not None else np.random.default_rng(seed)
    df = df.reset_index(drop=True)
    detections = {c: detect_column(df[c], str(c), table_name, force_pii=c in pii_columns) for c in df.columns}
    order = rng.permutation(len(df))
    n_hold = int(round(len(df) * T.HOLDOUT_FRACTION)) if len(df) >= 20 else 0
    holdout = df.iloc[order[:n_hold]].reset_index(drop=True)
    train = df.iloc[order[n_hold:]].reset_index(drop=True)
    modeled = [d.column for d in detections.values() if d.role == ROLE_MODELED]
    model = GaussianCopulaModel().fit(train, modeled, rng)
    learned = set(model.columns)
    modeled = [c for c in modeled if c.name in learned]
    for name, det in detections.items():
        if det.role == ROLE_MODELED and name not in learned:
            detections[name] = DetectedColumn(
                det.column.model_copy(update={"type": "string", "pii": True}), ROLE_FRESH,
                "all values too rare to learn safely (generated fresh)")
    table = _table_from_detections(table_name, detections, model)
    # Use the final column specs (with learned categories) for coercion.
    modeled = [table.column(c.name) for c in modeled]
    no_copy = NoCopyFilter(df, modeled)
    return FitResult(table=table, model=model, detections=detections, train=train, holdout=holdout,
                     no_copy=no_copy, modeled_columns=modeled)
