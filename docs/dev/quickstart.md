# Quickstart (local)

This needs Python 3.11+ and [uv](https://docs.astral.sh/uv/).

## Install

```bash
uv sync                      # creates .venv with all dependencies
uv sync --extra postgres     # optional: Postgres delivery (psycopg)
```

## Generate locally (no server)

```bash
uv run synthetic generate --schema examples/ecommerce.sql \
  --rows customers=2000,orders=50000 --seed 42 --out ./out --format parquet \
  --scenario orders.is_fraud=0.02
uv run synthetic report --data ./out          # rebuilds out/report.json + report.html

# Learn from a sample (FR3). PII columns are generated fresh, never learned.
uv run synthetic generate --sample examples/sample_customers.csv --table customers \
  --rows customers=5000 --seed 1 --out ./out-sample
```

Running the same command again gives byte-identical files, and the SHA-256 values printed are the same.

## Run the server

```bash
uv run synthetic keys create --scopes admin       # prints sk_test_... once; stored hashed in ./var
uv run synthetic serve                             # http://127.0.0.1:8000  (UI at /, docs at /docs)
```

**Dev bootstrap:** `uv run synthetic serve --dev-bootstrap` (or `SYNTHETIC_DEV_BOOTSTRAP=1`) creates an admin test key on first start if none exists. It writes the key to `var/dev-api-key.txt` (mode 600), never to the log.

Useful settings (environment variables):

| Variable | Default | Meaning |
|---|---|---|
| `SYNTHETIC_DATA_DIR` | `var` | SQLite and files |
| `SYNTHETIC_RETENTION_HOURS` | `24` | delete uploads this long after their last job (0–720) |
| `SYNTHETIC_RATE_LIMIT_PER_MINUTE` | `60` | per key |
| `SYNTHETIC_TEST_KEY_MAX_ROWS` | `100000` | row cap per job for `sk_test_` keys |

## curl

```bash
export KEY=sk_test_...   # from `keys create`
curl -s localhost:8000/v1/schemas -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d "$(jq -n --rawfile ddl examples/ecommerce.sql '{ddl: $ddl}')"          # → {"id": "sch_..."}
curl -s localhost:8000/v1/previews -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -d '{"schema_id": "sch_...", "rows": {"customers": 5}}'
curl -s localhost:8000/v1/datasets -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{"schema_id": "sch_...", "rows": {"customers": 2000, "orders": 50000}, "seed": 42,
       "scenarios": [{"type": "rare_event", "column": "orders.is_fraud", "rate": 0.02}], "formats": ["parquet"]}'
curl -s localhost:8000/v1/datasets/ds_... -H "Authorization: Bearer $KEY"          # status + progress
curl -s localhost:8000/v1/datasets/ds_.../files -H "Authorization: Bearer $KEY"    # signed links
curl -s localhost:8000/v1/datasets/ds_.../report -H "Authorization: Bearer $KEY"
curl -s localhost:8000/v1/uploads -H "Authorization: Bearer $KEY" -F file=@examples/sample_customers.csv
```

## SDK

```python
from synthetic.sdk import Client

client = Client(api_key="sk_test_...", base_url="http://localhost:8000")
schema = client.schemas.create(ddl=open("examples/ecommerce.sql").read())
ds = client.datasets.create(schema_id=schema["id"], rows={"customers": 2000, "orders": 50000}, seed=42).wait()
ds.download("./out")
print(client.reports.get(ds.id)["summary"])
```

The CLI also talks to a server: `SYNTHETIC_API_KEY=... uv run synthetic remote generate --schema examples/ecommerce.sql --rows customers=100 --download ./out`.

## MCP (Claude Code)

Start the server first. Then add this to `.mcp.json` in your project (or run `claude mcp add`):

```json
{
  "mcpServers": {
    "synthetic": {
      "command": "/path/to/synthetic/.venv/bin/synthetic",
      "args": ["mcp"],
      "env": {"SYNTHETIC_API_KEY": "sk_test_...", "SYNTHETIC_BASE_URL": "http://localhost:8000"}
    }
  }
}
```

The tools are `create_schema`, `preview`, `create_dataset`, `get_dataset`, `get_report` and `list_recipes`. They return previews (at most 20 rows) and links, never full datasets.

## Tests, lint and benchmark

```bash
uv run pytest            # SYNTHETIC_TEST_PG_DSN=postgresql://... enables the Postgres delivery test
uv run ruff check src tests scripts
uv run python scripts/benchmark.py        # 1M rows x 20 columns
docker build -t synthetic . && docker run -p 8000:8000 synthetic
```
