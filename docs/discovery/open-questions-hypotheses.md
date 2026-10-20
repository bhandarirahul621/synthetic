# Open questions: current hypotheses

| | |
|---|---|
| **Last updated** | 2026-10-20 |
| **Covers** | PRD §14 questions 1–5, plus the Phase 0 benchmark handoff |
| **Status** | Hypotheses only. Each one is settled by the discovery activity named below, then written back into PRD §14 with a version bump. |

A **hypothesis** is our best current guess, stated so that evidence can prove it wrong. Writing it down *before* the interviews protects us from **confirmation bias**: the habit of noticing only the evidence that agrees with us.

---

## Summary

| # | PRD §14 question | Current hypothesis | Confidence | Settled by |
|---|---|---|---|---|
| Q1 | Which industry for the beta? | **Fintech** (payments, lending, insurtech), with e-commerce as fallback | Low | Interview segment tally (commitment by industry), end of week 3 |
| Q2 | Schema-only enough, or sample-data learning from day one? | **Schema-only is enough to start**; sample-data learning ships in MVP but is not the lead | Medium | Interview question A3 tally (A20) |
| Q3 | Open-source the core engine? | **No.** Open-source the CLI, MCP server and report *format*; keep the hosted engine closed | Medium | Interviews A8/A14 + desk research; decided with `backend-data-platform-architect` |
| Q4 | Per seat, per row, or hybrid? | **Hybrid:** a flat per-workspace platform fee plus row-based usage, with a free tier | Medium | Interview A12 + price survey with qualified interviewees; pricing-page test in Phase 2 |
| Q5 | What privacy evidence will design partners' compliance teams accept? | A per-dataset report **plus** a methodology document and data-handling terms (retention, no-training, DPA). No team will accept it as legal certification. | Low | P3 interviews B4–B5 + mock-report review B9 (A19); thresholds set with `privacy-compliance-expert` |

---

## Q1. Which industry should the beta focus on first: fintech, health-tech or e-commerce?

**Recommendation:** Hypothesis = **fintech** (payments, lending, insurtech) at 200–5,000 employees. Keep e-commerce as the fallback. Don't decide until the week-3 tally.

**Reasoning:**
1. **Clear, valuable rare-event use case.** Fraud and chargebacks are rare in real data and must be boosted for testing and model training (PRD U6). The PRD's own example request is about fraud and refunds (§1).
2. **Relational, transaction-heavy schemas** (customers → accounts → transactions) play to our multi-table strength (G3, U3).
3. **Regulatory pressure makes the privacy report matter**, so fintech tests our differentiator (A19) directly.

