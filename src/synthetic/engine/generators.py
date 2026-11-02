"""Per-type value generators: one function per column type.

Each generator takes a column definition, a row count and the shared random
generator, and returns a pandas Series with *no nulls* (nulls are added later
by :func:`apply_nulls`). Everything is vectorised with numpy, so a million
rows take seconds, not minutes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from synthetic.engine import pools
from synthetic.engine.constraints import DAY, numeric_bounds
from synthetic.errors import ConstraintError
from synthetic.schema import Column, Table

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _bounded(sampler, n: int, lo: float, hi: float, rng: np.random.Generator) -> np.ndarray:
    """Draw from ``sampler`` and redraw anything outside [lo, hi] (then clip)."""
    values = sampler(n)
    for _ in range(5):
        bad = (values < lo) | (values > hi)
        if not bad.any():
            break
        values[bad] = sampler(int(bad.sum()))
    return np.clip(values, lo, hi)


def _continuous(col: Column, n: int, lo: float, hi: float, rng: np.random.Generator) -> np.ndarray:
    """Sample a continuous distribution inside [lo, hi]."""
    dist = col.distribution or "uniform"
    if hi <= lo:
        return np.full(n, lo, dtype=float)
    if dist == "normal":
        mean = col.mean if col.mean is not None else (lo + hi) / 2
        std = col.std if col.std is not None else (hi - lo) / 6
        return _bounded(lambda k: rng.normal(mean, std, k), n, lo, hi, rng)
    if dist == "lognormal":
        median = col.mean if col.mean is not None else min(max(lo, 1.0) * 50, (lo + hi) / 2)
        sigma = 1.0 if col.std is None else float(np.sqrt(np.log1p((col.std / median) ** 2)))
        mu = np.log(max(median, 1e-9))
        return _bounded(lambda k: rng.lognormal(mu, sigma, k), n, lo, hi, rng)
    if dist == "exponential":
        scale = col.mean if col.mean is not None else (hi - lo) / 5
        return _bounded(lambda k: lo + rng.exponential(scale, k), n, lo, hi, rng)
    return rng.uniform(lo, hi, n)


def _unique_integers(lo: int, hi: int, n: int, rng: np.random.Generator, what: str) -> np.ndarray:
    size = hi - lo + 1
    if size < n:
        raise ConstraintError(
            "unique_range_too_small",
            f"Column '{what}' must be unique, but its range only has {size} values for {n} rows. "
            "Widen its min/max or generate fewer rows.",
            param=what,
        )
    return rng.choice(size, size=n, replace=False).astype(np.int64) + lo


# ---------------------------------------------------------------------------
# type generators
# ---------------------------------------------------------------------------


def gen_int(col: Column, table: Table, n: int, rng: np.random.Generator) -> pd.Series:
    lo, hi = numeric_bounds(col, table)
    if col.primary_key and len(table.primary_key) == 1:
        start = int(lo) if col.min is not None else 1
        return pd.Series(np.arange(start, start + n, dtype=np.int64), dtype="Int64")
    if col.unique:
        return pd.Series(_unique_integers(int(lo), int(hi), n, rng, col.name), dtype="Int64")
    if col.distribution in (None, "uniform"):
        values = rng.integers(int(lo), int(hi), size=n, endpoint=True)
    else:
        values = np.rint(_continuous(col, n, lo, hi, rng)).astype(np.int64)
    return pd.Series(values, dtype="Int64")


def gen_float(col: Column, table: Table, n: int, rng: np.random.Generator) -> pd.Series:
    lo, hi = numeric_bounds(col, table)
    decimals = col.decimals if col.decimals is not None else 2
    values = np.round(_continuous(col, n, lo, hi, rng), decimals)
    values = np.clip(values, lo, hi)
    if col.unique:
        values = _fix_duplicates(values, lambda k: np.round(_continuous(col, k, lo, hi, rng), decimals),
                                 col.name)
    return pd.Series(values, dtype="float64")


def gen_bool(col: Column, table: Table, n: int, rng: np.random.Generator) -> pd.Series:
    p = 0.5 if col.p_true is None else col.p_true
    return pd.Series(rng.random(n) < p, dtype="boolean")


def gen_category(col: Column, table: Table, n: int, rng: np.random.Generator) -> pd.Series:
    values = col.allowed_values or [f"{col.name}_{i}" for i in range(1, 5)]
    arr = np.array(values, dtype=object)
    if col.unique:
        if len(arr) < n:
            raise ConstraintError(
                "unique_range_too_small",
                f"Column '{col.name}' must be unique but has only {len(arr)} allowed values "
                f"for {n} rows.",
                param=col.name,
            )
        return pd.Series(arr[rng.permutation(len(arr))[:n]], dtype=object)
    p = None
    if col.weights is not None:
        w = np.asarray(col.weights, dtype=float)
        p = w / w.sum()
    return pd.Series(arr[rng.choice(len(arr), size=n, p=p)], dtype=object)


def gen_temporal(col: Column, table: Table, n: int, rng: np.random.Generator) -> pd.Series:
    lo, hi = numeric_bounds(col, table)
    if col.type == "date":
        lo_d, hi_d = int(lo // DAY), int(hi // DAY)
        if col.unique:
            days = _unique_integers(lo_d, hi_d, n, rng, col.name)
        elif col.distribution in (None, "uniform"):
            days = rng.integers(lo_d, hi_d, size=n, endpoint=True)
        else:
            days = np.floor(_continuous(col, n, lo_d, hi_d, rng)).astype(np.int64)
        seconds = days * DAY
    else:
        if col.unique:
            seconds = _unique_integers(int(lo), int(hi), n, rng, col.name)
        elif col.distribution in (None, "uniform"):
            seconds = rng.integers(int(lo), int(hi), size=n, endpoint=True)
        else:
            seconds = np.floor(_continuous(col, n, lo, hi, rng)).astype(np.int64)
    return pd.Series(np.asarray(seconds, dtype="int64").astype("datetime64[s]"))


def gen_uuid(col: Column, table: Table, n: int, rng: np.random.Generator) -> pd.Series:
    raw = rng.integers(0, 256, size=(n, 16), dtype=np.uint8)
    raw[:, 6] = (raw[:, 6] & 0x0F) | 0x40  # version 4
    raw[:, 8] = (raw[:, 8] & 0x3F) | 0x80  # RFC 4122 variant
    hexed = [row.tobytes().hex() for row in raw]
    return pd.Series([f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}" for h in hexed], dtype=object)


def _pick(pool: np.ndarray, n: int, rng: np.random.Generator) -> np.ndarray:
    return pool[rng.integers(0, len(pool), size=n)]


def _digits(n: int, k: int, rng: np.random.Generator) -> np.ndarray:
    """``n`` zero-padded random strings of ``k`` digits."""
    nums = rng.integers(0, 10**k, size=n)
    return np.char.zfill(nums.astype(str), k).astype(object)


def gen_name(col: Column, table: Table, n: int, rng: np.random.Generator) -> pd.Series:
    sub = col.subtype or "full"
    first = pools.make_pool("first", rng)
    last = pools.make_pool("last", rng)
    if sub == "first":
        values = _pick(first, n, rng)
    elif sub == "last":
        values = _pick(last, n, rng)
    else:
        values = _pick(first, n, rng) + " " + _pick(last, n, rng)
    return pd.Series(values, dtype=object)


def gen_email(col: Column, table: Table, n: int, rng: np.random.Generator) -> pd.Series:
    first = np.char.lower(pools.make_pool("first", rng).astype(str)).astype(object)
    last = np.char.lower(pools.make_pool("last", rng).astype(str)).astype(object)
    sep = np.array([".", "_", ""], dtype=object)[rng.integers(0, 3, size=n)]
    if col.unique:
        # A permuted counter guarantees uniqueness without a retry loop.
        suffix = (rng.permutation(n) + 1).astype(str).astype(object)
    else:
        suffix = rng.integers(1, 1000, size=n).astype(str).astype(object)
    domain = _pick(pools.EMAIL_DOMAINS, n, rng)
    values = _pick(first, n, rng) + sep + _pick(last, n, rng) + suffix + "@" + domain
    return pd.Series(values, dtype=object)


def emails_from_names(first: pd.Series, last: pd.Series, unique: bool,
                      rng: np.random.Generator) -> pd.Series:
    """Build emails from the row's own first/last names, so they look consistent."""
    n = len(first)

    def clean(series: pd.Series) -> pd.Series:
        return series.astype(str).str.lower().str.replace(r"[^a-z0-9]", "", regex=True)

    sep = np.array([".", "_", ""], dtype=object)[rng.integers(0, 3, size=n)]
    if unique:
        suffix = (rng.permutation(n) + 1).astype(str).astype(object)
    else:
        suffix = rng.integers(1, 1000, size=n).astype(str).astype(object)
    domain = _pick(pools.EMAIL_DOMAINS, n, rng)
    values = clean(first).to_numpy(dtype=object) + sep + clean(last).to_numpy(dtype=object) + suffix + "@" + domain
    return pd.Series(values, dtype=object)


