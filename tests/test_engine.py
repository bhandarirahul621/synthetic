"""FR4: relational integrity and constraints, including a property-style test over seeds and schemas."""

import numpy as np
import pandas as pd
import pytest

from synthetic.ddl import parse_ddl
from synthetic.engine.constraints import check_foreign_keys, validate_dataset
from synthetic.engine.ordering import topological_order
from synthetic.engine.relational import allocate_children, generate
from synthetic.engine.scenarios import Scenario
from synthetic.errors import ConstraintError, SchemaError
from synthetic.schema import ChildCount, Column, Schema, Table

KITCHEN_SINK = Schema(name="kitchen_sink", tables=[
    Table(name="teams", rows=12, columns=[
        Column(name="code", type="string", primary_key=True, max_length=6),
        Column(name="label", type="category", allowed_values=["red", "blue", "green"], weights=[5, 3, 2])]),
    Table(name="employees", rows=150, columns=[
        Column(name="id", type="uuid", primary_key=True),
        Column(name="team_code", type="string", nullable=True, null_rate=0.1,
               foreign_key={"table": "teams", "column": "code",
                            "children": ChildCount(distribution="poisson", mean=10, min=1, max=30)}),
        Column(name="manager_id", type="uuid", foreign_key={"table": "employees", "column": "id"}),
        Column(name="email", type="email", unique=True, nullable=False),
        Column(name="salary", type="float", min=30000, max=250000, distribution="lognormal", mean=70000),
        Column(name="hired_on", type="date", min="2015-01-01", max="2026-01-01", nullable=False),
        Column(name="left_on", type="date", null_rate=0.7),
        Column(name="badge", type="int", unique=True, min=1000, max=99999)],
        checks=["left_on > hired_on", "salary >= 30000"]),
    Table(name="reviews", columns=[
        Column(name="id", type="int", primary_key=True),
        Column(name="employee_id", type="uuid", nullable=False,
               foreign_key={"table": "employees", "column": "id",
                            "children": ChildCount(distribution="uniform", min=0, max=4)}),
        Column(name="score", type="int", min=1, max=5),
        Column(name="period", type="category", allowed_values=["H1", "H2"]),
        Column(name="note", type="text", null_rate=0.5)],
        unique_together=[["employee_id", "period"]]),
])


def random_schema(seed: int) -> Schema:
    """A random multi-table schema: random column types, FKs to earlier tables and date checks."""
    rng = np.random.default_rng(seed)
    tables = []
    for t in range(int(rng.integers(2, 6))):
        cols = [Column(name="id", type="int", primary_key=True)]
        for p in range(t):
            if rng.random() < 0.6:
                cols.append(Column(name=f"t{p}_id", type="int", nullable=bool(rng.random() < 0.3),
                                   null_rate=0.05, foreign_key={"table": f"t{p}", "column": "id"}))
        for i in range(int(rng.integers(1, 6))):
            kind = str(rng.choice(["int", "float", "bool", "category", "datetime", "email", "name", "string"]))
            extra = {"allowed_values": ["a", "b", "c"]} if kind == "category" else {}
            if kind in ("int", "float"):
                lo = float(rng.integers(-50, 50))
                extra = {"min": lo, "max": lo + float(rng.integers(1, 500))}
            cols.append(Column(name=f"c{i}", type=kind, unique=bool(kind in ("email", "string") and rng.random() < 0.5),
                               null_rate=float(rng.choice([0.0, 0.2])), **extra))
        cols += [Column(name="start_at", type="datetime", nullable=False), Column(name="end_at", type="datetime")]
        tables.append(Table(name=f"t{t}", columns=cols, rows=int(rng.integers(5, 300)), checks=["end_at >= start_at"]))
    return Schema(name=f"random_{seed}", tables=tables)


def _schemas(ecommerce_sql, fintech_yaml):
    return {"ecommerce": parse_ddl(ecommerce_sql), "fintech": Schema.from_yaml(fintech_yaml),
            "kitchen_sink": KITCHEN_SINK}


