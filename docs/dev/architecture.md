# Architecture (Milestone 1)

Think of a request as an order in a restaurant. The **API** takes the order and answers immediately with `202`. A **worker thread** cooks it by running `pipeline.run`. The **report** is the inspection sticker on the plate. The SDK, CLI, MCP server and web UI are different waiters, but they all use the same kitchen (G4).

```
 Web UI (/)   SDK   CLI remote   MCP (stdio)           CLI local generate/report
      \        |        |         /                              |
       └───────┴── REST /v1 (FastAPI) ──┘                         |
                 auth · scopes · rate limit · idempotency · errors  |
         ┌──────────────┼──────────────────┐                      |
   SQLiteStore      JobRunner (threads)  LocalBlobStore            |
   (metadata)            │               (var/blobs)               |
                         └──────────► pipeline.run ◄───────────────┘
                     fit (copula) → relational generate → report → export
```

## Modules → PRD

| Module | What it does | PRD |
|---|---|---|
| `schema.py` | Pydantic schema model: types, keys, FKs, child counts, checks, PII, JSON/YAML | F2 |
| `ddl.py`, `semantics.py` | Postgres/MySQL DDL (sqlglot) and dbt `schema.yml` import; name-based types and PII | FR2, F1 |
| `engine/ordering.py`, `engine/relational.py` | Topological order, children per parent, FK filling, scenarios, check repair, validation | FR4, F3 |
| `engine/generators.py`, `engine/pools.py` | Vectorised per-type generators; seeded Faker pools | F3, FR10 |
| `engine/constraints.py` | Bounds and validation (not null, unique, range, allowed values, checks, FKs) | FR4 |
| `engine/fit.py`, `engine/base.py` | Type detection, Gaussian copula behind the `TabularModel` interface, no-copy filter | FR3, FR8, §9 |
| `report/` | Integrity, fidelity (1−KS, 1−TVD, associations), privacy (exact match, DCR, NNDR, MIA), thresholds, HTML | FR7, F4 |
| `export.py` | CSV / Parquet / JSON / SQL with SHA-256; Postgres COPY (optional extra) | F5, FR10 |
| `pipeline.py` | The one code path: fit → generate → report | G4 |
| `api/` | FastAPI `/v1`, SQLite metadata, local blobs, jobs, webhooks, retention, keys, planner interface | §9.1, FR9–FR15 |
| `sdk.py`, `cli.py`, `mcp_server.py` | Thin clients over the API (plus the local CLI) | F6, §9.1.7 |
| `api/static/` | Single-page UI on the same API | G4 |

## Key design choices

- **Determinism (FR10):** one `numpy.random.Generator` is seeded once and passed through fitting, generation and repairs in a fixed order. Faker is seeded from it. Output formats are fixed, and checksums are recorded. *Trade-off:* adding a column changes every value after it. Per-column derived streams would fix that later, at the cost of an engine-version bump.
- **Integrity by construction (FR4):** child rows are created *from* parent keys. Composite keys cap children per parent. Every table is validated before it is returned, and an unsatisfiable rule fails the job with a 422-style error rather than producing bad data.
- **Privacy by default:** PII, free text and identifiers are never fitted. Quantile tails are trimmed, rare categories are dropped, and copies of source rows are resampled and then dropped. A 20% holdout is kept for the privacy checks. Logs hold IDs, counts and timings only, and unexpected exceptions log only their type and stack frames. Thresholds in `report/thresholds.py` are **provisional** until `privacy-compliance-expert` signs them off.

## Deviations from PRD §9 / §9.1

- **Engine:** our own engine, not a wrapped library (ADR 0001).
- **Storage:** SQLite and local files instead of Postgres and S3. Both sit behind the `MetadataStore` and `BlobStore` interfaces. There is no encryption at rest yet; it will rely on disk encryption or S3 SSE.
- **Uploads:** multipart `POST /v1/uploads` instead of signed upload URLs. Downloads use HMAC-signed, expiring `/v1/files/{token}` links.
- **Workers:** an in-process thread pool instead of a separate queue and workers. There is no worker isolation. Unfinished jobs are re-queued on restart, which is safe because generation is deterministic.
- **Auth:** API keys only. A single default workspace is created by the CLI. There is no OAuth for MCP clients.
- **Rate limits:** a fixed-window, in-memory, per-process limiter. Row quota is reported by `/v1/usage` but not enforced by default.
- **SDK and MCP:** hand-written, not generated from OpenAPI. A contract test checks that every SDK path exists in the spec. The official MCP conformance suite has not been run.
- **Extra endpoints:** list endpoints, `GET/DELETE /v1/uploads/{id}`, `/v1/keys`, and `/v1/webhooks/{id}/deliveries`.

## Status against FRs

| FR | Status | Notes |
|---|---|---|
| FR1 | Not met | Field, `SchemaPlanner` interface and 501 only |
| FR2 | Partly | Postgres/MySQL tests pass; the 50-file corpus has not been assembled |
| FR3 | Partly | CSV/Parquet in memory; 1 GB limit enforced but not benchmarked; detection is tested on our sample only |
| FR4 | Met (tests) | Property tests over seeds and random schemas |
| FR5 | Met locally | Preview is synchronous; no p95 measurement |
| FR6 | Met locally | 1M × 20: about 10 s to generate, 23 s including the report and Parquet and CSV writes, on a 4-core dev VM. Not measured on a "standard tier" |
| FR7 | Partly | JSON and HTML; PDF is TODO (501); no utility (TSTR) |
| FR8 | Met | Resample, then drop; tested |
| FR9 | Partly | Everything is in REST, SDK and CLI; MCP covers the core tools; conformance suite not run |
| FR10 | Met | Byte-identical CSV test |
| FR11 | Met | 24 h default, 0–720 h, per upload; `DELETE` purges now. Backups are not in scope |
| FR12 | Partly | OpenAPI covers all endpoints; SDK and MCP are not generated from it |
| FR13 | Partly | 202 in a few ms; webhooks are signed and retried for up to 24 h; no p95 or latency SLO measured |
| FR14 | Met | Replay or 409 within 24 h; one envelope with `request_id` |
| FR15 | Met (tests) | Hashed, scoped keys; 403; automated log, error and webhook scan |

## Known gaps / next milestone

- An LLM schema planner (FR1) and an LLM text filler.
- PDF reports and a train-on-synthetic, test-on-real (TSTR) utility score.
- Hosted deployment, TLS, and worker isolation (a separate queue and containers).
- Billing and Stripe; accounts, sign-in, workspaces and roles (F7).
- Postgres metadata and S3 storage (signed URLs, SSE), plus streaming and chunked processing for 1 GB inputs.
- More connectors (Snowflake, BigQuery, Databricks, MySQL, S3).
- Multi-table learning from samples, cross-table checks, composite FKs, and a second model.
- An external **red-team privacy review**, and `privacy-compliance-expert` sign-off on the thresholds. Known limit: the DCR closer-share check is diluted when only part of the training set is copied.
- The FR2 50-file DDL corpus, FR3 benchmark columns, p95 load tests, and MCP conformance tests.
