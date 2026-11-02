"""Create examples/sample_customers.csv: a small, entirely fake sample for fit/report tests.

No real people are involved: names and emails come from Faker word pools via
our own generators, and the numbers come from a seeded random generator with
built-in correlations (older customers earn more and spend more), so the
Gaussian copula has something real to learn.

Run:  .venv/bin/python scripts/make_sample_csv.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from synthetic.engine.generators import gen_address, gen_email, gen_name
from synthetic.schema import Column, Table

OUT = Path(__file__).resolve().parent.parent / "examples" / "sample_customers.csv"


def build(n: int = 2000, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    table = Table(name="customers", columns=[Column(name="x")])
    age = np.clip(rng.normal(41, 12, n), 18, 85).round().astype(int)
    income = np.round(np.exp(10.2 + 0.012 * (age - 40) + rng.normal(0, 0.35, n)), -2)
    tenure = np.clip(rng.gamma(2.0, 14, n) + (age - 18) * 0.3, 0, 240).round().astype(int)
    plan_p = 1 / (1 + np.exp(-(np.log(income) - 10.3) * 3))
    plan = np.where(rng.random(n) < plan_p * 0.6, "premium", np.where(rng.random(n) < 0.5, "standard", "basic"))
    spend = np.round(20 + income / 1500 + np.where(plan == "premium", 40, 0) + rng.normal(0, 8, n), 2)
    spend = np.clip(spend, 5, None)
    churn_p = 1 / (1 + np.exp(0.04 * tenure - 0.5))
    churned = rng.random(n) < churn_p * 0.5
    signup = pd.Timestamp("2026-10-01") - pd.to_timedelta(tenure * 30 + rng.integers(0, 30, n), unit="D")
    df = pd.DataFrame({
        "customer_id": np.arange(1, n + 1),
        "full_name": gen_name(Column(name="full_name", type="name"), table, n, rng),
        "email": gen_email(Column(name="email", type="email", unique=True), table, n, rng),
        "city": gen_address(Column(name="city", type="address", subtype="city"), table, n, rng),
        "age": age,
        "annual_income": income,
        "plan": plan,
        "monthly_spend": spend,
        "tenure_months": tenure,
        "signup_date": signup.strftime("%Y-%m-%d"),
        "churned": churned,
    })
    # A few missing values, like real exports have.
    df.loc[rng.random(n) < 0.03, "annual_income"] = np.nan
    return df


if __name__ == "__main__":
    build().to_csv(OUT, index=False, lineterminator="\n")
    print(f"wrote {OUT}")
