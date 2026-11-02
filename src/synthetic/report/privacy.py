"""Privacy checks, run only when a real sample was used.

Plain-language versions of each check:

* **Exact matches.** Did any synthetic row come out identical to a real row?
  Must be zero (FR8).
* **Distance to closest record (DCR).** For each synthetic row, how far is
  the nearest real row? We compare against a fair baseline: real *holdout*
  rows the model never saw. If synthetic rows are much closer to training
  rows than holdout rows are, the model may have memorised people.
* **Nearest-neighbour distance ratio (NNDR).** Closest distance divided by
  second-closest. Near 0 means a synthetic row sits on top of one specific
  real row: an outlier that has effectively been copied.
* **Membership inference attack (MIA).** We play attacker: for each real
  person, guess "they were in the training data" if a synthetic row is very
  close to their record. AUC 0.5 = the attacker is guessing; higher = leak.

How distances are measured: numbers (and dates) are scaled to 0..1 using
the training data's range, and categories are one-hot encoded (a different
category adds the same distance as a full-range numeric difference).

Known limits (documented for the red-team review): these are distance-based
heuristics on the learned columns only; they do not prove anonymity, do not
model attackers with auxiliary data about quasi-identifiers, and use a random
subset of at most ``PRIVACY_MAX_ROWS`` rows per side.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats
from scipy.spatial import cKDTree

from synthetic.engine.fit import NoCopyFilter, _to_float, coerce
from synthetic.report import thresholds as T
from synthetic.schema import ORDERED_TYPES, Column


class _Encoder:
    """Scale numbers to 0..1 and one-hot categories, using the training data only."""

    def __init__(self, train: pd.DataFrame, columns: list[Column]):
        self.columns = columns
        self.params: dict[str, Any] = {}
        for col in columns:
            typed = coerce(train[col.name], col)
            if col.type in ORDERED_TYPES:
                values = _to_float(typed)
                values = values[~np.isnan(values)]
                lo, hi = (float(values.min()), float(values.max())) if len(values) else (0.0, 1.0)
                median = float(np.median(values)) if len(values) else 0.0
                self.params[col.name] = ("num", lo, max(hi - lo, 1e-12), median)
            else:
                cats = typed.dropna().astype(str).value_counts().index[: T.FIT_MAX_CATEGORIES].tolist()
                self.params[col.name] = ("cat", sorted(cats))

    def transform(self, df: pd.DataFrame) -> np.ndarray:
        blocks = []
        for col in self.columns:
            typed = coerce(df[col.name], col)
            spec = self.params[col.name]
            if spec[0] == "num":
                _, lo, width, median = spec
                values = _to_float(typed)
                missing = np.isnan(values)
                values = np.where(missing, median, values)
                blocks.append(np.clip((values - lo) / width, -1, 2)[:, None])
                blocks.append(missing.astype(float)[:, None])
            else:
                cats = spec[1]
                text = typed.astype(object).where(typed.notna(), "\x00null").astype(str).to_numpy()
                onehot = np.zeros((len(df), len(cats) + 1))
                index = {c: i for i, c in enumerate(cats)}
                for row, value in enumerate(text):
                    onehot[row, index.get(value, len(cats))] = 1.0
                blocks.append(onehot / np.sqrt(2))
        return np.hstack(blocks) if blocks else np.zeros((len(df), 0))


def _subset(df: pd.DataFrame, n: int, rng: np.random.Generator) -> pd.DataFrame:
    if len(df) <= n:
        return df.reset_index(drop=True)
    return df.iloc[np.sort(rng.choice(len(df), size=n, replace=False))].reset_index(drop=True)


def _check(threshold: T.Threshold, value: float | None, **extra: Any) -> dict[str, Any]:
    return {"name": threshold.name, "value": None if value is None else round(float(value), 4),
            "status": threshold.status(value), "threshold": threshold.describe(),
            "explanation": threshold.explanation, **extra}


def _nndr(d: np.ndarray) -> np.ndarray:
    d1, d2 = d[:, 0], d[:, 1]
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(d2 > 0, d1 / d2, 1.0)
    return ratio


def privacy_checks(source: pd.DataFrame, train: pd.DataFrame, holdout: pd.DataFrame,
                   synthetic: pd.DataFrame, columns: list[Column], seed: int = 0) -> dict[str, Any]:
    """Run all privacy checks on the learned columns and return a report section."""
    rng = np.random.default_rng([seed, 2026])  # separate stream: never affects the data itself
    checks = []
    exact = int(NoCopyFilter(source, columns).matches(synthetic).sum()) if columns else 0
    checks.append(_check(T.EXACT_MATCHES, exact))

    if not columns or len(holdout) < 5 or len(train) < 5 or len(synthetic) < 5:
        return {"applicable": True, "status": _worst([c["status"] for c in checks] + ["warn"]),
                "checks": checks,
                "note": "The sample is too small for distance-based checks (need at least 25 rows)."}

    cap = T.PRIVACY_MAX_ROWS
    enc = _Encoder(train, columns)
    syn = enc.transform(_subset(synthetic, cap, rng))
    hold_df = _subset(holdout, cap, rng)
    hold = enc.transform(hold_df)
    tr = enc.transform(_subset(train, cap, rng))
    # A training subset the same size as the holdout keeps the DCR share fair (~0.5).
    tr_equal = enc.transform(_subset(train, len(hold_df), rng))

    train_tree = cKDTree(tr)
    syn_d = train_tree.query(syn, k=2)[0]
    hold_d = train_tree.query(hold, k=2)[0]

    d_to_train = cKDTree(tr_equal).query(syn, k=1)[0]
    d_to_hold = cKDTree(hold).query(syn, k=1)[0]
    share = float(np.mean(d_to_train < d_to_hold) + 0.5 * np.mean(d_to_train == d_to_hold))
    checks.append(_check(T.DCR_CLOSER_SHARE, share))

    med_syn, med_hold = float(np.median(syn_d[:, 0])), float(np.median(hold_d[:, 0]))
    dcr_ratio = 1.0 if med_hold == 0 and med_syn == 0 else (med_syn / med_hold if med_hold > 0 else 10.0)
    checks.append(_check(T.DCR_RATIO, dcr_ratio, synthetic_median_dcr=round(med_syn, 5),
                         holdout_median_dcr=round(med_hold, 5),
                         synthetic_p5_dcr=round(float(np.percentile(syn_d[:, 0], 5)), 5)))

    nn_syn, nn_hold = float(np.median(_nndr(syn_d))), float(np.median(_nndr(hold_d)))
    nndr_ratio = 1.0 if nn_hold == 0 else nn_syn / nn_hold
    checks.append(_check(T.NNDR_RATIO, nndr_ratio, synthetic_median_nndr=round(nn_syn, 4),
                         holdout_median_nndr=round(nn_hold, 4)))

    syn_tree = cKDTree(syn)
    member_scores = -syn_tree.query(tr_equal, k=1)[0]
    non_member_scores = -syn_tree.query(hold, k=1)[0]
    u = stats.mannwhitneyu(member_scores, non_member_scores, alternative="two-sided").statistic
    auc = float(u / (len(member_scores) * len(non_member_scores)))
    checks.append(_check(T.MIA_AUC, auc, members=len(member_scores), non_members=len(non_member_scores)))

    return {"applicable": True, "status": _worst([c["status"] for c in checks]), "checks": checks,
            "rows_compared": {"synthetic": len(syn), "train": len(tr), "holdout": len(hold)},
            "columns_compared": [c.name for c in columns]}


def _worst(statuses: list[str]) -> str:
    for s in ("fail", "warn"):
        if s in statuses:
            return s
    return "pass"
