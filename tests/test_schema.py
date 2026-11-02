"""The schema model: validation, check parsing and (de)serialization."""

import pytest
from pydantic import ValidationError

from synthetic.schema import CheckConstraint, Column, Schema, Table, load_schema


def test_check_parse_column_and_literal():
    c = CheckConstraint.parse("end_date > start_date")
    assert (c.left, c.op, c.right_column, c.value) == ("end_date", ">", "start_date", None)
    c = CheckConstraint.parse("amount >= 0.5")
    assert c.value == 0.5 and c.right_column is None
    c = CheckConstraint.parse("status != 'gone'")
    assert c.value == "gone" and c.op == "!="


def test_primary_key_normalisation():
    t = Table(name="t", columns=[Column(name="id", type="int", primary_key=True), Column(name="x")])
    assert t.primary_key == ["id"]
    assert t.column("id").unique and not t.column("id").nullable


def test_not_null_forces_zero_null_rate():
    assert Column(name="x", nullable=False, null_rate=0.4).null_rate == 0.0


def test_fk_to_missing_table_is_rejected():
    with pytest.raises(ValidationError, match="not in the schema"):
        Schema(tables=[Table(name="orders", columns=[
            Column(name="id", type="int", primary_key=True),
            Column(name="customer_id", type="int", foreign_key={"table": "customers", "column": "id"})])])


def test_fk_to_non_key_column_is_rejected():
    with pytest.raises(ValidationError, match="neither a primary key nor unique"):
        Schema(tables=[
            Table(name="a", columns=[Column(name="id", type="int", primary_key=True), Column(name="v")]),
            Table(name="b", columns=[Column(name="a_v", foreign_key={"table": "a", "column": "v"})])])


def test_weights_must_match_values():
    with pytest.raises(ValidationError):
        Column(name="c", type="category", allowed_values=["a", "b"], weights=[1.0])


def test_check_with_unknown_column_is_rejected():
    with pytest.raises(ValidationError, match="unknown column"):
        Table(name="t", columns=[Column(name="a", type="int")], checks=["a > b"])


def test_json_and_yaml_roundtrip(fintech_yaml):
    schema = Schema.from_yaml(fintech_yaml)
    assert Schema.from_json(schema.to_json()) == schema
    assert Schema.from_yaml(schema.to_yaml()) == schema
    assert schema.table("accounts").checks[0].right_column == "opened_on"
    assert [r.child_table for r in schema.relationships()] == ["transactions"]


def test_load_schema_by_extension(tmp_path, ecommerce_sql):
    path = tmp_path / "s.sql"
    path.write_text(ecommerce_sql)
    assert load_schema(path).table_names == ["customers", "products", "orders", "order_items"]
    with pytest.raises(ValueError, match="unsupported"):
        load_schema(tmp_path / "s.txt") if (tmp_path / "s.txt").write_text("x") else None
