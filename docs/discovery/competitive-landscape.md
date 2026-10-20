# Competitive landscape: synthetic data (October 2026)

| | |
|---|---|
| **Research date** | All sources accessed **2026-10-20** unless noted |
| **Prepared by** | product-strategist agent (desk research) |
| **Scope** | Tabular and relational synthetic data for testing, analytics and AI; open-source tools; platform bundling; MCP/agent offerings |

**Sourcing rule.** Every factual claim links to its source. "Vendor-stated" means the claim comes from the company's own marketing. **"Unverified"** means we could not confirm it from a primary or reliable secondary source. Treat unverified items as leads, not facts.

## Terms used in this document

- **Test data management (TDM):** tools that give software teams safe data for development and testing. Usually combines *subsetting* (copying a small, consistent slice of production), *masking* (replacing sensitive values) and, increasingly, synthesis.
- **Masking / de-identification:** changing real records so individuals are harder to identify. The rows are still real rows. Synthesis creates new rows.
- **Referential integrity:** foreign keys still point to existing rows after the data is changed or generated.
- **Business Source License (BSL):** a "source-available" license. You can read and use the code, but some commercial uses are restricted until a "change date," after which it becomes open source.
- **MCP (Model Context Protocol):** the open standard that lets AI assistants call external tools (PRD §15).
- **Bundling:** a large platform includes a feature for free or as part of its product. That makes it hard for a stand-alone vendor to charge for the same feature, the way free phone cameras undercut cheap digital cameras.

---

## 1. Summary

