# Design-partner plan

| | |
|---|---|
| **Last updated** | 2026-10-20 |
| **Goal** | 3 design partners signed by the end of week 3 (PRD §13 Phase 0), who then use the MVP weekly in Phase 1 (PRD §13 Phase 1 exit criterion) |

A **design partner** is an early customer who helps shape the product before it is finished. They give regular feedback and try early versions; in return, they get influence and early access. It's like a restaurant's "friends and family" soft opening: a few trusted guests eat early, tell you what's wrong, and you fix the menu before the public arrives.

---

## 1. Ideal design-partner profile

| Attribute | Ideal | Acceptable | Disqualify |
|---|---|---|---|
| **Champion persona** | P2 engineer or P1 data engineer who scored **pain ≥ 2** and **commitment ≥ 2** in their interview | Engineering manager who owns test environments | No recent, concrete pain story |
| **Company** | 200–5,000 employees; fintech, insurance, health-tech or e-commerce (PRD §3.1) | 50–10,000 in another regulated sector | Large enterprise that needs on-prem and long procurement (PRD §3.3) |
| **Stack** | Postgres (MVP direct-write target, F5) with a relational schema of 5+ tables | MySQL or Snowflake; CSV workflows | Needs images, audio or video (PRD §4.2) |
| **Agent use** | Uses an AI coding assistant weekly (tests A16) | Plans to within the quarter | n/a |
| **Compliance access** | Can bring their P3 (privacy/compliance) into one session to review the report | Can describe their approval process in detail | n/a |
| **Time** | 30 min every two weeks for ~10 weeks (Phase 1, weeks 4–14), plus ~15 min/week of hands-on use | 30 min every two weeks | Can't commit to any recurring time |
| **Security posture** | Can try a tool that sees **schemas only** without a formal vendor review | Needs a lightweight security questionnaire | Requires SOC 2 before any trial (see A02) |

**Portfolio rule:** aim for 3 partners from **at least 2 different industries**, with at least one P2-led and one P1-led partner. That keeps PRD §14 Q1 (industry focus) open until the evidence is in.

---

## 2. What we offer vs. what we ask

**Give/get** is the trade at the heart of any partnership: both sides must feel they get more than they give.

| We offer (give) | We ask (get) |
|---|---|
| Free use of Synthetic throughout the private beta | A 30-min feedback session every two weeks (4–6 sessions) |
| A generator "recipe" built for their own schema (from their DDL, never their data) | Their **schema (DDL) only**, with sensitive table/column names renamed if they prefer. **No production data, no personal data.** |
| Direct influence on the roadmap: their top issue gets a written response within a week | Weekly hands-on use during Phase 1 (needed for our exit criterion: "3 design partners using it weekly") |
| A draft privacy evidence report template their compliance team can comment on | One session with their compliance lead (P3) to review the report |
| *Proposal, decide before offering:* a discounted first year if they later convert to paid | Permission to quote them anonymously in product research (named case study only with separate, explicit approval) |
| A summary of findings from all 15 discovery interviews | Honest negative feedback, including "we wouldn't use this" |
| Honesty: this is a student project with no company, SLA or support team yet | An introduction to one peer who might benefit (optional) |

**What we never ask for:** real customer, patient or employee data; credentials to their systems; payment during the beta.

---

## 3. Selection process (weeks 2–3)