def gen_phone(col: Column, table: Table, n: int, rng: np.random.Generator) -> pd.Series:
    # 555 exchanges are reserved for fiction in North America, which lowers the
    # chance of producing a real person's number.
    area = rng.integers(201, 990, size=n).astype(str).astype(object)
    values = "+1-" + area + "-555-" + _digits(n, 4, rng)
    return pd.Series(values, dtype=object)


def gen_address(col: Column, table: Table, n: int, rng: np.random.Generator) -> pd.Series:
    sub = col.subtype or "full"
    if sub == "city":
        return pd.Series(_pick(pools.make_pool("city", rng), n, rng), dtype=object)
    if sub == "state":
        return pd.Series(_pick(pools.make_pool("state", rng), n, rng), dtype=object)
    if sub == "zip":
        return pd.Series(_digits(n, 5, rng), dtype=object)
    if sub == "country":
        countries = np.array(["United States", "Canada", "United Kingdom", "Germany", "France",
                              "India", "Australia", "Mexico", "Brazil", "Japan"], dtype=object)
        weights = np.array([40, 10, 10, 8, 7, 8, 5, 5, 4, 3], dtype=float)
        return pd.Series(countries[rng.choice(len(countries), size=n, p=weights / weights.sum())],
                         dtype=object)
    streets = pools.make_pool("street_name", rng)
    number = rng.integers(1, 9999, size=n).astype(str).astype(object)
    street = number + " " + _pick(streets, n, rng)
    if sub == "street":
        return pd.Series(street, dtype=object)
    city = _pick(pools.make_pool("city", rng), n, rng)
    state = _pick(pools.make_pool("state", rng), n, rng)
    return pd.Series(street + ", " + city + ", " + state + " " + _digits(n, 5, rng), dtype=object)


