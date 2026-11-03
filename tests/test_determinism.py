"""FR10: same schema + seed + engine version → byte-identical CSV; a different seed → different output."""

import hashlib

import pandas as pd

from synthetic import pipeline
from synthetic.ddl import parse_ddl
from synthetic.engine.scenarios import Scenario
from synthetic.export import write_dataset
from synthetic.schema import Schema


def _digests(tmp_path, name, schema, seed, **kwargs):
    result = pipeline.run(schema, seed=seed, with_report=False, **kwargs)
    files = write_dataset(result.tables, result.schema, tmp_path / name, ["csv"])
    return {f["filename"]: hashlib.sha256((tmp_path / name / f["filename"]).read_bytes()).hexdigest()
            for f in files}


def test_same_seed_byte_identical_csv(tmp_path, ecommerce_sql, fintech_yaml):
    for schema in (parse_ddl(ecommerce_sql), Schema.from_yaml(fintech_yaml)):
        kwargs = {"rows": {schema.tables[0].name: 300}}
        if schema.table_names[0] == "customers":
            kwargs["scenarios"] = [Scenario(column="orders.is_fraud", rate=0.02)]
        a = _digests(tmp_path, f"{schema.name}-a", schema, 42, **kwargs)
        b = _digests(tmp_path, f"{schema.name}-b", schema, 42, **kwargs)
        c = _digests(tmp_path, f"{schema.name}-c", schema, 43, **kwargs)
        assert a == b
        assert all(a[name] != c[name] for name in a)


def test_sample_mode_is_deterministic(tmp_path, sample_csv):
    sample = pd.read_csv(sample_csv)
    a = _digests(tmp_path, "a", None, 5, sample=sample, sample_table="customers", rows={"customers": 500})
    b = _digests(tmp_path, "b", None, 5, sample=sample, sample_table="customers", rows={"customers": 500})
    c = _digests(tmp_path, "c", None, 6, sample=sample, sample_table="customers", rows={"customers": 500})
    assert a == b and a != c
