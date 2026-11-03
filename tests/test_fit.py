"""FR3 (type detection, copula fit) and FR8 (no source-row copying)."""

import numpy as np
import pandas as pd

from synthetic import pipeline
from synthetic.engine.fit import NoCopyFilter, detect_column, learn_from_sample, read_sample

EXPECTED_TYPES = {
    "customer_id": "int", "full_name": "name", "email": "email", "city": "address", "age": "int",
    "annual_income": "int", "plan": "category", "monthly_spend": "float", "tenure_months": "int",
    "signup_date": "date", "churned": "bool",
}


def test_type_detection_on_sample(sample_csv):
    fit = learn_from_sample(read_sample(sample_csv), "customers", seed=0)
    detected = {d["column"]: d["type"] for d in fit.detection_summary()}
    correct = sum(detected[c] == t for c, t in EXPECTED_TYPES.items())
    assert correct / len(EXPECTED_TYPES) >= 0.95, detected
    roles = {d["column"]: d["role"] for d in fit.detection_summary()}
    assert roles["full_name"] == roles["email"] == "fresh"
    assert roles["customer_id"] == "primary_key"


def test_value_based_detection():
    n = 200
    rng = np.random.default_rng(0)
    assert detect_column(pd.Series([f"u{i}@corp.test" for i in range(n)]), "contact").column.type == "email"
    assert detect_column(pd.Series(["yes", "no"] * 50), "x").column.type == "bool"
    assert detect_column(pd.Series(pd.date_range("2020-01-01", periods=n, freq="h").astype(str)), "x").column.type \
        == "datetime"
    text = pd.Series([" ".join(rng.choice(["alpha", "beta", "gamma", "delta"], 6)) + str(i) for i in range(n)])
    assert detect_column(text, "x").role == "fresh"


def test_fit_keeps_distributions_and_correlations(sample_csv):
    source = read_sample(sample_csv)
    result = pipeline.run(None, rows={"customers": 4000}, seed=1, sample=source, sample_table="customers")
    synth = result.tables["customers"]
    real_corr = source["annual_income"].corr(source["monthly_spend"])
    syn_corr = synth["annual_income"].astype(float).corr(synth["monthly_spend"])
    assert abs(real_corr - syn_corr) < 0.1
    assert result.report["fidelity"]["score"] >= 85


def test_pii_columns_are_never_copied(sample_csv):
    source = read_sample(sample_csv)
    # Distinctive values: if any reached the output, the column was copied or learned.
    source["full_name"] = [f"Zyxw Person{i}" for i in range(len(source))]
    source["email"] = [f"zyxw.{i}@source.invalid" for i in range(len(source))]
    result = pipeline.run(None, rows={"customers": 2000}, seed=2, sample=source, sample_table="customers",
                          pii_columns=["city"])
    synth = result.tables["customers"]
    assert not set(synth["email"]) & set(source["email"])
    assert not set(synth["full_name"]) & set(source["full_name"])
    assert not synth["full_name"].str.contains("Zyxw").any()
    assert {"full_name", "email", "city"}.isdisjoint(result.fit.model.columns)
    assert result.fit.detections["city"].role == "fresh"


def test_fr8_zero_exact_copies_even_in_a_tiny_value_space():
    # Only 2 x 3 x 2 = 12 possible rows: random sampling would copy source rows all the time.
    rng = np.random.default_rng(0)
    n = 600
    source = pd.DataFrame({"a": rng.integers(0, 2, n), "b": rng.choice(["x", "y", "z"], n),
                           "c": rng.choice([True, False], n)})
    source = source.iloc[: n // 2]  # the source covers only some combinations
    seen = set(map(tuple, source.astype(str).to_numpy()))
    result = pipeline.run(None, rows={"t": 1000}, seed=3, sample=source, sample_table="t")
    synth = result.tables["t"]
    filt = NoCopyFilter(source, result.fit.modeled_columns)
    assert int(filt.matches(synth).sum()) == 0
    assert result.report["privacy"]["checks"][0]["value"] == 0
    assert all(tuple(r) not in seen for r in synth[["a", "b", "c"]].astype(str).to_numpy()) or len(synth) == 0


def test_fr8_zero_copies_on_realistic_sample(sample_csv):
    source = read_sample(sample_csv)
    for seed in (0, 1, 2):
        result = pipeline.run(None, rows={"customers": 3000}, seed=seed, sample=source, sample_table="customers")
        exact = next(c for c in result.report["privacy"]["checks"] if c["name"] == "exact_matches")
        assert exact["value"] == 0
