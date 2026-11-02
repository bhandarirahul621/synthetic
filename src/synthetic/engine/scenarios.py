"""Scenarios: deliberate edits to make rare situations common enough to test.

A ``rare_event`` scenario sets an exact share of rows to a value, e.g. "2% of
orders are fraud" (``orders.is_fraud`` = true for exactly 2% of rows). Exact
counts (not coin flips) make tests stable: 50,000 orders always contain
exactly 1,000 fraud rows.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from synthetic.errors import SchemaError
from synthetic.schema import Scalar, Schema


class Scenario(BaseModel):
    """One scenario, as in PRD §9.1.4: ``{"type": "rare_event", "column": "orders.is_fraud", "rate": 0.02}``."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["rare_event"] = "rare_event"
    column: str = Field(description="'table.column' to set")
    rate: float = Field(ge=0.0, le=1.0)
    value: Scalar | None = Field(default=None, description="Value to set; defaults to true for bool columns.")

    def target(self) -> tuple[str, str]:
        if "." not in self.column:
            raise SchemaError("invalid_scenario", f"Scenario column '{self.column}' must be 'table.column'.",
                              param="scenarios")
        table, column = self.column.split(".", 1)
        return table, column


def validate_scenarios(schema: Schema, scenarios: list[Scenario]) -> None:
    """Raise :class:`SchemaError` if a scenario points at a missing or unsuitable column."""
    for sc in scenarios:
        table_name, col_name = sc.target()
        try:
            col = schema.table(table_name).column(col_name)
        except KeyError:
            raise SchemaError("invalid_scenario", f"Scenario column '{sc.column}' is not in the schema.",
                              param="scenarios") from None
        if col.type == "bool":
            continue
        if col.type in ("category", "string") and sc.value is not None:
            if col.allowed_values is not None and sc.value not in col.allowed_values:
                raise SchemaError("invalid_scenario",
                                  f"Scenario value for '{sc.column}' is not one of its allowed values.",
                                  param="scenarios")
            continue
        raise SchemaError(
            "invalid_scenario",
            f"rare_event needs a bool column, or a category column plus a 'value'; '{sc.column}' is {col.type}.",
            param="scenarios",
        )


def apply_rare_event(df: pd.DataFrame, column: str, sc: Scenario, col_type: str,
                     allowed: list | None, weights: list | None, rng: np.random.Generator) -> pd.DataFrame:
    """Set exactly ``round(rate * rows)`` rows of ``column`` to the scenario value."""
    n = len(df)
    k = int(round(sc.rate * n))
    chosen = np.zeros(n, dtype=bool)
    if k:
        chosen[rng.choice(n, size=k, replace=False)] = True
    if col_type == "bool":
        value = True if sc.value is None else bool(sc.value)
        df[column] = pd.Series(np.where(chosen, value, not value), dtype="boolean")
        return df
    values = df[column].to_numpy(dtype=object).copy()
    values[chosen] = sc.value
    # Rows not chosen must not carry the value either, or the rate would drift.
    others = [v for v in (allowed or []) if v != sc.value]
    leftover = (~chosen) & (values == sc.value)
    if leftover.any():
        if not others:
            raise SchemaError("invalid_scenario",
                              f"Column '{column}' has no other values to use besides the scenario value.",
                              param="scenarios")
        p = None
        if weights is not None and allowed is not None:
            w = np.array([wt for v, wt in zip(allowed, weights, strict=True) if v != sc.value], dtype=float)
            p = w / w.sum() if w.sum() > 0 else None
        values[leftover] = np.array(others, dtype=object)[rng.choice(len(others), size=int(leftover.sum()), p=p)]
    df[column] = values
    return df
