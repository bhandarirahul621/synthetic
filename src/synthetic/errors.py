"""Domain errors shared by the engine, the report and the API.

Every error carries a machine-readable ``code`` and a plain-English ``message``
that explains how to fix the problem. Messages must never contain values from
uploaded source data (FR15): they may name tables and columns, never cell values.
"""

from __future__ import annotations


class SyntheticError(Exception):
    """Base class for errors we raise on purpose.

    ``status`` is the HTTP status the API uses when the error reaches a client.
    """

    status: int = 400
    type: str = "invalid_request"

    def __init__(self, code: str, message: str, param: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.param = param


class SchemaError(SyntheticError):
    """The schema is malformed (unknown table, bad reference, cycle, ...)."""

    status = 422
    type = "schema_error"


class ConstraintError(SyntheticError):
    """The declared constraints cannot be satisfied for the requested rows."""

    status = 422
    type = "constraint_error"


class DDLParseError(SyntheticError):
    """The SQL DDL could not be parsed."""

    status = 400
    type = "invalid_request"


class FitError(SyntheticError):
    """The sample data could not be learned from (empty file, unreadable format, ...)."""

    status = 422
    type = "fit_error"