@pytest.mark.parametrize("seed", [0, 1, 7, 42, 2026])
def test_fr4_integrity_property(seed, ecommerce_sql, fintech_yaml):
    """For every schema and seed: 100% of FKs resolve and no declared rule is broken."""
    schemas = list(_schemas(ecommerce_sql, fintech_yaml).values()) + [random_schema(seed), random_schema(seed + 100)]
    for schema in schemas:
        rows = {"customers": 300, "orders": 2000} if schema.name == "schema" else None
        result = generate(schema, rows=rows, seed=seed)
        assert validate_dataset(schema, result.tables) == [], schema.name
        for fk in check_foreign_keys(schema, result.tables):
            assert fk.resolved == fk.total, (schema.name, fk)


def test_self_reference_is_a_tree():
    df = generate(KITCHEN_SINK, seed=3).tables["employees"]
    position = {k: i for i, k in enumerate(df["id"])}
    managers = df["manager_id"].dropna()
    assert all(position[m] < position[e] for e, m in zip(df.loc[managers.index, "id"], managers, strict=True))


def test_topological_order_and_cycle(ecommerce_sql):
    assert topological_order(parse_ddl(ecommerce_sql)) == ["customers", "products", "orders", "order_items"]
    cyclic = Schema(tables=[
        Table(name="a", columns=[Column(name="id", type="int", primary_key=True),
                                 Column(name="b_id", type="int", foreign_key={"table": "b", "column": "id"})]),
        Table(name="b", columns=[Column(name="id", type="int", primary_key=True),
                                 Column(name="a_id", type="int", foreign_key={"table": "a", "column": "id"})])])
    with pytest.raises(SchemaError) as e:
        generate(cyclic)
    assert e.value.code == "fk_cycle"


def test_child_counts_exact_total_and_skewed():
    rng = np.random.default_rng(0)
    counts = allocate_children(2000, None, 50_000, rng)
    assert counts.sum() == 50_000
    assert counts.max() > 3 * counts.mean()  # realistic skew: some parents have many children
    bounded = allocate_children(100, ChildCount(min=2, max=5), 400, rng)
    assert bounded.sum() == 400 and bounded.min() >= 2 and bounded.max() <= 5
    with pytest.raises(ConstraintError):
        allocate_children(10, ChildCount(max=2), 100, rng)


def test_requested_rows_respected(ecommerce_sql):
    r = generate(parse_ddl(ecommerce_sql), rows={"customers": 2000, "orders": 50_000}, seed=1)
    assert r.row_counts["customers"] == 2000 and r.row_counts["orders"] == 50_000


def test_rare_event_scenario_exact_rate(ecommerce_sql):
    r = generate(parse_ddl(ecommerce_sql), rows={"customers": 500, "orders": 10_000}, seed=4,
                 scenarios=[Scenario(column="orders.is_fraud", rate=0.02),
                            Scenario(column="orders.status", rate=0.1, value="refunded")])
    orders = r.tables["orders"]
    assert int(orders["is_fraud"].sum()) == 200
    assert int((orders["status"] == "refunded").sum()) == 1000


def test_invalid_scenarios_rejected(ecommerce_sql):
    schema = parse_ddl(ecommerce_sql)
    for bad in (Scenario(column="orders.nope", rate=0.1), Scenario(column="orders.total_amount", rate=0.1),
                Scenario(column="orders.status", rate=0.1, value="not-a-status")):
        with pytest.raises(SchemaError):
            generate(schema, scenarios=[bad])


def test_unsatisfiable_constraints_fail_loudly():
    schema = Schema(tables=[Table(name="t", rows=50, columns=[
        Column(name="id", type="int", primary_key=True), Column(name="u", type="int", unique=True, min=1, max=10)])])
    with pytest.raises(ConstraintError) as e:
        generate(schema)
    assert e.value.code == "unique_range_too_small"


def test_cross_column_check_repair_keeps_bounds():
    schema = Schema(tables=[Table(name="t", rows=5000, columns=[
        Column(name="id", type="int", primary_key=True),
        Column(name="a", type="date", min="2024-01-01", max="2024-12-31", nullable=False),
        Column(name="b", type="date", min="2024-01-01", max="2024-12-31", nullable=False)], checks=["b > a"])])
    df = generate(schema, seed=9).tables["t"]
    assert (df["b"] > df["a"]).all()
    assert df["a"].min() >= pd.Timestamp("2024-01-01") and df["b"].max() <= pd.Timestamp("2024-12-31")
