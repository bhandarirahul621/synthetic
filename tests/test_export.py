"""Export formats and (optional) Postgres delivery."""

import json
import os

import pandas as pd
import pytest
import sqlglot

from synthetic import pipeline
from synthetic.ddl import parse_ddl
from synthetic.export import deliver_postgres, write_dataset


def test_all_formats(tmp_path, ecommerce_sql):
    schema = parse_ddl(ecommerce_sql)
    result = pipeline.run(schema, rows={"customers": 30, "orders": 80}, seed=1, with_report=False)
    files = write_dataset(result.tables, result.schema, tmp_path, ["csv", "parquet", "json", "sql"])
    assert {f["format"] for f in files} == {"csv", "parquet", "json", "sql"}
    orders_csv = pd.read_csv(tmp_path / "orders.csv")
    assert len(orders_csv) == 80
    parquet = pd.read_parquet(tmp_path / "orders.parquet")
    assert str(parquet["is_fraud"].dtype) == "bool" and str(parquet["ordered_at"].dtype).startswith("datetime64")
    rows = json.loads((tmp_path / "orders.json").read_text())
    assert len(rows) == 80 and isinstance(rows[0]["is_fraud"], bool)
    statements = sqlglot.parse((tmp_path / "orders.sql").read_text(), read="postgres")
    assert all(s.key == "insert" for s in statements)
    assert sqlglot.parse((tmp_path / "_schema.sql").read_text(), read="postgres")
    assert all(len(f["sha256"]) == 64 for f in files)


@pytest.mark.skipif(not os.environ.get("SYNTHETIC_TEST_PG_DSN"), reason="set SYNTHETIC_TEST_PG_DSN to run")
def test_postgres_delivery(ecommerce_sql):  # pragma: no cover - needs a database
    pytest.importorskip("psycopg")
    schema = parse_ddl(ecommerce_sql)
    result = pipeline.run(schema, rows={"customers": 20, "orders": 50}, seed=1, with_report=False)
    counts = deliver_postgres(result.tables, schema, os.environ["SYNTHETIC_TEST_PG_DSN"],
                              target_schema="synthetic_test", if_exists="replace")
    assert counts["orders"] == 50