def gen_text(col: Column, table: Table, n: int, rng: np.random.Generator) -> pd.Series:
    """Short notes made of random words. (An LLM text filler is planned; see docs.)"""
    words = pools.make_pool("word", rng)
    max_words = 14
    counts = rng.integers(4, max_words + 1, size=n)
    idx = rng.integers(0, len(words), size=(n, max_words))
    chosen = words[idx]
    out = []
    for row, count in zip(chosen, counts, strict=True):
        sentence = " ".join(row[:count])
        out.append(sentence[:1].upper() + sentence[1:] + ".")
    return pd.Series(out, dtype=object)


_ALNUM = np.array(list("ABCDEFGHJKLMNPQRSTUVWXYZ23456789"), dtype=object)


def gen_string(col: Column, table: Table, n: int, rng: np.random.Generator) -> pd.Series:
    sub = col.subtype
    if col.allowed_values:
        return gen_category(col, table, n, rng)
    if sub == "ssn":
        # 9xx area numbers are never issued as real SSNs.
        values = "9" + _digits(n, 2, rng) + "-" + _digits(n, 2, rng) + "-" + _digits(n, 4, rng)
    elif sub == "ipv4":
        # 198.18.0.0/15 is reserved for benchmarking, never a real host.
        values = ("198." + rng.integers(18, 20, size=n).astype(str).astype(object) + "."
                  + rng.integers(0, 256, size=n).astype(str).astype(object) + "."
                  + rng.integers(1, 255, size=n).astype(str).astype(object))
    elif sub == "account_number":
        values = "ACCT" + _digits(n, 10, rng)
    elif sub == "url":
        values = "https://" + _pick(pools.make_pool("word", rng), n, rng) + ".example.com/"
    elif sub == "company":
        values = _pick(pools.make_pool("company", rng), n, rng)
    elif sub == "product":
        values = (_pick(pools.make_pool("adjective", rng), n, rng) + " "
                  + _pick(pools.make_pool("noun", rng), n, rng))
    elif sub == "username":
        values = _pick(pools.make_pool("username", rng), n, rng) + rng.integers(1, 100, size=n).astype(str).astype(object)
    else:
        length = min(col.max_length or 10, 10)
        codes = _ALNUM[rng.integers(0, len(_ALNUM), size=(n, length))]
        values = np.array(["".join(r) for r in codes], dtype=object)
    return pd.Series(np.asarray(values, dtype=object), dtype=object)