**Recommendation:** Keep the core product idea, but stop leading with "agent-first." Two competitors already ship MCP servers, so that is no longer a differentiator. Lead with **schema-first, reproducible, multi-table test data that runs in CI, with a privacy evidence report that compliance can file, and no production data required.** Price between hobby tools (~$29/month) and enterprise tools (~$500/user/month). (Details in [§6 Gap analysis](#6-gap-analysis-against-prd-11-positioning).)

**Reasoning, with the five most important findings:**

1. **Consolidation is real and well documented.** NVIDIA acquired Gretel (reported March 2025) ([TechCrunch](https://techcrunch.com/2025/03/19/nvidia-reportedly-acquires-synthetic-data-startup-gretel/)). SAS acquired Hazy's principal software assets (November 2024) ([SAS](https://www.sas.com/en_gb/news/press-releases/2024/november/hazy-syntheticdata.html)). KPMG agreed to acquire YData's IP and technology assets (October 2025) ([KPMG](https://kpmg.com/us/en/media/news/kpmg-accelerates-ai-strategy-with-ydata.html)). Syntho acquired the MOSTLY AI brand (June 2026) ([Syntho](https://www.syntho.ai/syntho-acquires-mostly-ai-trademark-and-related-assets/)). Tonic.ai acquired Fabricate (April 2025) ([Tonic.ai](https://www.tonic.ai/press-releases/tonic-ai-acquires-fabricate-expanding-its-leadership-in-synthetic-data)). Neosync was acquired by Grow Therapy, and its open-source repository is no longer maintained ([GitHub](https://github.com/nucleuscloud/neosync)).
2. **The "agent-first, self-serve" gap is narrower than PRD §2.2 assumed.** Tonic Fabricate has a free tier, a $29/month Plus plan and an MCP server ([Tonic pricing](https://www.tonic.ai/pricing); [Fabricate MCP docs](https://docs.tonic.ai/fabricate/fabricate-api/using-the-fabricate-mcp-server)). MOSTLY AI launched an MCP server in beta with 19 tools in v4.8.0 (June 26, 2025) ([MOSTLY AI docs](https://mostly.ai/docs/whats-new)).
3. **The most popular open-source tabular library cannot simply be wrapped into our hosted service.** SDV's license forbids use "for a Synthetic Data Service" until four years after each release ([SDV LICENSE](https://raw.githubusercontent.com/sdv-dev/SDV/main/LICENSE)). Permissive alternatives exist: MOSTLY AI's SDK ([Apache 2.0](https://github.com/mostly-ai/mostlyai)), Synthcity ([Apache 2.0](https://github.com/vanderschaarlab/synthcity)) and NVIDIA's NeMo Data Designer ([Apache 2.0](https://github.com/NVIDIA-NeMo/DataDesigner)). The legal reading belongs to `privacy-compliance-expert`; the architecture decision belongs to `backend-data-platform-architect`.
4. **Platforms already bundle synthetic data.** Snowflake has a built-in `GENERATE_SYNTHETIC_DATA` procedure. It takes up to five tables, keeps join keys consistent and has an optional privacy "similarity filter" ([Snowflake docs](https://docs.snowflake.com/en/user-guide/synthetic-data)). Databricks generates synthetic evaluation sets for AI agents ([Databricks docs](https://docs.databricks.com/aws/en/agents/agent-evaluation/synthesize-evaluation-set)). NVIDIA offers NeMo Data Designer and NeMo Safe Synthesizer ([NVIDIA](https://www.nvidia.com/en-us/use-cases/synthetic-data-generation-for-agentic-ai/)).
5. **Public price points form a ladder with a gap in the middle.** Tonic Fabricate: $0 and $29/month ([Tonic](https://www.tonic.ai/pricing)). DataCebo SDV Enterprise: $500/month per user plus usage, with $250/month add-on bundles ([DataCebo](https://datacebo.com/pricing/)). Tonic Structural, Syntho and K2view: quote-only. Our ~$49 Pro hypothesis sits in the gap.

**Main risk:** an incumbent (Tonic, or a platform like Snowflake) closes the remaining gaps faster than a solo founder can.

---

## 2. Market size: handle with care

Analyst estimates differ a lot, because each firm defines "the market" differently. Use them only as context, never as a forecast for Synthetic.

| Publisher | Estimate | Source |
|---|---|---|
| Global Market Insights | USD 310.5M in 2024; 35.2% CAGR 2025–2034 | [gminsights.com](https://www.gminsights.com/industry-analysis/synthetic-data-generation-market) |
| Research Nester | USD 447.16M in 2025; 34.7% CAGR to USD 8.79B by 2035 | [researchnester.com](https://www.researchnester.com/reports/synthetic-data-generation-market/5711) |
| Gartner prediction (as quoted by NVIDIA) | "By 2026, 75% of businesses will use GenAI to create synthetic customer data, up from less than 5% in 2023." | Quoted on [NVIDIA's use-case page](https://www.nvidia.com/en-us/use-cases/synthetic-data-generation-for-agentic-ai/). We did not read the original Gartner report. |

**CAGR** (compound annual growth rate) is the steady yearly growth rate that would take a value from its start to its end. A **bottom-up** estimate (number of target companies × likely spend) is more useful to us than any of these numbers, and we can build one from interview data in Phase 0.

---

## 3. Vendors

| Vendor | What they offer | Target customer | Pricing (public?) | Notable recent events | MCP / agent offering |
|---|---|---|---|---|---|
| **MOSTLY AI** (now "MOSTLY AI, powered by Syntho") | "Data Intelligence Platform": synthetic, mock and simulated data, plus an AI assistant for analysis. Open-source Synthetic Data SDK (TabularARGN model, differential privacy, multi-table). Runs on Kubernetes/OpenShift. ([mostly.ai](https://mostly.ai/); [SDK on GitHub](https://github.com/mostly-ai/mostlyai)) | Enterprise data and AI teams (customer stories name Swiss Post and Erste Group) ([mostly.ai](https://mostly.ai/)) | Not verified. The pricing page returned 404 on 2026-10-20 ([mostly.ai/pricing](https://mostly.ai/pricing)). A third-party guide says credit-based; **unverified**. | SDK open-sourced under Apache 2.0, January 2025 ([insideHPC](https://insidehpc.com/2025/02/mostly-ai-releases-open-source-toolkit-for-synthetic-data-creation/)). Syntho acquired the MOSTLY AI **brand** on June 9, 2026 ([Syntho](https://www.syntho.ai/syntho-acquires-mostly-ai-trademark-and-related-assets/)). What happened to the team and platform is **unverified**. | **Yes.** MCP server beta, 19 tools, for Claude Desktop/Web, VS Code and Cursor (v4.8.0, June 26, 2025) ([docs](https://mostly.ai/docs/whats-new)). The listed GitHub repo `mostly-ai/mostlyai-mcp-server` returned 404 on 2026-10-20, so its current status is **unverified**. |
| **Syntho** | One platform with AI-generated synthetic data, "synthetic data masking" and rule-based generation; subsetting; sensitivity scanner; QA report. Self-hosted/on-prem via Docker. ([pricing](https://www.syntho.ai/pricing/); [announcement](https://www.syntho.ai/syntho-acquires-mostly-ai-trademark-and-related-assets/)) | Organizations moving synthetic data "to production": test data, demo data, data sharing (vendor-stated) | Quote-only, three tiers (Basic/Standard/Ultimate), feature-based with "no consumption-based charges" ([pricing](https://www.syntho.ai/pricing/)) | Acquired MOSTLY AI brand, June 2026 (above) | None found on the pricing page. No other evidence found. |
| **Gretel → NVIDIA** | Gretel's platform was folded into NVIDIA. gretel.ai now redirects to NVIDIA's "Synthetic Data Generation for Agentic AI" page, which offers **NeMo Data Designer** (LLM-driven dataset design, Apache 2.0) and **NeMo Safe Synthesizer** (privacy-preserving synthetic tabular data, optional differential privacy) ([redirect observed 2026-10-20](https://gretel.ai/); [NVIDIA](https://www.nvidia.com/en-us/use-cases/synthetic-data-generation-for-agentic-ai/); [Data Designer GitHub](https://github.com/NVIDIA-NeMo/DataDesigner); [Safe Synthesizer docs](https://docs.nvidia.com/nemo/microservices/latest/safe-synthesizer/about/data-synthesis.html)) | AI/LLM developers building models and agents | Data Designer is open source. Safe Synthesizer pricing not found. | Acquisition reported March 2025: "nine figures," above Gretel's last $320M valuation, ~80 employees (TechCrunch citing Wired) ([TechCrunch](https://techcrunch.com/2025/03/19/nvidia-reportedly-acquires-synthetic-data-startup-gretel/)). The claim that Data Designer descends directly from Gretel's product is **unverified** (one blog asserts it). | Agent-focused (synthetic data *for training/evaluating* agents). No MCP server found. |
| **Tonic.ai** | Three products: **Structural** (de-identification, subsetting with referential integrity, privacy reports), **Fabricate** (chat-based "Data Agent" generating relational DBs and unstructured files from scratch; mock APIs) and **Textual** (unstructured-text redaction/synthesis) ([pricing](https://www.tonic.ai/pricing)) | Software and AI engineering teams. Structural targets enterprise; Fabricate reaches individuals. | **Fabricate:** Free $0 ($5 credits/month); Plus $29/month ($25 credits + pay-as-you-go); Enterprise custom. **Structural:** Professional/Enterprise custom, priced by source-data volume. **Textual:** pay-as-you-go per 1,000 words. Tonic says it has a SOC 2 Type II report and signs BAAs for Enterprise. ([pricing](https://www.tonic.ai/pricing)) | Acquired Fabricate from Mockaroo, April 2025 ([press release](https://www.tonic.ai/press-releases/tonic-ai-acquires-fabricate-expanding-its-leadership-in-synthetic-data)) | **Yes.** Fabricate MCP server (OAuth or API key, JSON-RPC) for Claude, Cursor, VS Code ([docs](https://docs.tonic.ai/fabricate/fabricate-api/using-the-fabricate-mcp-server); [blog](https://www.tonic.ai/blog/generate-synthetic-data-in-claude-cursor)). Tonic also says MCP servers exist for Textual and are in development for Structural. That comes from a Tonic-authored comparison page, so it is vendor-stated ([Tonic vs Synthesized](https://www.tonic.ai/vs/synthesized)). |
| **DataCebo (SDV)** | Synthetic Data Vault: single-table, multi-table and sequential synthesis. SDV Enterprise adds models, data types, connectors and "bundles" (constraint-augmented generation, differential privacy). ([GitHub](https://github.com/sdv-dev/SDV); [pricing](https://datacebo.com/pricing/)) | Data science and engineering teams that run it on their own infrastructure | **SDV Community:** free, "limited commercial use: Business Source License." **SDV Enterprise Base:** $500/month + usage (per user). **Bundles:** $250/month per bundle + usage. ([pricing](https://datacebo.com/pricing/)) | SDV 2.0 released Sept 15, 2026: "generative relational models" trained on an organization's own databases, with automated schema/relationship detection (press release) ([AIwire](https://www.hpcwire.com/aiwire/2026/09/15/datacebo-releases-sdv-2-0-for-building-generative-relational-models-of-enterprise-data/)) | No official MCP server found. Community-built SDV MCP servers and tutorials exist ([Daily Dose of DS tutorial](https://www.dailydoseofds.com/p/hands-on-mcp-powered-synthetic-data-generator)). |
| **Hazy → SAS** | Hazy's synthetic data software integrated into **SAS Data Maker** (preview announced for early 2025) ([SAS](https://www.sas.com/en_gb/news/press-releases/2024/november/hazy-syntheticdata.html)) | SAS enterprise customers, especially regulated sectors (health care, finance) | Not public | SAS acquired Hazy's principal software assets, November 2024 ([SAS](https://www.sas.com/en_gb/news/press-releases/2024/november/hazy-syntheticdata.html)) | None found |
| **YData → KPMG** | Data profiling and synthetic data platform ("Fabric") and SDK. Partnership with Databricks (2024) ([YData press release](https://www.newswire.com/news/ydata-announces-partnership-with-databricks-to-empower-enterprises-22413926)) | Was data science teams; now KPMG's internal Synthetic Data Center of Excellence for Audit, Tax and Advisory work | Not public. ydata.ai returned 404 on 2026-10-20; whether the product is still sold to the public is **unverified**. | KPMG signed a definitive agreement to acquire YData's IP and technology assets, Oct 16, 2025; founders to join KPMG ([KPMG](https://kpmg.com/us/en/media/news/kpmg-accelerates-ai-strategy-with-ydata.html)) | None found |
| **K2view** | Entity-based test data management: AI and rules-based generation, data cloning, masking, cross-system subsetting with referential integrity ([K2view](https://www.k2view.com/solutions/synthetic-data-generation-tools/)) | Large, complex enterprises (vendor names Walmart, Verizon, Vodafone, BBVA) | Not public ("Start Free" button; terms not shown) | No specific 2026 event verified | **Partly.** Markets a "data agent" for test data and "MCP data integration," turning data products into MCP servers ([K2view](https://www.k2view.com/solutions/synthetic-data-generation-tools/); [MCP page](https://www.k2view.com/solutions/mcp-integration/)), vendor-stated. Whether synthetic generation is exposed through MCP is **unverified**. |
| **Synthesized** | Test data platform (synthesis, masking, subsetting) | Dev/QA in finance, insurance, health care (third-party profile) | Not public. Usage-based per third-party profiles; **unverified** ([Sacra](https://sacra.com/c/synthesized)) | None verified | Tonic says Synthesized is "bundled breadth." That is vendor-authored competitive marketing ([Tonic](https://www.tonic.ai/vs/synthesized)). **Unverified.** |
| **Seedfast** (small, agent-native) | MCP server that writes connected, realistic rows into your own database from one call | Developers using coding agents | Free plan + monthly credits (per article) | The article listing it appears to be written by Seedfast itself (its images are hosted on seedfa.st), so treat it as vendor-stated ([DEV Community](https://dev.to/mikh-shytsko/mcp-servers-for-test-data-what-exists-and-what-each-one-does-30ol)) | **Yes** (MCP-only product) |
| **Neosync** (discontinued) | Was open-source anonymization + synthetic data for dev/staging (Postgres, MySQL, S3) | Developers | MIT-licensed open source | Acquired by Grow Therapy; repository "no longer actively maintained" ([GitHub](https://github.com/nucleuscloud/neosync)) | n/a |

---

## 4. Open-source tools

| Tool | What it does | License | Notes for Synthetic | Source |
|---|---|---|---|---|
| **SDV** | ML-based single-table, multi-table and sequential synthesis | **Business Source License.** The Additional Use Grant excludes a "Synthetic Data Service" (a commercial offering letting third parties benefit from its synthesis features). Each release converts to MIT four years after its release date. | **Cannot** be the engine of our hosted service without a commercial agreement, on a plain reading. Needs legal review (`privacy-compliance-expert`). | [LICENSE](https://raw.githubusercontent.com/sdv-dev/SDV/main/LICENSE); [GitHub](https://github.com/sdv-dev/SDV) |
| **MOSTLY AI Synthetic Data SDK** | TabularARGN model; differential privacy; multi-table; local training | Apache 2.0 | Permissive. Strong candidate for the engine, but now owned by a competitor's brand group (Syntho), so check maintenance. | [GitHub](https://github.com/mostly-ai/mostlyai); [mostly.ai](https://mostly.ai/) |
| **Synthcity** | Generate and evaluate synthetic tabular data (also time series, survival analysis, images); many model families | Apache 2.0 | Permissive. Useful for both models and evaluation metrics. Academic origin (NeurIPS 2023 benchmark track). | [GitHub](https://github.com/vanderschaarlab/synthcity); [NeurIPS paper](https://papers.nips.cc/paper_files/paper/2023/hash/09723c9f291f6056fd1885081859c186-Abstract-Datasets_and_Benchmarks.html) |
| **NVIDIA NeMo Data Designer** | LLM-driven, declarative dataset design (text, code, structured outputs, samplers), with validators and LLM-as-judge scoring | Apache 2.0 | Overlaps with our "describe it in English" path (F1) and text filling (F3). A possible component or a free substitute. | [GitHub](https://github.com/NVIDIA-NeMo/DataDesigner); [arXiv](https://arxiv.org/pdf/2609.17699) |
| **Faker** (Python) | Random fake values (names, addresses, etc.); no statistical learning, no cross-table logic | MIT | The "general-purpose faker" named in our positioning. Free and very widely used (~19.5k GitHub stars on 2026-10-20). | [GitHub](https://github.com/joke2k/faker) |
| **Neosync** | Anonymization + synthetic data sync | MIT | Unmaintained after acquisition | [GitHub](https://github.com/nucleuscloud/neosync) |

---

## 5. Platform bundling

| Platform | Built-in capability | Implication for Synthetic | Source |
|---|---|---|---|
| **Snowflake** | `SNOWFLAKE.DATA_PRIVACY.GENERATE_SYNTHETIC_DATA`: up to 5 input tables per call, ≤ 100 columns and ≤ 14M rows per table, minimum 20 distinct rows. Consistent `join_key` values across tables. Optional `similarity_filter` removes rows too close to real ones (nearest-neighbor distance ratio and distance to closest record). | Snowflake customers with sample data in Snowflake already have a "good enough" option. Our edge is schema-only generation, Postgres/CI workflows and a compliance-ready report. Ask interviewees on Snowflake whether they have tried it (A29). | [Snowflake user guide](https://docs.snowflake.com/en/user-guide/synthetic-data); [procedure reference](https://docs.snowflake.com/en/sql-reference/stored-procedures/generate_synthetic_data) |
| **Databricks** | `generate_evals_df` (in the `databricks-agents` package) synthesizes evaluation sets from documents for testing retrieval agents | Covers part of our Phase 3 "AI evaluation" idea (U10) for Databricks users | [Databricks docs](https://docs.databricks.com/aws/en/agents/agent-evaluation/synthesize-evaluation-set) |
| **NVIDIA NeMo** | Data Designer (open source) and Safe Synthesizer (private synthetic tabular data; docs list an 80GB+ VRAM GPU for training in one version) | Free, well-funded tooling for AI teams. Heavy GPU needs make it a poor fit for small engineering teams, a possible opening for us. | [NVIDIA](https://www.nvidia.com/en-us/use-cases/synthetic-data-generation-for-agentic-ai/); [Safe Synthesizer docs](https://docs.nvidia.com/nemo/microservices/latest/safe-synthesizer/getting-started.html) |
| **SAS** | Hazy technology inside SAS Data Maker / Viya | Bundled for existing SAS enterprise customers; not our segment | [SAS](https://www.sas.com/en_gb/news/press-releases/2024/november/hazy-syntheticdata.html) |
| **KPMG** | YData assets used inside KPMG's services | Synthetic data delivered through consulting, not self-serve | [KPMG](https://kpmg.com/us/en/media/news/kpmg-accelerates-ai-strategy-with-ydata.html) |

**Agent distribution channel:** an [official MCP Registry](https://registry.modelcontextprotocol.io/) exists, which supports PRD §11's "listings in MCP tool directories" channel. A third-party article says that as of July 2026, Tonic's Fabricate MCP was not listed on Glama, mcp.so or Smithery. That is **unverified**, but if true, directory presence is still an open opportunity.

---

## 6. Gap analysis against PRD §11 positioning

PRD §11: *"For data and engineering teams in regulated industries who need realistic data without privacy risk, Synthetic is a synthetic-data platform that AI agents and humans can use in minutes. Unlike masking tools or general-purpose fakers, Synthetic preserves real relationships across tables and proves its privacy with every dataset."*

**Positioning** means the place a product holds in the buyer's mind compared with the alternatives: "the X for Y that does Z, unlike W."

| Claim in our positioning | Differentiated? | Evidence |
|---|---|---|
| "AI agents … can use" (MCP) | **No longer.** It is table stakes. | Tonic Fabricate MCP; MOSTLY AI MCP beta (June 2025); K2view MCP marketing; Seedfast |
| "Use in minutes," self-serve | **Partly.** | Tonic Fabricate free/$29 self-serve; SDV Community free. But Structural, Syntho, K2view and SAS are sales-led and quote-only. |
| "Unlike masking tools" | **Weak.** Leading masking vendors now also synthesize. | Tonic (Structural + Fabricate), Syntho (synthesis + masking + rules), K2view (generation + masking + cloning) |
| "Unlike general-purpose fakers" | **Yes**, against Faker itself | Faker generates independent random values, with no learned distributions or cross-table logic ([Faker](https://github.com/joke2k/faker)) |
| "Preserves real relationships across tables" | **Partly.** Many claim it. | Tonic (referential integrity), K2view (entity model), SDV 2.0 (relational models), Snowflake (`join_key`). Our edge has to be *measured* relational fidelity in the report, plus deterministic seeds. |
| "Proves its privacy with every dataset" | **Partly; potentially our strongest claim.** | Tonic Structural has privacy reports; Syntho has a QA report; Snowflake has a similarity filter. We found no self-serve tool that ships a **compliance-ready, per-dataset evidence pack** (fidelity + utility + privacy tests + plain-English summary + PDF) at a mid-market price. Unverified gap; test it with P3 interviews (A19). |
| "Regulated industries" (mid-market) | **Underserved by self-serve tools** | Regulated-industry vendors (Hazy/SAS, K2view, Syntho, Tonic Structural) are enterprise and quote-only. Self-serve tools (Fabricate) target individual developers. The mid-market middle looks thin. |
| Reproducible recipes in CI (deterministic seeds, versioned recipes, CLI) | **Likely differentiated** (not in the §11 statement today) | We found no competitor that leads with byte-identical reproducibility (FR10) for CI. Fabricate offers "project versioning" and "automated workflows" ([pricing](https://www.tonic.ai/pricing)), so this is not unique. |

### Recommended positioning adjustment (hypothesis to test in interviews)

> *For engineering and data teams at regulated mid-market companies, Synthetic generates realistic multi-table test data **from just a schema**, reproducibly in CI or from an AI coding agent, and ships every dataset with a privacy evidence report your compliance team can file. Unlike enterprise test-data suites, it is self-serve and priced for teams. Unlike fakers and chat-based generators, it measures and proves fidelity and privacy every time.*

What changes and why:
1. **Lead with "from just a schema" (no production data needed).** It removes the upload-trust barrier (PRD §12) and sidesteps the A20 risk. Snowflake and SDV mostly start from real data.
2. **Move "agents" from headline to delivery channel.** MCP is now expected, not special. Keep it in G4, but don't build the pitch on it.
3. **Make "evidence your compliance team can file" the core promise**, and frame it as *evidence, not legal certification*, in line with PRD §4.2. The `privacy-compliance-expert` must approve this wording.
4. **Name the price gap explicitly:** between ~$29/month individual plans and $500/user/month enterprise SDKs.

**Impact on the PRD:** if interviews support it (A01, A13, A19, A20), update §11's positioning statement and §1's "angle." Until then, only §2.2 has been corrected (v0.2).

**Next step:** add one question to every interview: "What have you tried for test data, and why did you stop or keep using it?" Tally which competitors appear and why they fell short.

---

## 7. Implications to hand off

| To | Item |
|---|---|
| `backend-data-platform-architect` | Engine choice must respect licenses: SDV's BSL excludes a Synthetic Data Service. Evaluate Apache-2.0 options (MOSTLY AI SDK, Synthcity, NeMo Data Designer) or a commercial SDV license. |
| `privacy-compliance-expert` | (1) Legal reading of SDV's BSL Additional Use Grant. (2) What our report may claim, given that competitors publish "privacy reports" and Snowflake uses DCR/NNDR filters. (3) Whether SOC 2 is needed before design-partner pilots (A02). |
| `qa-evaluation-engineer` | Benchmark against competitor-style metrics (e.g., distance to closest record), so our report numbers can be compared. |

## 8. What we could not verify

- MOSTLY AI's current pricing (pricing page 404), the status of its team and platform after Syntho bought the brand, and its MCP server's current availability (GitHub repo 404).
- Whether NeMo Data Designer or Safe Synthesizer is a direct continuation of Gretel's product.
- Whether YData's product is still sold publicly after the KPMG deal (website 404).
- Synthesized's pricing and product details; K2view pricing; whether K2view exposes synthetic generation via MCP.
- Exactly when the Tonic Fabricate MCP launched (the blog post has no date) and whether it is listed in MCP directories.
- The original Gartner report behind the "75% by 2026" prediction.
- Big-cloud offerings (AWS, Google Cloud, Microsoft) were **not researched** in this pass. Consider a follow-up.

**Key takeaway:** the market has consolidated, but the space it left behind is already being filled. Synthetic should compete on *trust evidence plus schema-first reproducibility at a mid-market price*, not on "has an MCP server."
