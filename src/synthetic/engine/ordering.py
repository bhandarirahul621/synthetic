"""Decide the order in which tables are generated.

Parents must exist before children, the way you must build the foundation
before the walls: an order row can only point at a customer that already
exists. This is a *topological sort* of the foreign-key graph.
"""

from __future__ import annotations

from synthetic.errors import SchemaError
from synthetic.schema import Schema


def parent_tables(schema: Schema, table_name: str) -> list[str]:
    """Distinct parent tables of ``table_name`` (self-references excluded), in column order."""
    table = schema.table(table_name)
    out: list[str] = []
    for col in table.foreign_keys:
        assert col.foreign_key is not None
        parent = col.foreign_key.table
        if parent != table_name and parent not in out:
            out.append(parent)
    return out


def topological_order(schema: Schema) -> list[str]:
    """Return table names with every parent before its children.

    Uses Kahn's algorithm. Ties are broken by the order tables appear in the
    schema, so the result is deterministic (important for FR10).
    Raises :class:`SchemaError` if foreign keys form a cycle between tables.
    """
    names = schema.table_names
    parents = {name: set(parent_tables(schema, name)) for name in names}
    done: list[str] = []
    remaining = list(names)
    while remaining:
        ready = [n for n in remaining if parents[n] <= set(done)]
        if not ready:
            cycle = ", ".join(remaining)
            raise SchemaError(
                "fk_cycle",
                f"Foreign keys form a cycle between tables: {cycle}. Make one of the "
                "foreign keys nullable and remove it from the schema, or split the cycle.",
            )
        # Take the first ready table in schema order, then re-scan. Simple and stable.
        done.append(ready[0])
        remaining.remove(ready[0])
    return done
