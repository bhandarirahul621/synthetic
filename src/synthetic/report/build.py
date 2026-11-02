"""Assemble the Fidelity and Privacy Report (FR7).

The report has four parts, each with its own pass / warn / fail status:

1. **Integrity**: do foreign keys resolve and do all declared rules hold?
2. **Fidelity**: how close is the data to the source sample (or to the spec)?
3. **Privacy**: only when a sample was used: copies, distances, attacks.
4. **Summary**: a few plain-English sentences a compliance lead can read.

The output is a plain dict (JSON-ready). It contains only aggregate numbers,
column names and table names, never row values (FR15).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from synthetic.engine.constraints import check_foreign_keys, validate_dataset
from synthetic.engine.version import ENGINE_VERSION
from synthetic.report import thresholds as T
from synthetic.report.fidelity import relationship_stats, sample_fidelity, spec_fidelity
from synthetic.report.privacy import privacy_checks
from synthetic.schema import Column, Schema

REPORT_VERSION = "1.0"


def _worst(statuses: list[str]) -> str:
    for s in ("fail", "warn"):
        if s in statuses:
            return s
    return "pass"


def integrity_section(schema: Schema, tables: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """Foreign-key resolution and constraint violations."""
    fks = check_foreign_keys(schema, tables)
    total = sum(f.total for f in fks)
    resolved = sum(f.resolved for f in fks)
    pct = 100.0 if total == 0 else 100.0 * resolved / total
    violations = validate_dataset(schema, tables)
    rule_violations = [v for v in violations if not v.rule.startswith("foreign_key")]
    n_viol = sum(v.count for v in rule_violations)
    status = _worst([T.FK_RESOLVED_PCT.status(pct), T.CONSTRAINT_VIOLATIONS.status(n_viol)])
    return {
        "status": status,
        "foreign_keys": [f.as_dict() for f in fks],
        "fk_resolved_pct": round(pct, 4),
        "constraint_violations": {"total": n_viol, "by_rule": [v.as_dict() for v in rule_violations]},
        "rows": {name: len(df) for name, df in tables.items()},
        "thresholds": {"fk_resolved_pct": T.FK_RESOLVED_PCT.describe(),
                       "constraint_violations": T.CONSTRAINT_VIOLATIONS.describe()},
    }


def build_report(
    schema: Schema,
    tables: dict[str, pd.DataFrame],
    metadata: dict[str, Any] | None = None,
    sample: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the full report.

    Args:
        schema: the schema the data was generated from.
        tables: generated tables by name.
        metadata: generation metadata (seed, rows, scenarios, ...).
        sample: when a sample was used, a dict with ``table`` (name),
            ``source``, ``train`` and ``holdout`` DataFrames and
            ``columns`` (the learned :class:`Column` list).
    """
    metadata = metadata or {}
    integrity = integrity_section(schema, tables)
    scenarios = metadata.get("scenarios") or []
    seed = int(metadata.get("seed", 0))

    if sample is not None:
        table_name = sample["table"]
        columns: list[Column] = sample["columns"]
        synthetic = tables[table_name]
        fidelity = sample_fidelity(sample["source"], synthetic, columns)
        fidelity["table"] = table_name
        others = {k: v for k, v in tables.items() if k != table_name}
        if others:
            fidelity["other_tables"] = spec_fidelity(schema, others, scenarios,
                                                     requested_rows=metadata.get("requested_rows"))
        privacy = privacy_checks(sample["source"], sample["train"], sample["holdout"], synthetic,
                                 columns, seed=seed)
        mode = "sample"
    else:
        fidelity = spec_fidelity(schema, tables, scenarios, requested_rows=metadata.get("requested_rows"))
        privacy = {"applicable": False, "status": "not_applicable",
                   "note": "No source data was used: rows were generated from the schema only, so "
                           "there are no real records to compare against."}
        mode = "spec"
    fidelity["status"] = T.FIDELITY_SCORE.status(fidelity["score"])
    fidelity["threshold"] = T.FIDELITY_SCORE.describe()
    if "relationships" not in fidelity:
        fidelity["relationships"] = relationship_stats(schema, tables,
                                                       fixed=set(metadata.get("requested_rows") or {}))

    statuses = [integrity["status"], fidelity["status"]]
    if privacy.get("applicable"):
        statuses.append(privacy["status"])
    report = {
        "report_version": REPORT_VERSION,
        "engine_version": metadata.get("engine_version", ENGINE_VERSION),
        "seed": seed,
        "mode": mode,
        "overall": {"status": _worst(statuses), "fidelity_score": fidelity["score"]},
        "integrity": integrity,
        "fidelity": fidelity,
        "privacy": privacy,
        "utility": {"applicable": False,
                    "note": "Train-on-synthetic / test-on-real utility is planned for a later milestone."},
        "generation": {k: metadata[k] for k in ("rows", "scenarios", "models", "rows_dropped_no_copy")
                       if k in metadata},
    }
    if sample is not None:
        report["sample"] = {"table": sample["table"], "rows": int(len(sample["source"])),
                            "train_rows": int(len(sample["train"])),
                            "holdout_rows": int(len(sample["holdout"])),
                            "learned_columns": [c.name for c in sample["columns"]],
                            "detections": sample.get("detections", [])}
    report["summary"] = summarize(report)
    return report


