# Synthetic — Product Requirements Document

| | |
|---|---|
| **Product** | Synthetic: privacy-safe synthetic data for AI, analytics and software teams |
| **Status** | Draft v0.1 |
| **Owner** | Rahul Bhandari |
| **Last updated** | 2026-10-20 |

> **How to read this document.** Sections 1–4 explain *why* the product should exist. Sections 5–8 explain *what* we will build. Sections 9–12 explain *how* we will build it, measure it and manage the risks. Anything marked **[Assumption]** is a hypothesis we still need to check with real customers.

---

## 1. Summary

Synthetic generates realistic fake datasets that keep the statistical shape and the relationships of real data but contain no real person's information. Teams use it to:

1. **Build and test software** with realistic data instead of copies of production data.
2. **Train and evaluate AI models and agents** when real data is scarce, sensitive or missing rare cases.
3. **Share data** with vendors, contractors, students or other teams without a privacy review that takes months.

Our angle is **"synthetic data that AI agents can ask for."** Engineers and AI coding agents can call Synthetic through an API and an MCP server (Model Context Protocol, the standard way AI assistants connect to tools). For example: *"Give me 50,000 orders across 2,000 customers, including 2% fraud and some refunds in currencies other than USD."* Every dataset comes with a **Fidelity and Privacy Report** that a compliance team can file.

---

## 2. Problem

### 2.1 What teams do today

| Need | Common workaround | Why it fails |
|---|---|---|
| Realistic staging/test data | Copy production into staging, maybe mask a few columns | Privacy and regulatory exposure; masked data still leaks identities through combinations of fields |
| Test data for new features | Hand-written fixtures, Faker-style random values | Unrealistic distributions, broken relationships between tables, no edge cases |
| Training data for ML / AI | Wait for data access approvals; collect more data | Takes weeks to months; rare events (fraud, failures) are underrepresented |
| Evaluating AI agents | Small hand-made test sets | Too few cases, no coverage of messy real-world inputs |
| Sharing data externally | Legal review, NDAs, aggregated extracts | Slow, and aggregates lose the row-level detail people need |

### 2.2 Why now (market drivers)

- **Regulation is tightening.** GDPR, US state privacy laws (CCPA/CPRA and others), HIPAA, and the EU AI Act's data-governance duties for high-risk AI systems all make "just copy production" harder to defend.
- **The AI build-out needs data.** Companies building models and agents need training and evaluation data faster than governance processes can approve real data.
- **AI agents now write and test code.** Coding agents generate tests and scaffolding all day, and they need realistic data on demand, through a tool interface rather than a web form.
- **The market is consolidating.** Early leaders have been acquired or have open-sourced their core engines, which leaves room for a focused, self-serve, agent-first product. **[Assumption — validate with competitive research]**

---

## 3. Target users

### 3.1 Primary personas

**P1 — "Dana," Data / ML Engineer (mid-market, regulated industry)**
- Works at a fintech, insurer, health-tech or e-commerce company with 200–5,000 employees.
- Needs training and test data but is blocked by data access requests.
- Success for Dana: a realistic dataset today, plus a report that shows Legal it is safe.

**P2 — "Sam," Software Engineer / QA**
- Builds features against a relational database (Postgres, MySQL, Snowflake).
- Wants staging environments that behave like production, including edge cases.
- Increasingly works through an AI coding agent that should be able to fetch data itself.

**P3 — "Priya," Privacy / Compliance Lead (approver, not daily user)**
- Must approve any use of personal data.
- Needs proof that the synthetic data cannot be traced back to real individuals.

### 3.2 Secondary personas (later phases)
- **Analytics educators and students:** realistic business datasets for coursework without privacy issues.
- **AI product teams:** synthetic conversations, documents and scenarios for evaluating agents.

### 3.3 Not our customers (for now)
- Large enterprises that need on-premises installs with long procurement cycles (Phase 3 at the earliest).
- Users who need synthetic images, video or audio.

---

## 4. Goals and non-goals

### 4.1 Goals
1. **G1 — Fast time-to-value:** a new user generates a usable dataset in under 10 minutes.
2. **G2 — Trustworthy output:** every dataset ships with measured fidelity and privacy scores.
3. **G3 — Relational correctness:** multi-table data keeps keys, joins and business rules intact.
4. **G4 — Agent-native access:** everything in the UI is also available through the API, SDK and MCP.
5. **G5 — Self-serve revenue:** users can start free and upgrade without talking to sales.