GENERATORS = {
    "int": gen_int,
    "float": gen_float,
    "bool": gen_bool,
    "category": gen_category,
    "date": gen_temporal,
    "datetime": gen_temporal,
    "uuid": gen_uuid,
    "email": gen_email,
    "name": gen_name,
    "phone": gen_phone,
    "address": gen_address,
    "text": gen_text,
    "string": gen_string,
}


def _fix_duplicates(values: np.ndarray, regenerate, name: str, rounds: int = 10) -> np.ndarray:
    values = np.asarray(values).copy()
    for _ in range(rounds):
        dup = pd.Series(values).duplicated().to_numpy()
        if not dup.any():
            return values
        values[dup] = regenerate(int(dup.sum()))
    if pd.Series(values).duplicated().any():
        raise ConstraintError(
            "unique_unsatisfiable",
            f"Could not make column '{name}' unique. Widen its range or allowed values.",
            param=name,
        )
    return values


def generate_column(col: Column, table: Table, n: int, rng: np.random.Generator) -> pd.Series:
    """Generate ``n`` non-null values for ``col`` and enforce uniqueness and max length."""
    series = GENERATORS[col.type](col, table, n, rng)
    if col.type in ("string", "text", "name", "email", "phone", "address") and col.max_length:
        series = series.astype(object).str.slice(0, col.max_length)
    if col.unique and col.type not in ("int", "float", "date", "datetime", "category", "email"):
        values = series.to_numpy(dtype=object)
        for _ in range(10):
            dup = pd.Series(values).duplicated().to_numpy()
            if not dup.any():
                break
            values[dup] = GENERATORS[col.type](col, table, int(dup.sum()), rng).to_numpy(dtype=object)
        dup = pd.Series(values).duplicated().to_numpy()
        if dup.any():  # last resort: make the leftovers unique with a counter suffix
            values[dup] = [f"{v}-{i}" for i, v in enumerate(values[dup], start=1)]
        series = pd.Series(values, dtype=object)
    return series.reset_index(drop=True)


def apply_nulls(series: pd.Series, col: Column, rng: np.random.Generator) -> pd.Series:
    """Blank out a ``null_rate`` share of values (only for nullable columns)."""
    if not col.nullable or col.null_rate <= 0 or len(series) == 0:
        return series
    mask = rng.random(len(series)) < col.null_rate
    return series.mask(mask)


