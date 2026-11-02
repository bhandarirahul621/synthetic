"""Write generated tables to files (CSV, Parquet, JSON, SQL) or straight into Postgres (F5).

Formatting is fixed and explicit (dates as ``YYYY-MM-DD``, datetimes as
``YYYY-MM-DD HH:MM:SS``, booleans as ``true``/``false``, ``\\n`` line endings),
so the same data always produces the same bytes (FR10). Every written file
is returned with its SHA-256 checksum, which makes reproducibility easy to
prove: run twice, compare checksums.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from synthetic.engine.ordering import topological_order
from synthetic.errors import SyntheticError
from synthetic.schema import Column, Schema, Table

FORMATS = ("csv", "parquet", "json", "sql")
EXTENSIONS = {"csv": "csv", "parquet": "parquet", "json": "json", "sql": "sql"}


class ConnectorUnavailable(SyntheticError):
    """The optional dependency for a connector is not installed."""

    status = 501
    type = "not_implemented"


def _display_frame(df: pd.DataFrame, table: Table | None) -> pd.DataFrame:
    """Turn typed columns into the exact text we publish (dates, bools)."""
    out = {}
    for name in df.columns:
        series = df[name]
        col = _find(table, name)
        if pd.api.types.is_datetime64_any_dtype(series):
            fmt = "%Y-%m-%d" if col is not None and col.type == "date" else "%Y-%m-%d %H:%M:%S"
            out[name] = series.dt.strftime(fmt).astype(object).where(series.notna(), None)
        elif pd.api.types.is_bool_dtype(series):
            out[name] = series.astype(object).map({True: "true", False: "false"}).where(series.notna(), None)
        else:
            out[name] = series
    return pd.DataFrame(out)


def _find(table: Table | None, name: str) -> Column | None:
    if table is None:
        return None
    try:
        return table.column(name)
    except KeyError:
        return None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_csv(df: pd.DataFrame, path: Path, table: Table | None = None) -> None:
    _display_frame(df, table).to_csv(path, index=False, lineterminator="\n", na_rep="")


def write_parquet(df: pd.DataFrame, path: Path, table: Table | None = None) -> None:
    arrays, fields = [], []
    for name in df.columns:
        series = df[name]
        col = _find(table, name)
        if pd.api.types.is_datetime64_any_dtype(series):
            arr = pa.array(series.astype("datetime64[ms]"), from_pandas=True)
            if col is not None and col.type == "date":
                arr = arr.cast(pa.date32())
        elif isinstance(series.dtype, pd.Int64Dtype):
            arr = pa.array(series, type=pa.int64(), from_pandas=True)
        elif pd.api.types.is_bool_dtype(series):
            arr = pa.array(series, type=pa.bool_(), from_pandas=True)
        elif pd.api.types.is_float_dtype(series):
            arr = pa.array(series, type=pa.float64(), from_pandas=True)
        else:
            arr = pa.array(series.astype(object).where(series.notna(), None), type=pa.string())
        arrays.append(arr)
        fields.append(pa.field(str(name), arr.type))
    pq.write_table(pa.Table.from_arrays(arrays, schema=pa.schema(fields)), path)


def _json_default(v: Any) -> Any:
    """Convert numpy scalars that ``json`` does not know about."""
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return None if np.isnan(v) else float(v)
    if isinstance(v, np.bool_):
        return bool(v)
    raise TypeError(type(v).__name__)


def frame_records(df: pd.DataFrame, table: Table | None = None) -> list[dict[str, Any]]:
    """Rows as JSON-ready dicts (dates as text, booleans as true/false, nulls as None)."""
    frame = _display_frame(df, table)
    for name in df.columns:
        if pd.api.types.is_bool_dtype(df[name]):
            frame[name] = df[name].astype(object)
    frame = frame.astype(object).where(frame.notna(), None)
    records = frame.to_dict(orient="records")
    return json.loads(json.dumps(records, default=_json_default))


def write_json(df: pd.DataFrame, path: Path, table: Table | None = None) -> None:
    """A JSON array of row objects (booleans as JSON true/false, nulls as null)."""
    frame = _display_frame(df, table)
    for name in df.columns:
        if pd.api.types.is_bool_dtype(df[name]):
            frame[name] = df[name].astype(object)
    frame = frame.astype(object).where(frame.notna(), None)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("[")
        for i, record in enumerate(frame.to_dict(orient="records")):
            fh.write(("," if i else "") + "\n" + json.dumps(record, ensure_ascii=False, default=_json_default))
        fh.write("\n]\n")


def _quote_ident(name: str, dialect: str) -> str:
    if dialect == "mysql":
        return "`" + name.replace("`", "``") + "`"
    return '"' + name.replace('"', '""') + '"'


def _sql_literal(v: Any) -> str:
    if v is None or v is pd.NA or (isinstance(v, float) and np.isnan(v)):
        return "NULL"
    if isinstance(v, bool | np.bool_):
        return "TRUE" if v else "FALSE"
    if isinstance(v, int | np.integer):
        return str(int(v))
    if isinstance(v, float | np.floating):
        return repr(float(v))
    return "'" + str(v).replace("'", "''") + "'"


_SQL_TYPES = {
    "int": "BIGINT", "float": "DOUBLE PRECISION", "bool": "BOOLEAN", "date": "DATE",
    "datetime": "TIMESTAMP", "uuid": "UUID", "text": "TEXT",
}


def schema_to_ddl(schema: Schema, dialect: str = "postgres") -> str:
    """CREATE TABLE statements (parents first) for loading the data elsewhere."""
    statements = []
    for name in topological_order(schema):
        table = schema.table(name)
        lines = []
        for col in table.columns:
            sql_type = _SQL_TYPES.get(col.type, f"VARCHAR({col.max_length})" if col.max_length else "TEXT")
            if dialect == "mysql" and col.type == "uuid":
                sql_type = "CHAR(36)"
            if dialect == "mysql" and sql_type == "TEXT" and (col.unique or col.primary_key):
                sql_type = "VARCHAR(255)"
            if dialect == "mysql" and sql_type == "DOUBLE PRECISION":
                sql_type = "DOUBLE"
            parts = [_quote_ident(col.name, dialect), sql_type]
            if not col.nullable:
                parts.append("NOT NULL")
            if col.unique and not col.primary_key:
                parts.append("UNIQUE")
            lines.append("  " + " ".join(parts))
        if table.primary_key:
            lines.append("  PRIMARY KEY (" + ", ".join(_quote_ident(k, dialect) for k in table.primary_key) + ")")
        for col in table.foreign_keys:
            fk = col.foreign_key
            assert fk is not None
            lines.append(f"  FOREIGN KEY ({_quote_ident(col.name, dialect)}) REFERENCES "
                         f"{_quote_ident(fk.table, dialect)} ({_quote_ident(fk.column, dialect)})")
        statements.append(f"CREATE TABLE {_quote_ident(name, dialect)} (\n" + ",\n".join(lines) + "\n);")
    return "\n\n".join(statements) + "\n"


def write_sql(df: pd.DataFrame, path: Path, table: Table | None = None, table_name: str = "data",
              dialect: str = "postgres", batch: int = 500) -> None:
    """Multi-row INSERT statements, ``batch`` rows per statement."""
    frame = _display_frame(df, table)
    bool_cols = {c for c in df.columns if pd.api.types.is_bool_dtype(df[c])}
    cols = ", ".join(_quote_ident(str(c), dialect) for c in frame.columns)
    head = f"INSERT INTO {_quote_ident(table_name, dialect)} ({cols}) VALUES\n"
    columns = list(frame.columns)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        rows = frame.itertuples(index=False, name=None)
        buf: list[str] = []
        for row in rows:
            values = []
            for c, v in zip(columns, row, strict=True):
                if c in bool_cols and v is not None:
                    values.append("TRUE" if v == "true" else "FALSE")
                else:
                    values.append(_sql_literal(v))
            buf.append("(" + ", ".join(values) + ")")
            if len(buf) == batch:
                fh.write(head + ",\n".join(buf) + ";\n")
                buf = []
        if buf:
            fh.write(head + ",\n".join(buf) + ";\n")


def write_dataset(tables: dict[str, pd.DataFrame], schema: Schema | None, out_dir: str | Path,
                  formats: Iterable[str] = ("csv",), dialect: str = "postgres") -> list[dict[str, Any]]:
    """Write every table in every format. Returns file records with size and SHA-256."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    formats = list(dict.fromkeys(formats))
    bad = [f for f in formats if f not in FORMATS]
    if bad:
        raise SyntheticError("unsupported_format", f"Unsupported format(s): {', '.join(bad)}. "
                             f"Use {', '.join(FORMATS)}.", param="formats")
    files = []
    for name, df in tables.items():
        table = schema.table(name) if schema is not None and name in schema.table_names else None
        for fmt in formats:
            path = out / f"{name}.{EXTENSIONS[fmt]}"
            if fmt == "csv":
                write_csv(df, path, table)
            elif fmt == "parquet":
                write_parquet(df, path, table)
            elif fmt == "json":
                write_json(df, path, table)
            else:
                write_sql(df, path, table, table_name=name, dialect=dialect)
            files.append({"table": name, "format": fmt, "path": str(path), "filename": path.name,
                          "bytes": path.stat().st_size, "sha256": _sha256(path), "rows": len(df)})
    if "sql" in formats and schema is not None:
        path = out / "_schema.sql"
        path.write_text(schema_to_ddl(schema, dialect), encoding="utf-8")
        files.append({"table": None, "format": "sql", "path": str(path), "filename": path.name,
                      "bytes": path.stat().st_size, "sha256": _sha256(path), "rows": 0})
    return files


