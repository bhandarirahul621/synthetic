"""Synthetic: privacy-safe synthetic data, schema-first and reproducible.

The package is organised by responsibility:

- ``synthetic.schema``     the schema model (tables, columns, constraints)
- ``synthetic.ddl``        SQL DDL import (Postgres, MySQL)
- ``synthetic.engine``     the generation engine (relational orchestrator, generators, fitting)
- ``synthetic.report``     the Fidelity and Privacy Report
- ``synthetic.export``     CSV / Parquet / JSON / SQL writers and Postgres delivery
- ``synthetic.api``        the FastAPI service (``/v1``)
- ``synthetic.sdk``        the Python SDK
- ``synthetic.cli``        the ``synthetic`` command line tool
- ``synthetic.mcp_server`` the MCP server for AI agents
"""

from synthetic.engine.version import ENGINE_VERSION

__all__ = ["ENGINE_VERSION"]
__version__ = "0.1.0"