1. After each interview, mark candidates with **pain ≥ 2 and commitment ≥ 2** in the synthesis log.
2. In week 2, send the top 3–5 candidates the design-partner ask (template below) plus the one-page outline.
3. Hold a 15-minute call to walk through the outline and answer questions.
4. "Signed" = written confirmation by email that they accept the outline (see [README exit criteria](README.md#exit-criteria-from-prd-13)).
5. Keep 1–2 warm backups in case a partner's employer says no.

**Design-partner ask (email):**

> Hi {name}, thanks again for walking me through {their story}. I'm picking three teams to help shape an early version of a tool for {the pain they described}. It would be ~30 minutes every two weeks over about 10 weeks, plus trying it on your schema. I'd never need real data, only a schema you're comfortable sharing. I've attached a one-page outline of what I'd ask and what you'd get. It's a student project, so no company or contract yet, just a clear set of expectations. Would you be up for it?

---

## 4. One-page design-partner agreement outline

> **WARNING: Not legal advice. Needs review before use.** This is a plain-English outline of mutual expectations, not a contract. Before sending it, it must be reviewed by the `privacy-compliance-expert` agent (data handling) **and** by a qualified human, such as a lawyer or your university's entrepreneurship/legal clinic. That matters especially because no legal entity exists yet, and the partner's employer may have its own rules about sharing schemas or joining outside research. Ask the partner to check with their manager or legal team if unsure.

**Design-Partner Outline: Synthetic (student project)**

1. **Parties.** {Your name}, a student building Synthetic (no company formed yet), and {partner name}, {title}, at {company}, acting with their employer's permission where required.
2. **Purpose.** To shape an early version of Synthetic, a tool that generates realistic synthetic test data from database schemas, through feedback and trial use.
3. **Term.** From {date} to {end of Phase 1, approx. week 14}. Either side may end it at any time, for any reason, by email.
4. **What the partner does (good-faith, non-binding).** Joins ~30-minute feedback sessions about every two weeks; tries the product on their schema about weekly during the beta; optionally introduces their compliance lead for one session.
5. **What Synthetic provides.** Free beta access; a recipe for their schema; responses to their feedback; a findings summary; (optional) the first-year discount, if offered.
6. **Data.** The partner shares **schemas only** (table/column definitions), with sensitive names renamed if preferred. **No production data or personal data** will be requested or accepted. Shared schemas are used only for this project, are not shared with anyone else, and are deleted on request or at the end of the term.
7. **Confidentiality.** Both sides keep the other's non-public information confidential. The partner's company name is not disclosed without written permission.
8. **Feedback.** Synthetic may use the partner's feedback and ideas to improve the product, with no obligation on either side.
9. **No fees, no warranty.** The beta is free and provided "as is." It is not for production use, and there is no SLA.
10. **Publicity.** Anonymous quotes only, unless the partner gives separate written approval for named use.
11. **Contacts.** {Your name, email} · {Partner name, email}.

*Confirmation:* "I've read this outline and I'm happy to proceed." (Reply by email.)

---

## 5. Where to find candidates

Work from warmest to coldest: warm introductions convert far better than cold messages. Verify current invite links and community rules before posting; many communities restrict promotion, so frame posts as research.

### 5.1 University and alumni networks (start here)
- **Your MSBA program:** professors who teach data engineering, analytics or information systems (ask each for 2 practitioner contacts), capstone and practicum sponsors, industry advisory boards, and guest speakers from past courses.
- **Alumni:** use LinkedIn's alumni tool (your university's LinkedIn page → "Alumni"). Filter by "What they do: Engineering / Information Technology / Legal" and by employers in fintech, insurance and health care.
- **Career services and entrepreneurship centers:** startup clinics often have mentor networks and can advise on the agreement outline.
- **Classmates' employers:** part-time MSBA classmates often work in data roles.

### 5.2 Online communities (research posts, not promotion)
| Community | Good for |
|---|---|
| dbt Community Slack; Locally Optimistic Slack | P1 data/analytics engineers |
| MLOps Community Slack; DataTalks.Club Slack | P1 ML engineers |
| r/dataengineering, r/QualityAssurance, r/ExperiencedDevs (Reddit) | P1/P2 (read the rules on research posts) |
| Ministry of Testing community | P2 QA/test engineers |
| PostgreSQL community Slack/Discord | P2 engineers on Postgres |
| Discords and forums for AI coding tools and MCP | P2 agent users (A16) |
| IAPP (International Association of Privacy Professionals) KnowledgeNet chapters and online community | P3 privacy professionals |

### 5.3 Events
- Local data, Python (PyData) and analytics meetups (search Meetup.com and Luma for your city).
- dbt and data-engineering meetups; local fintech or health-tech meetups.
- IAPP KnowledgeNet chapter events (P3).
- University career fairs and alumni networking nights.
- Ask speakers a "last time" question after their talk, then request a follow-up call.

### 5.4 LinkedIn searches (copy-paste Boolean strings)

Filter by company size **201–500, 501–1,000, 1,001–5,000**; industries **Financial Services, Insurance, Hospitals and Health Care, Retail / Online retail**; and location if you want in-person coffee chats.

| Persona | Search string |
|---|---|
| P1 | `("data engineer" OR "ML engineer" OR "machine learning engineer" OR "analytics engineer") AND (fintech OR payments OR lending OR insurance OR "health tech" OR healthcare OR ecommerce)` |
| P2 | `("QA engineer" OR SDET OR "test engineer" OR "backend engineer" OR "platform engineer") AND ("test data" OR staging OR "test environments" OR Postgres)` |
| P3 | `("privacy manager" OR "privacy officer" OR "data protection officer" OR DPO OR "compliance manager" OR "data governance") AND (fintech OR insurance OR healthcare)` |
| Signal of pain | Posts or comments containing `"test data"`, `"production data in staging"`, `"data masking"`, `"synthetic data"` |

### 5.5 Pipeline targets (planning assumption)

| Stage | Target |
|---|---|
| People contacted | ~80 |
| Interviews completed | 15 |
| Design-partner candidates (pain ≥ 2, commit ≥ 2) | 5–8 |
| Asked | 3–5 |
| Signed | 3 |

These conversion rates are our planning assumptions (A25, A26), not industry benchmarks. Replace them with your real week-1 numbers.

**Key takeaway:** a good design partner has a painful, recent problem and is willing to spend time on it. Pick on commitment shown in the interview, never on enthusiasm alone.