### 4.2 Non-goals (MVP)
- Images, audio, video or free-form long documents.
- Real-time streaming data generation.
- Replacing a full data-masking or tokenization product.
- Formal legal certification of anonymization. We provide evidence, not legal advice.

---

## 5. Key use cases (user stories)

| ID | As a… | I want to… | So that… | Priority |
|---|---|---|---|---|
| U1 | Software engineer | describe a schema in plain English or upload a SQL DDL file and get realistic data | I can test a feature without production data | P0 |
| U2 | Data engineer | upload a sample of real data and get a synthetic copy with the same statistical shape | I can share or train on it safely | P0 |
| U3 | Data engineer | generate several related tables with foreign keys intact | joins and reports work as in production | P0 |
| U4 | Any user | see a fidelity and privacy report for each dataset | I can trust the data and show it to compliance | P0 |
| U5 | Engineer using an AI agent | have my agent request datasets through MCP or the API | data generation fits into automated workflows | P0 |
| U6 | ML engineer | boost rare events (e.g., fraud to 5%) or add edge cases | my model and tests cover situations real data rarely shows | P1 |
| U7 | Data engineer | write output directly to Postgres, Snowflake, BigQuery or S3 | I skip manual file handling | P1 |
| U8 | Team lead | save generators as reusable, versioned "recipes" | the team regenerates consistent data in CI/CD | P1 |
| U9 | Compliance lead | apply differential privacy with a chosen privacy budget | we get a mathematical privacy guarantee for sensitive data | P2 |
| U10 | AI product team | generate synthetic conversations or support tickets tied to the tabular data | we can evaluate AI agents on realistic scenarios | P2 |

---

## 6. Product scope and features

### 6.1 MVP (Phase 1) — "Generate, trust, use"

**F1. Three ways to start a dataset**
- **From a description:** a natural-language prompt, which an LLM turns into a schema the user can edit.
- **From a schema:** upload SQL DDL, a dbt model, or a JSON/YAML schema.
- **From sample data:** upload CSV or Parquet (up to 1M rows / 1 GB in MVP). We learn its distributions and correlations, then generate new rows.

**F2. Schema editor**
- Edit tables, columns, types, value ranges and categories.
- Define relationships (one-to-many, many-to-many) and constraints (unique, not null, `end_date > start_date`).
- Mark columns as personal data (PII). These are always generated fresh, never copied.

**F3. Generation engine**
- Statistical and machine-learning models for tabular data (e.g., copula and deep generative models), picked automatically based on data size and type.
- An LLM fills realistic text fields (product names, addresses, short notes) while staying consistent with the other columns.
- Relational generation: parent tables first, then children, so keys and row counts per parent stay realistic.
- Deterministic seeds, so the same recipe and seed always give the same output.

**F4. Fidelity and Privacy Report** (attached to every dataset)
- **Fidelity:** how closely column distributions, correlations and cross-table statistics match the source or the spec, rolled into one 0–100 score.
- **Utility:** train-on-synthetic, test-on-real comparison, when sample data was provided.
- **Privacy:** checks that no source row was copied, distance from each synthetic row to its closest real row, and a membership-inference test (can an attacker tell whether a real person was in the source data?).
- Clear pass/warn/fail signals, a plain-English summary, and PDF export.

**F5. Export and delivery**
- Download as CSV, Parquet, JSON or SQL inserts.
- Direct write to Postgres (MVP). Other connectors arrive in Phase 2.

**F6. Developer and agent access**
- REST API and Python SDK.
- **MCP server** with tools such as `create_dataset`, `get_report` and `list_recipes`, usable from Claude Code and other MCP clients.
- CLI for CI pipelines: `synthetic generate --recipe orders --rows 10000`.

**F7. Accounts and billing**
- Email / Google / GitHub sign-in, workspaces and basic roles (Owner, Member).
- Free tier with usage limits; paid plans through Stripe.

### 6.2 Phase 2 — "Fit into the stack"
- Snowflake, BigQuery, Databricks, MySQL and S3 connectors.
- Versioned recipes, scheduled regeneration and a GitHub Action.
- Rare-event amplification and an edge-case "scenario pack" library (fraud, churn, data-quality errors).
- SSO (SAML), audit logs and team roles.

### 6.3 Phase 3 — "Enterprise and AI evaluation"
- Differential privacy mode with a configurable privacy budget.
- Deployment inside the customer's own cloud (VPC), so data never leaves it.
- Synthetic text and conversation generation linked to tabular records, for evaluating AI agents.
- Time-series and event-log data.

---

## 7. User experience