def _fmt(n: float) -> str:
    return f"{n:,.0f}" if float(n).is_integer() else f"{n:,.2f}"


def summarize(report: dict[str, Any]) -> str:
    """Plain-English summary of the report (a few sentences)."""
    integ = report["integrity"]
    fid = report["fidelity"]
    priv = report["privacy"]
    rows = sum(integ["rows"].values())
    n_tables = len(integ["rows"])
    parts = []
    if report["mode"] == "sample":
        s = report["sample"]
        parts.append(f"This dataset ({_fmt(rows)} rows in {n_tables} table{'s' if n_tables != 1 else ''}) "
                     f"was learned from a {_fmt(s['rows'])}-row sample of '{s['table']}'.")
    else:
        parts.append(f"This dataset ({_fmt(rows)} rows in {n_tables} table{'s' if n_tables != 1 else ''}) "
                     "was generated from the schema only; no real data was used.")
    n_fk = len(integ["foreign_keys"])
    viol = integ["constraint_violations"]["total"]
    if n_fk:
        parts.append(f"{integ['fk_resolved_pct']:.2f}% of foreign-key values across {n_fk} relationship"
                     f"{'s' if n_fk != 1 else ''} point at a real parent row.")
    parts.append("No declared rule is broken." if viol == 0
                 else f"{_fmt(viol)} rows break a declared rule; see the integrity section.")
    word = {"pass": "closely matches", "warn": "partly matches", "fail": "does not match well"}[fid["status"]]
    target = "the source sample" if report["mode"] == "sample" else "the schema spec"
    parts.append(f"Fidelity is {fid['score']:.0f}/100: the data {word} {target}.")
    if priv.get("applicable"):
        checks = {c["name"]: c for c in priv["checks"]}
        exact = checks["exact_matches"]["value"]
        parts.append("No synthetic row is an exact copy of a source row." if exact == 0
                     else f"{_fmt(exact)} synthetic rows exactly copy a source row.")
        mia = checks.get("membership_inference_auc")
        if mia:
            parts.append(f"A simple membership-inference attack scored AUC {mia['value']:.2f} "
                         "(0.50 means it does no better than guessing).")
        verdict = {"pass": "All privacy checks passed.",
                   "warn": "Some privacy checks need a closer look before sharing.",
                   "fail": "At least one privacy check failed; do not share this data yet."}[priv["status"]]
        parts.append(verdict)
        parts.append("These checks are statistical evidence, not a legal guarantee of anonymity.")
    overall = report["overall"]["status"]
    parts.append({"pass": "Overall: pass.", "warn": "Overall: warn.", "fail": "Overall: fail."}[overall])
    return " ".join(parts)
