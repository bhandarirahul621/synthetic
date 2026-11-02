"""One function that runs a whole generation: (fit) → generate → report.

The API worker, the CLI and the tests all call :func:`run`, so there is
exactly one code path from "request" to "files + report". That is what makes
UI, API, SDK, CLI and MCP give identical results for the same inputs (G4).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from synthetic.engine.fit import FitResult, learn_from_sample
from synthetic.engine.relational import GenerationResult, generate
from synthetic.engine.scenarios import Scenario
from synthetic.errors import SchemaError
from synthetic.report.build import build_report
from synthetic.schema import Schema


@dataclass
class PipelineResult:
    """Generated tables, the schema actually used, metadata and the report."""

    schema: Schema
    generation: GenerationResult
    report: dict[str, Any]
    fit: FitResult | None = None

    @property
    def tables(self) -> dict[str, pd.DataFrame]:
        return self.generation.tables


def merge_fitted_table(schema: Schema | None, fit: FitResult) -> Schema:
    """Put the learned table into ``schema`` (replacing a table with the same name)."""
    if schema is None:
        return fit.schema()
    tables = [fit.table if t.name == fit.table.name else t for t in schema.tables]
    if fit.table.name not in schema.table_names:
        tables.append(fit.table)
    try:
        return Schema(name=schema.name, version=schema.version, tables=tables, warnings=schema.warnings)
    except ValueError as exc:
        raise SchemaError(
            "sample_schema_mismatch",
            "The learned sample table does not fit the schema (for example, a foreign key points at a "
            f"column the sample does not have). Details: {_first_msg(exc)}",
            param="upload_id",
        ) from None


def _first_msg(exc: Exception) -> str:
    errors = getattr(exc, "errors", None)
    if callable(errors):
        return "; ".join(str(e.get("msg", "")).removeprefix("Value error, ") for e in errors())
    return type(exc).__name__


def run(
    schema: Schema | None,
    rows: dict[str, int] | None = None,
    seed: int = 0,
    scenarios: list[Scenario] | None = None,
    sample: pd.DataFrame | None = None,
    sample_table: str | None = None,
    pii_columns: list[str] | None = None,
    progress: Callable[[float, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    with_report: bool = True,
) -> PipelineResult:
    """Generate a dataset and its report.

    With ``sample``, the table ``sample_table`` is learned from it (FR3); any
    other tables in ``schema`` are generated from their spec around it.
    """
    if schema is None and sample is None:
        raise SchemaError("schema_required", "Provide a schema, a sample upload, or both.", param="schema_id")
    rng = np.random.default_rng(seed)  # the one generator for the whole run (FR10)
    fit = None
    if sample is not None:
        name = sample_table or (schema.tables[0].name if schema and len(schema.tables) == 1 else "sample")
        forced = set(pii_columns or [])
        if schema is not None and name in schema.table_names:
            forced |= {c.name for c in schema.table(name).columns if c.pii}
        if progress:
            progress(0.05, "learning from sample")
        fit = learn_from_sample(sample, name, seed=seed, pii_columns=sorted(forced), rng=rng)
        schema = merge_fitted_table(schema, fit)
    assert schema is not None
    generation = generate(
        schema,
        rows=rows,
        seed=seed,
        scenarios=scenarios,
        models={fit.table.name: fit.model} if fit else None,
        no_copy={fit.table.name: fit.no_copy} if fit else None,
        progress=(lambda f, m: progress(0.1 + 0.7 * f, m)) if progress else None,
        should_cancel=should_cancel,
        rng=rng,
    )
    generation.metadata["requested_rows"] = dict(rows or {})
    report: dict[str, Any] = {}
    if with_report:
        if progress:
            progress(0.85, "building report")
        sample_info = None
        if fit is not None:
            sample_info = {"table": fit.table.name, "source": sample, "train": fit.train,
                           "holdout": fit.holdout, "columns": fit.modeled_columns,
                           "detections": fit.detection_summary()}
        report = build_report(schema, generation.tables, generation.metadata, sample=sample_info)
    return PipelineResult(schema=schema, generation=generation, report=report, fit=fit)
