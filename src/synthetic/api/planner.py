"""Natural-language schema planning (FR1): the pluggable interface only.

A *schema planner* turns a prompt such as "an online shop with customers,
orders and refunds" into a :class:`~synthetic.schema.Schema` the user can
edit. The real implementation will call an LLM (PRD §9: LLMs are used only
for schema planning and text fields). This milestone ships the interface and
a clear ``501`` when no planner is configured; no LLM API is called.
"""

from __future__ import annotations

from typing import Protocol

from synthetic.schema import Schema

MAX_TABLES = 20
"""FR1: a prompt returns at most 20 tables."""


class SchemaPlanner(Protocol):
    """Anything that can turn a prompt into a schema."""

    name: str

    def plan(self, prompt: str, max_tables: int = MAX_TABLES) -> Schema:
        """Return a valid schema with at most ``max_tables`` tables."""
        ...


#: Registered planners by name. The LLM planner will register itself here.
PLANNERS: dict[str, type] = {}


def get_planner(name: str | None) -> SchemaPlanner | None:
    """Return the configured planner, or ``None`` if none is configured/available."""
    if not name:
        return None
    cls = PLANNERS.get(name)
    return cls() if cls is not None else None