**Main risk:** fintech security reviews may block a student project (A18, A26). Also, enterprise synthetic data vendors already sell to banks (MOSTLY AI's customer stories include Erste Group, a bank) ([mostly.ai](https://mostly.ai/), accessed 2026-10-20). E-commerce may have less friction but a weaker need for privacy evidence. Health-tech has the strongest privacy need but likely the slowest approvals (HIPAA questions go to `privacy-compliance-expert`).

**How it gets settled:** the [segment view](interview-guide.md#63-segment-view-answers-prd-14-q1) in the synthesis template. Pick the industry with the highest **average commitment score** (min. 4 interviews). Tie-break by number of design-partner candidates.
**Metric link:** activation (§10.2) and design partners using it weekly (§13 Phase 1).

---

## Q2. Is schema-only generation enough for most early users, or do they need sample-data learning from day one?

**Recommendation:** Hypothesis = **schema-only is enough for most early users, especially P2 (software/QA).** Keep sample-data learning (F1 "from sample data") in the MVP, but lead the onboarding and positioning with schema-first.

**Reasoning:**
1. **It removes the biggest adoption barrier.** Teams hesitate to upload sensitive samples to a cloud service (PRD §12). Schema-only lets a design partner start without a security review (A18).
2. **It differentiates us from platform bundling.** Snowflake's built-in generator starts from existing input tables ([Snowflake docs](https://docs.snowflake.com/en/user-guide/synthetic-data), accessed 2026-10-20), as does SDV's learning from data. Schema-first is a space they serve less.
3. **P2's job (test data for features) usually needs valid, realistic, relationally correct data, not a statistical twin of production.** That is still a hypothesis (A20).

**Main risk:** P1 (ML) users need real statistical shape for model training. If most interview stories are ML training, sample-data learning becomes essential. Local/in-VPC options would then matter; that architecture question goes to `backend-data-platform-architect`.

**How it gets settled:** interview question A3 ("Did you start from a schema, a sample, a production copy, or nothing?") and A13 ("Would an outside service ever be allowed to receive a sample?"). Rule: if ≥ 60% of the last-time stories could have started from a schema, the hypothesis holds.
**Metric link:** time-to-value < 10 min and activation ≥ 40% (§10.2).

---

## Q3. Should the core generation engine be open source to drive developer adoption?

**Recommendation:** Hypothesis = **don't open-source the generation engine. Do open-source the developer surface:** the CLI, the MCP server, the recipe format and the report *specification* (what each metric means and how it is computed).

**Reasoning:**
1. **Open-source engines already exist and are free:** MOSTLY AI's SDK, Synthcity and NVIDIA NeMo Data Designer are all Apache 2.0 ([competitive landscape §4](competitive-landscape.md#4-open-source-tools)). Another open engine would not stand out, and we would be giving away the part we plan to build ourselves (relational orchestrator and evaluator, PRD §9).
2. **An open CLI and MCP server lower adoption friction** where it matters for developer-led growth (PRD §11 channels; A12), and they are easy to list in the [official MCP Registry](https://registry.modelcontextprotocol.io/) (accessed 2026-10-20).
3. **An open report specification builds trust with P3.** Compliance teams can inspect exactly how scores are computed (A19) without us giving away the engine.

**Main risk:** developers may distrust a closed engine for privacy-sensitive work. Also note that licensing cuts both ways: SDV's Business Source License restricts use in a "Synthetic Data Service" ([SDV LICENSE](https://raw.githubusercontent.com/sdv-dev/SDV/main/LICENSE), accessed 2026-10-20). Our own engine choices must be checked by `backend-data-platform-architect`, with the legal reading by `privacy-compliance-expert`.

**How it gets settled:** interviews (A8 "What have you tried, and why did you keep or drop it?"; A14 "How did you discover the last dev tool?"). If ≥ half of P1/P2 say they *only* adopt open-source tools for this kind of work, revisit. Final decision jointly with `backend-data-platform-architect`.
**Metric link:** agent adoption ≥ 30% (§10.2) and CAC (A12).

---

## Q4. Should pricing be per seat, per row, or a hybrid?

**Recommendation:** Hypothesis = **hybrid: a flat monthly fee per workspace that includes a row allowance, plus metered usage above it, and a free tier.** Not per user.

**Reasoning:**
1. **AI agents aren't seats.** If ≥ 30% of jobs come through API/MCP (§10.2 target), per-seat pricing undercharges heavy automated use and overcharges light human users.
2. **The market uses usage-plus-base models.** Tonic Fabricate: $29/month including $25 of credits, then pay-as-you-go. DataCebo SDV Enterprise: $500/month per user + usage. Syntho deliberately advertises "no consumption-based charges" as a contrast. ([Tonic](https://www.tonic.ai/pricing), [DataCebo](https://datacebo.com/pricing/), [Syntho](https://www.syntho.ai/pricing/), all accessed 2026-10-20.) Buyers are used to a base fee plus usage.
3. **It protects the margin guardrail** (cost of goods < 20% of price per 1M rows, §10.3), because revenue rises with LLM and compute usage.

**Main risk:** usage pricing feels unpredictable to finance teams. Mitigate with spending caps (DataCebo advertises spending caps on its pricing page) and a clear free allowance.

**How it gets settled:** interview A12 (how they last bought a dev tool) plus a short **Van Westendorp survey** for qualified interviewees. It asks four questions: at what price is this too cheap to trust, a bargain, getting expensive, and too expensive. The answers give an acceptable price range. Then a pricing-page A/B test in Phase 2.
**Metric link:** free-to-paid conversion ≥ 4% (§10.2); first 20 paying workspaces (§13 Phase 2).
**PRD impact if confirmed:** §11 pricing table changes Pro from "~$49/user/month" to a per-workspace base fee plus usage.

---

## Q5. What level of privacy evidence will compliance teams at design partners accept?

**Recommendation:** Hypothesis = compliance leads will accept, for **non-production use of schema-only or sample-based synthetic data**: (a) the per-dataset Fidelity and Privacy Report (no-copy check, distance to closest record, membership-inference result, plain-English summary, PDF); **plus** (b) a short methodology document explaining the tests; **plus** (c) clear data-handling terms (retention, no training on customer data, deletion; PRD FR11, §8.1). They will **not** treat any of it as legal certification of anonymization, consistent with PRD §4.2.

**Reasoning:**
1. Competitors already sell "privacy reports" (Tonic Structural) and QA reports (Syntho), and Snowflake filters rows by distance-to-closest-record ([Tonic](https://www.tonic.ai/pricing), [Syntho](https://www.syntho.ai/pricing/), [Snowflake](https://docs.snowflake.com/en/user-guide/synthetic-data), accessed 2026-10-20). That suggests compliance buyers expect this kind of evidence, but it also means a report alone won't differentiate us.
2. P3's stated need is "proof that the synthetic data cannot be traced back to real individuals" (PRD §3.1). Schema-only data starts with no real individuals, which is the easiest case to approve.
3. Vendor-approval requirements (SOC 2, DPA) may matter more than the report itself (A02).

**Main risk:** compliance teams may require differential privacy (Phase 3 in our plan) or an external expert opinion before any use of sample-based synthesis.

**How it gets settled:** P3 interview questions B4, B5 and B7, plus the mock-report review B9 (A19). Rule: ≥ 2 of 3 P3s say they could approve with the report plus feasible additions. **Boundary:** what the report may claim, and what counts as "sufficient," must be defined with `privacy-compliance-expert`. Product strategy makes no legal claims.
**Metric link:** trust (% of jobs passing all privacy checks ≥ 98%, §10.2); guardrail of 0 privacy false negatives (§10.3).

---

## Handoff: benchmark datasets (owned by `qa-evaluation-engineer`)

PRD §13 Phase 0 requires "benchmark datasets chosen." **This decision belongs to `qa-evaluation-engineer`**, not product strategy. Product strategy contributes only (1) the use cases the suite must represent and (2) a candidate list to evaluate.

**Use cases the suite should cover (from PRD §5 and the personas):**
- Multi-table relational data with foreign keys and constraints (U3, FR4).
- Rare events / heavy class imbalance, e.g., fraud (U6).
- Mixed types: numeric, categorical, dates, short text, missing values (FR3).
- Schema-only inputs: realistic DDL files with PK/FK/CHECK constraints (U1, FR2's 50-file corpus).
- Scale tests near 1M rows × 20 columns (FR6) and the 1 GB upload limit (F1).
- At least one dataset per candidate beta industry: fintech, health, e-commerce (Q1).

**Candidate public datasets for QA to evaluate.** All licenses, terms of use and current availability are **unverified** and must be checked by `qa-evaluation-engineer`, with `privacy-compliance-expert` for any personal-data concerns. Some Kaggle competition datasets restrict commercial use.

| Candidate | Type | Why it might fit |
|---|---|---|
| UCI Adult (Census Income) | Single table, mixed types | Standard fidelity/utility baseline in synthetic-data papers |
| Credit Card Fraud Detection (ULB, Kaggle) | Single table, extreme imbalance | Rare-event amplification (U6); fintech |
| Default of Credit Card Clients (UCI) | Single table | Fintech classification utility test |
| UCI Bank Marketing | Single table, categorical-heavy | Fintech; categorical fidelity |
| Berka / PKDD'99 Czech financial dataset | Multi-table (accounts, clients, transactions, loans…) | Classic relational fintech benchmark (U3) |
| Olist Brazilian E-Commerce (Kaggle) | Multi-table (orders, items, payments, reviews, customers…) | E-commerce relational benchmark; includes short text (reviews) |
| Home Credit Default Risk (Kaggle) | Multi-table, large | Fintech relational + scale (check competition terms) |
| Instacart Market Basket (Kaggle) | Multi-table, millions of rows | E-commerce, scale (FR6) |
| CTU Prague Relational Learning Repository | Many multi-table databases | Breadth of relational schemas |
| Synthea (synthetic patient generator) | Multi-table health records (already synthetic) | Health-tech schemas without real patients |
| MIMIC-IV demo | Multi-table clinical | Health-tech realism; access terms must be checked carefully |
| Pagila (Postgres Sakila), Chinook, Northwind, AdventureWorks | Sample relational schemas with DDL | Schema-only path (U1) and the FR2 DDL corpus |
| TPC-H / TPC-DS data generators | Synthetic relational, scalable | Throughput testing (FR6), not fidelity |

**Handoff request to `qa-evaluation-engineer`:** choose the benchmark suite before the end of week 3, record the license check for each dataset, and note which datasets support the fidelity (≥ 85/100) and privacy (≥ 98% pass) targets in §10.2.

**Key takeaway:** write your guess down before you collect evidence, and decide in advance what result would change your mind.
