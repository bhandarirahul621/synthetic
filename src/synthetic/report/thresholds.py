"""All pass / warn / fail thresholds and privacy knobs, in one place.

.. warning::
   **Provisional values.** The privacy thresholds below are engineering
   placeholders chosen to be conservative. Per the team's roles, privacy
   thresholds are owned by ``privacy-compliance-expert`` and must be reviewed
   and signed off before any customer relies on them. Changing a value here
   changes every report, so record the reason in the changelog.

How to read a threshold: each :class:`Threshold` says which direction is
good (``higher_is_better``), the value needed to **pass**, and the value
below which (or above which) it is a **fail**. Anything in between is a
**warn**: "look at this before you share the data".
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Threshold:
    """One rule that turns a measured number into pass / warn / fail."""

    name: str
    higher_is_better: bool
    pass_at: float
    fail_at: float
    explanation: str

    def status(self, value: float | None) -> str:
        """Return ``"pass"``, ``"warn"`` or ``"fail"`` for ``value`` (``None`` → ``"warn"``)."""
        if value is None:
            return "warn"
        if self.higher_is_better:
            if value >= self.pass_at:
                return "pass"
            return "fail" if value < self.fail_at else "warn"
        if value <= self.pass_at:
            return "pass"
        return "fail" if value > self.fail_at else "warn"

    def describe(self) -> dict:
        return {"pass": self.pass_at, "fail": self.fail_at,
                "direction": "higher is better" if self.higher_is_better else "lower is better"}


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------

FK_RESOLVED_PCT = Threshold(
    "fk_resolved_pct", True, 100.0, 100.0,
    "Share of foreign-key values that point at an existing parent row. Anything below 100% "
    "means some joins would silently drop rows, so it is a fail (FR4).",
)
"""Foreign keys must resolve 100% of the time (FR4)."""

CONSTRAINT_VIOLATIONS = Threshold(
    "constraint_violations", False, 0, 0,
    "Number of rows that break a declared rule (not null, unique, range, allowed values, "
    "row checks). Any violation is a fail (FR4).",
)
"""Declared constraints must hold on every row (FR4)."""

# ---------------------------------------------------------------------------
# Fidelity
# ---------------------------------------------------------------------------

FIDELITY_SCORE = Threshold(
    "fidelity_score", True, 80.0, 60.0,
    "Overall 0-100 similarity between the synthetic data and the source (or the schema spec). "
    "80+ means distributions and relationships match closely; below 60 means the data may "
    "mislead analyses or models trained on it.",
)
"""Overall fidelity: pass at 80, fail below 60 (PRD §10.2 targets a median of 85)."""

# ---------------------------------------------------------------------------
# Privacy (only when a sample was used)
# ---------------------------------------------------------------------------

EXACT_MATCHES = Threshold(
    "exact_matches", False, 0, 0,
    "Number of synthetic rows identical to a real source row (on the learned columns). "
    "Must be zero (FR8).",
)
"""No synthetic row may equal a source row (FR8)."""

DCR_CLOSER_SHARE = Threshold(
    "dcr_closer_to_train_share", False, 0.55, 0.65,
    "Distance to closest record (DCR): for each synthetic row we find its nearest real "
    "training row and its nearest real holdout row (rows the model never saw). If the "
    "generator did not memorise, a synthetic row is equally likely to be closer to either, "
    "so this share should be about 0.5. Higher means synthetic rows hug the training data.",
)
"""Share of synthetic rows closer to training rows than to holdout rows. ~0.5 is ideal."""

DCR_RATIO = Threshold(
    "dcr_ratio", True, 0.8, 0.5,
    "Median distance from synthetic rows to their closest training row, divided by the same "
    "median for real holdout rows. Around 1 means synthetic rows are no closer to real people "
    "than a new real person would be; much lower suggests near-copies.",
)
"""Median DCR(synthetic) / median DCR(holdout); about 1 is ideal."""

NNDR_RATIO = Threshold(
    "nndr_ratio", True, 0.8, 0.5,
    "Nearest-neighbour distance ratio: distance to the closest real row divided by distance "
    "to the second closest. A very low value means a synthetic row sits right on top of one "
    "specific real row (an outlier copy). We compare the synthetic median to the holdout median.",
)
"""Median NNDR(synthetic) / median NNDR(holdout); about 1 is ideal."""

MIA_AUC = Threshold(
    "membership_inference_auc", False, 0.60, 0.70,
    "A simple membership-inference attack: an attacker who sees the synthetic data guesses "
    "whether a real person was in the training data by how close their record is to a "
    "synthetic row. AUC 0.5 means the attacker does no better than a coin flip; 1.0 means "
    "they always win.",
)
"""Distance-based membership-inference attack AUC; 0.5 is ideal."""

# ---------------------------------------------------------------------------
# Privacy knobs used while fitting (sample learning)
# ---------------------------------------------------------------------------

HOLDOUT_FRACTION = 0.2
"""Share of the sample kept aside (never fitted) so privacy checks have a fair baseline."""

FIT_TAIL_QUANTILE = 0.005
"""Quantile tables start at 0.5% and end at 99.5%, so exact real extremes are not stored."""

FIT_MIN_CATEGORY_COUNT = 5
"""A category must appear at least this many times to be learned; rarer values could identify someone."""

FIT_MAX_CATEGORIES = 50
"""Text columns with more distinct values than this are treated as free text, not categories."""

PRIVACY_MAX_ROWS = 5000
"""Distance checks use at most this many rows per side (random subset) to bound cost."""
