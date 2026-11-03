"""FR7: the Fidelity and Privacy Report."""

import json

import numpy as np

from synthetic import pipeline
from synthetic.ddl import parse_ddl
from synthetic.engine.fit import learn_from_sample, read_sample
from synthetic.engine.scenarios import Scenario
from synthetic.report.build import build_report
from synthetic.report.html import render_html
from synthetic.report.privacy import privacy_checks
from synthetic.report.thresholds import MIA_AUC, Threshold


def test_spec_mode_report_fields(ecommerce_sql):
    result = pipeline.run(parse_ddl(ecommerce_sql), rows={"customers": 300, "orders": 3000}, seed=1,
                          scenarios=[Scenario(column="orders.is_fraud", rate=0.02)])
    r = result.report
    for key in ("report_version", "engine_version", "seed", "mode", "overall", "integrity", "fidelity",
                "privacy", "summary"):
        assert key in r
    assert r["mode"] == "spec" and r["privacy"]["applicable"] is False
    assert r["integrity"]["fk_resolved_pct"] == 100.0
    assert r["integrity"]["constraint_violations"]["total"] == 0
    assert 0 <= r["fidelity"]["score"] <= 100 and r["fidelity"]["score"] >= 95
    fraud = next(c for c in r["fidelity"]["columns"] if c["column"] == "orders.is_fraud")
    assert fraud["scenario_rate_observed"] == 0.02
    assert r["overall"]["status"] == "pass"
    assert "no real data was used" in r["summary"]
    json.dumps(r)  # JSON-serialisable
    html = render_html(r)
    assert "<html" in html and "Fidelity" in html


def test_sample_mode_privacy_metrics(sample_csv):
    result = pipeline.run(None, rows={"customers": 2000}, seed=4, sample=read_sample(sample_csv),
                          sample_table="customers")
    r = result.report
    assert r["mode"] == "sample"
    names = {c["name"]: c for c in r["privacy"]["checks"]}
    assert set(names) == {"exact_matches", "dcr_closer_to_train_share", "dcr_ratio", "nndr_ratio",
                          "membership_inference_auc"}
    assert names["exact_matches"]["value"] == 0
    assert 0.35 < names["membership_inference_auc"]["value"] < 0.65
    assert r["privacy"]["status"] in ("pass", "warn")
    assert r["fidelity"]["correlation"]["applicable"]
    assert "legal guarantee" in r["summary"]
    assert r["sample"]["holdout_rows"] == 400


def test_privacy_checks_flag_a_memorising_generator(sample_csv):
    """Red flag test: 'synthetic' data that is the training set plus tiny noise must fail."""
    source = read_sample(sample_csv)
    fit = learn_from_sample(source, "customers", seed=0, rng=np.random.default_rng(0))
    leaky = fit.train.copy()
    leaky["monthly_spend"] = leaky["monthly_spend"] + 0.001
    section = privacy_checks(source, fit.train, fit.holdout, leaky, fit.modeled_columns)
    checks = {c["name"]: c for c in section["checks"]}
    assert checks["membership_inference_auc"]["status"] == "fail"
    assert checks["dcr_ratio"]["status"] == "fail"
    # Known limit (documented): the closer-share check subsamples train to the holdout size,
    # which dilutes it for full copies, so it only reaches "warn" here.
    assert checks["dcr_closer_to_train_share"]["status"] in ("warn", "fail")
    assert section["status"] == "fail"


def test_threshold_semantics():
    assert MIA_AUC.status(0.5) == "pass" and MIA_AUC.status(0.65) == "warn" and MIA_AUC.status(0.9) == "fail"
    t = Threshold("x", True, 80, 60, "")
    assert (t.status(90), t.status(70), t.status(10), t.status(None)) == ("pass", "warn", "fail", "warn")


def test_report_counts_violations(ecommerce_sql):
    schema = parse_ddl(ecommerce_sql)
    tables = pipeline.run(schema, rows={"customers": 50}, seed=0, with_report=False).tables
    tables["orders"].loc[0, "customer_id"] = 999_999  # break one foreign key
    tables["products"].loc[0, "price"] = -1.0          # break one range check
    r = build_report(schema, tables, {"seed": 0})
    assert r["integrity"]["status"] == "fail"
    assert r["integrity"]["fk_resolved_pct"] < 100
    assert r["integrity"]["constraint_violations"]["total"] >= 1