### 7.1 Core flow (MVP)
1. **Sign up**, then pick a starting point: *Describe*, *Upload schema* or *Upload sample*.
2. **Review the schema.** The editor shows tables and relationships, with suggested constraints highlighted.
3. **Preview.** See 100 rows within 10 seconds and adjust before the full run.
4. **Generate.** Choose the row count; a progress bar tracks the job.
5. **Review the report.** Scores sit at the top, with details underneath.
6. **Use the data.** Download it, push it to a database, or copy an API/MCP snippet.

### 7.2 UX principles
- **Preview before commit:** never make users wait for a full job to find a mistake.
- **Explain every score** in plain English, with a "Why?" link.
- **UI and API parity:** anything clickable is also callable.
- **Safe by default:** privacy checks always run, and flagged PII columns are never copied.

---

## 8. Functional requirements (MVP acceptance criteria)

| ID | Requirement | Acceptance criteria |
|---|---|---|
| FR1 | Natural-language schema creation | A prompt returns an editable schema of up to 20 tables in under 15 s, valid against our schema format |
| FR2 | DDL import | Postgres and MySQL DDL with PK/FK and CHECK constraints parse correctly in at least 95% of a 50-file test corpus |
| FR3 | Sample-data learning | Accepts CSV/Parquet up to 1 GB; correctly detects column types in at least 95% of benchmark columns |
| FR4 | Relational integrity | 100% of generated foreign keys resolve; declared constraints hold on every row |
| FR5 | Preview | 100-row preview returned in under 10 s (p95) |
| FR6 | Generation throughput | 1M rows × 20 columns generated in under 5 min (p95) on the standard tier |
| FR7 | Report | A report is produced for every job, containing a fidelity score, privacy checks and a plain-English summary |
| FR8 | No source-row copying | 0 synthetic rows exactly match a source row (when sample data is used) |
| FR9 | API/SDK/MCP | Every MVP action is available through the REST API; the MCP server passes the MCP conformance tests |
| FR10 | Reproducibility | Same recipe + seed + engine version gives byte-identical output |
| FR11 | Data deletion | Uploaded source data is deleted within 24 h of job completion by default (configurable to 0–30 days) |

### 8.1 Non-functional requirements
- **Security:** encryption in transit (TLS 1.2+) and at rest; isolated job workers; source data never used to train shared models.
- **Availability:** 99.5% monthly uptime for the API in MVP; 99.9% target for paid plans in Phase 2.
- **Compliance roadmap:** SOC 2 Type I within 6 months of launch, Type II within 12. **[Assumption]**
- **Accessibility:** web app meets WCAG 2.1 AA.
- **Observability:** every job logs engine version, seed, parameters and timings for audit and debugging.

---

## 9. Proposed technical approach (for discussion)

```
┌─────────────┐   ┌─────────────┐   ┌──────────────┐
│  Web app    │   │ REST API /  │   │  MCP server  │
│  (Next.js)  │   │ SDK / CLI   │   │  (agents)    │
└──────┬──────┘   └──────┬──────┘   └──────┬───────┘
       └─────────────────┼─────────────────┘
                  ┌──────▼──────┐
                  │ API service │  auth, workspaces, billing
                  │  (FastAPI)  │
                  └──────┬──────┘
          ┌──────────────┼───────────────┐
   ┌──────▼─────┐  ┌─────▼──────┐  ┌─────▼───────┐
   │ Postgres   │  │ Job queue  │  │ Object store│
   │ (metadata) │  │            │  │ (S3)        │
   └────────────┘  └─────┬──────┘  └─────────────┘
                  ┌──────▼──────────────────────┐
                  │ Generation workers (Python) │
                  │ • schema planner (LLM)      │
                  │ • tabular models            │
                  │ • relational orchestrator   │
                  │ • text filler (LLM)         │
                  │ • evaluator (fidelity +     │
                  │   privacy)                  │
                  └─────────────────────────────┘
```

- **Language:** Python for generation and evaluation (strongest data and ML ecosystem); TypeScript for the web app.
- **Build vs. buy:** start with proven open-source tabular synthesis libraries, wrapped behind our own engine interface so models can be swapped out; build the relational orchestrator and the evaluator ourselves, because that is where we differentiate.
- **LLM use:** schema planning and text fields only. Numbers and statistical structure come from statistical models, which are more faithful and cheaper.

---

## 10. Success metrics

### 10.1 North-star metric
**Weekly datasets generated and used.** A dataset counts as used when it is downloaded, pushed to a database, or fetched through the API or MCP. This measures delivered value, not sign-ups.

