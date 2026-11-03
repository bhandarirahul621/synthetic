"""Performance sanity check: ~1M rows x 20 columns (FR6 target: < 5 min p95 on the standard tier).

Run:  .venv/bin/python scripts/benchmark.py [rows]
"""

from __future__ import annotations

import sys
import tempfile
import time

from synthetic.engine.relational import generate
from synthetic.export import write_dataset
from synthetic.report.build import build_report
from synthetic.schema import Column, Schema, Table

COLUMNS = [
    Column(name="id", type="int", primary_key=True),
    Column(name="customer_uuid", type="uuid"),
    Column(name="email", type="email"),
    Column(name="first_name", type="name", subtype="first"),
    Column(name="last_name", type="name", subtype="last"),
    Column(name="phone", type="phone", null_rate=0.1),
    Column(name="city", type="address", subtype="city"),
    Column(name="country", type="address", subtype="country"),
    Column(name="segment", type="category", allowed_values=["consumer", "smb", "enterprise"], weights=[6, 3, 1]),
    Column(name="status", type="category", allowed_values=["active", "paused", "closed"]),
    Column(name="age", type="int", min=18, max=90),
    Column(name="income", type="float", min=0, max=500000, distribution="lognormal", mean=55000),
    Column(name="balance", type="float", min=-1000, max=100000, distribution="normal", mean=2500, std=4000),
    Column(name="score", type="int", min=300, max=850, distribution="normal", mean=680, std=60),
    Column(name="is_active", type="bool", p_true=0.8),
    Column(name="is_fraud", type="bool", p_true=0.02),
    Column(name="created_at", type="datetime", nullable=False),
    Column(name="updated_at", type="datetime"),
    Column(name="birth_date", type="date", min="1940-01-01", max="2007-12-31"),
    Column(name="note", type="text", null_rate=0.8),
]
SCHEMA = Schema(name="benchmark", tables=[Table(name="wide", columns=COLUMNS, checks=["updated_at >= created_at"])])


def main(rows: int = 1_000_000) -> None:
    t0 = time.perf_counter()
    result = generate(SCHEMA, rows={"wide": rows}, seed=1)
    t1 = time.perf_counter()
    report = build_report(SCHEMA, result.tables, result.metadata)
    t2 = time.perf_counter()
    with tempfile.TemporaryDirectory() as out:
        write_dataset(result.tables, SCHEMA, out, ["parquet"])
        t3 = time.perf_counter()
        write_dataset(result.tables, SCHEMA, out, ["csv"])
        t4 = time.perf_counter()
    print(f"rows={rows:,} columns={len(COLUMNS)}")
    print(f"generate      {t1 - t0:7.1f} s")
    print(f"report        {t2 - t1:7.1f} s  (status {report['overall']['status']})")
    print(f"parquet write {t3 - t2:7.1f} s")
    print(f"csv write     {t4 - t3:7.1f} s")
    print(f"total         {t4 - t0:7.1f} s")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1_000_000)