def read_table_file(path: str | Path) -> pd.DataFrame:
    """Read one exported file back (CSV or Parquet), e.g. for ``synthetic report``."""
    path = Path(path)
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, keep_default_na=True, low_memory=False)


# ---------------------------------------------------------------------------
# Postgres delivery (optional extra: pip install 'synthetic[postgres]')
# ---------------------------------------------------------------------------


def deliver_postgres(tables: dict[str, pd.DataFrame], schema: Schema, dsn: str,
                     target_schema: str = "public", if_exists: str = "fail") -> dict[str, int]:
    """Create tables (parents first) and COPY rows into a Postgres database.

    ``if_exists``: ``"fail"`` (default), ``"replace"`` (drop and recreate) or
    ``"append"``. The DSN is never logged or stored.
    """
    try:
        import psycopg
        from psycopg import sql
    except ImportError:
        raise ConnectorUnavailable(
            "connector_unavailable",
            "Postgres delivery needs the optional 'postgres' extra: uv sync --extra postgres "
            "(or pip install 'synthetic[postgres]').",
        ) from None
    if if_exists not in ("fail", "replace", "append"):
        raise SyntheticError("invalid_if_exists", "if_exists must be fail, replace or append.",
                             param="if_exists")
    counts: dict[str, int] = {}
    order = topological_order(schema)
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(target_schema)))
            cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(target_schema)))
            if if_exists == "replace":
                for name in reversed(order):
                    cur.execute(sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(sql.Identifier(name)))
            if if_exists in ("fail", "replace"):
                for statement in schema_to_ddl(schema).split(";\n"):
                    if statement.strip():
                        cur.execute(statement)  # identifiers are quoted by schema_to_ddl
            for name in order:
                df = _display_frame(tables[name], schema.table(name))
                columns = sql.SQL(", ").join(sql.Identifier(str(c)) for c in df.columns)
                copy_sql = sql.SQL("COPY {} ({}) FROM STDIN").format(sql.Identifier(name), columns)
                with cur.copy(copy_sql) as copy:
                    for row in df.itertuples(index=False, name=None):
                        copy.write_row([None if (v is None or v is pd.NA or
                                                 (isinstance(v, float) and np.isnan(v))) else v
                                        for v in row])
                counts[name] = len(df)
        conn.commit()
    return counts