### 10.2 Supporting metrics (targets for 90 days after launch) **[Assumption — set baselines in beta]**

| Category | Metric | Target |
|---|---|---|
| Activation | % of sign-ups who generate a dataset in their first session | ≥ 40% |
| Time-to-value | Median time from sign-up to first full dataset | < 10 min |
| Quality | Median fidelity score on benchmark datasets | ≥ 85 / 100 |
| Trust | % of jobs passing all privacy checks | ≥ 98% |
| Agent adoption | % of generation jobs started via API/SDK/MCP | ≥ 30% |
| Retention | Week-4 retention of activated users | ≥ 25% |
| Revenue | Free-to-paid conversion of activated workspaces | ≥ 4% |

### 10.3 Guardrail metrics
- Privacy-check false negatives found in red-team testing: **0** tolerated.
- Cost of goods per 1M rows stays below 20% of the price charged for them.

---

## 11. Go-to-market and pricing (initial hypothesis)

| Plan | Price | Includes |
|---|---|---|
| **Free** | $0 | 100k rows/month, 3 recipes, CSV export, community support |
| **Pro** | ~$49/user/month | 5M rows/month, API/MCP, Postgres push, saved recipes |
| **Team** | ~$399/month + usage | Connectors, scheduling, SSO, audit logs |
| **Enterprise** | Custom | VPC deployment, differential privacy, SLA, DPA |

**Channels:** developer-led growth (docs, open-source CLI, listings in MCP tool directories), content on "test data without production data," integrations with dbt and CI tools, and later outbound sales to regulated mid-market companies.

**Positioning statement:** *For data and engineering teams in regulated industries who need realistic data without privacy risk, Synthetic is a synthetic-data platform that AI agents and humans can use in minutes. Unlike masking tools or general-purpose fakers, Synthetic preserves real relationships across tables and proves its privacy with every dataset.*

---

## 12. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Synthetic data leaks real records (overfitting) | Severe: destroys trust, legal exposure | Mandatory privacy evaluator, no-copy checks, external red-team before GA, DP mode in Phase 3 |
| Fidelity not good enough for ML use | Users churn after trying it | Public benchmark suite, utility tests in each report, engine swapping |
| Competitors with large-company backing bundle synthetic data into platforms | Pricing pressure | Focus on self-serve, agent-native workflows and relational depth; integrate with platforms instead of competing on breadth |
| LLM costs grow with usage | Margin erosion | Use LLMs only for schemas and text; cache; route to smaller models where quality allows |
| Customers won't upload sensitive samples to a cloud service | Slower enterprise adoption | Schema-only mode needs no real data; clear retention policy; VPC deployment in Phase 3 |
| Regulatory interpretation of "anonymous" varies by jurisdiction | Compliance teams hesitate | Provide evidence and documentation, avoid legal claims, partner with privacy counsel for templates |

---

## 13. Release plan

| Phase | Timeline (from kickoff) | Exit criteria |
|---|---|---|
| **0 — Discovery** | Weeks 0–3 | 15 customer interviews; 3 design partners signed; benchmark datasets chosen |
| **1 — MVP / private beta** | Weeks 4–14 | FR1–FR11 met; 3 design partners using it weekly |
| **2 — Public beta** | Weeks 15–22 | Self-serve billing live; activation ≥ 30%; first 20 paying workspaces |
| **3 — GA** | Week 23+ | SOC 2 Type I; uptime target met for 30 days; Phase 2 connectors shipped |

---

## 14. Open questions

1. Which industry should the beta focus on first: fintech, health-tech or e-commerce?
2. Is schema-only generation (no real data uploaded) enough for most early users, or do they need sample-data learning from day one?
3. Should the core generation engine be open source to drive developer adoption?
4. Should pricing be per seat, per row, or a hybrid?
5. What level of privacy evidence will compliance teams at design partners accept?

---

## 15. Glossary

- **Synthetic data:** artificially generated data that mimics the statistical properties of real data without containing real records.
- **Fidelity:** how statistically similar synthetic data is to the real data or the intended spec.
- **Utility:** how well synthetic data performs on a real task, such as training a model that is then tested on real data.
- **Membership inference attack:** a test of whether someone can tell that a specific real person's record was in the training data.
- **Differential privacy (DP):** a mathematical guarantee that limits how much any single person's data can influence the output.
- **MCP (Model Context Protocol):** an open standard that lets AI assistants call external tools and data sources.
- **Foreign key:** a column that links a row in one table to a row in another, e.g., `orders.customer_id → customers.id`.
- **Recipe:** a saved, versioned configuration for generating a dataset.
