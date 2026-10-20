# Phase 0 — Discovery plan

| | |
|---|---|
| **Phase** | 0 — Discovery (PRD §13), weeks 0–3 |
| **Owner** | Rahul Bhandari |
| **Prepared by** | product-strategist agent |
| **Last updated** | 2026-10-20 |
| **Source of truth** | [`docs/PRD.md`](../PRD.md) |

---

## Recommendation (one paragraph)

Spend Phase 0 testing the five riskiest assumptions in the [assumptions register](assumptions-register.md), not collecting feature ideas. The biggest single risk is that a privacy/compliance lead (persona P3, "Priya") will **not** accept our Fidelity and Privacy Report as evidence. The second is that the "agent-first, self-serve" gap is smaller than the PRD assumes: desk research found that Tonic Fabricate and MOSTLY AI already ship MCP servers and self-serve tiers (see [competitive landscape](competitive-landscape.md)). Run 15 interviews using the [interview guide](interview-guide.md), turn the best 3 conversations into design partners using the [design-partner plan](design-partner-plan.md), and use the results to answer the PRD §14 open questions ([hypotheses](open-questions-hypotheses.md)).

**Why:** (1) every later phase depends on these answers; (2) interviews about past behavior cost nothing but time; (3) the competitive research changes what "differentiated" means for us.
**Main risk:** a solo student without a company may struggle to book interviews with regulated companies. Track the outreach funnel from day one (see the schedule below).

---

## Goals

1. **Validate the problem.** Do data/ML engineers (P1) and software/QA engineers (P2) at regulated mid-market companies feel enough pain with today's workarounds (production copies, masking, Faker) to adopt a new tool?
2. **Validate the trust model.** What evidence does a compliance lead (P3) need before approving synthetic data?
3. **Validate the agent angle.** Do engineers already use AI coding agents with tool connections (MCP), and do those agents need test data?
4. **Validate buying.** Can these teams start and pay for a tool themselves, or does every purchase go through procurement and a security review?
5. **Recruit 3 design partners** for Phase 1 (PRD §13 exit criterion).
6. **Hand off benchmark dataset selection** to the `qa-evaluation-engineer` agent (candidate list in [open-questions-hypotheses.md](open-questions-hypotheses.md#handoff-benchmark-datasets-owned-by-qa-evaluation-engineer)).

## Exit criteria (from PRD §13)

| Criterion | Definition we will use | Evidence |
|---|---|---|
| **15 customer interviews** | 15 completed interviews with people who pass the [screener](interview-guide.md#1-screener-who-qualifies). Target mix: 6 × P1, 6 × P2, 3 × P3. Friends who are only being polite and competitors do not count. | 15 filled note sheets + the synthesis tally |
| **3 design partners signed** | 3 people who have confirmed **in writing** (email is fine) that they accept the one-page [design-partner outline](design-partner-plan.md#4-one-page-design-partner-agreement-outline): feedback sessions every two weeks and weekly use of the MVP in Phase 1. | 3 confirmation emails |
| **Benchmark datasets chosen** | `qa-evaluation-engineer` has picked the benchmark suite. Product strategy supplies only the candidate list and the use cases each dataset must represent. | QA agent's benchmark document |

---

## Week-by-week schedule

Planning assumption (ours, not a measured industry rate): about 1 in 5 cold outreach messages leads to a booked interview. So we plan for **about 80 outreach messages** to get 15 interviews. Adjust after week 1 using your real numbers.

| Week | Focus | Tasks | End-of-week checkpoint |
|---|---|---|---|
| **0** | Set-up and outreach | Read the PRD, this folder and the [competitive landscape](competitive-landscape.md). Build a target list of 80+ people (sources in the [design-partner plan](design-partner-plan.md#5-where-to-find-candidates)). Send the first 40 messages using the [templates](interview-guide.md#2-outreach-templates). Make your note-taking sheet and synthesis spreadsheet from the templates. Do one practice interview with a classmate. | ≥ 40 messages sent; ≥ 5 interviews booked |
| **1** | Interviews 1–5 | Run 5 interviews. Fill in notes within 24 hours of each one. Send the next 40 messages. Ask every interviewee for 2 introductions. | 5 done; first tally of the top 5 assumptions; outreach reply rate measured |
| **2** | Interviews 6–11 + first design-partner asks | Run 6 interviews. Include at least 2 P3 (compliance) interviews this week. Ask the 3–5 strongest interviewees (highest pain + commitment scores) to be design partners. Refine the script if a question is not producing stories. | 11 done; ≥ 2 design-partner "yes" replies; draft answer to PRD §14 Q1 (industry) |
| **3** | Interviews 12–15, sign partners, synthesize | Finish 4 interviews. Get written confirmation from 3 design partners. Complete the synthesis tally. Update each assumption's status in the register. Write a one-page decision memo. Ask product-strategist to update PRD §14 and bump the PRD version. Confirm the benchmark handoff is done. | All 3 exit criteria met, or a written explanation of the gap and a plan |

If you are behind at the end of week 1 (fewer than 5 interviews booked), switch effort to warm introductions (professors, alumni, interviewees' contacts). They convert much better than cold messages.

---

## How to run Phase 0 (for a student)

**What "customer discovery" means.** Customer discovery is research to check whether a problem is real and painful before you build anything. Think of it as a doctor's diagnosis before the prescription: you ask what happened, where it hurts, and what the patient has already tried. You do not hand out pills on the first visit.

**The rules (from *The Mom Test* by Rob Fitzpatrick).** The book's name comes from the idea that even your mom can't lie to you if you ask good questions.
1. **Talk about their life, not your idea.** Don't describe Synthetic until the very end, if at all.
2. **Ask about specific past events, not opinions about the future.** "Tell me about the last time you needed test data" beats "Would you use a tool that…?" People are poor predictors of their own future behavior and like to be polite.
3. **Listen more than you talk.** Aim for them speaking 80% of the time.
4. **Look for commitment, not compliments.** "Sounds cool!" is worth nothing. A meeting with their compliance lead, an intro to a colleague, or an offer to share a schema is real evidence. We call these **commitment signals**: costs in time, reputation or money that someone accepts.

**Your weekly rhythm.**
1. **Before:** check the screener, read their LinkedIn profile, and pick the persona module (P1/P2 or P3).
2. **During:** follow the script, take notes in the template, and capture exact quotes.
3. **Within 24 hours:** fill in the synthesis row. For each assumption tested, mark **+** (supports), **−** (contradicts) or **?** (unclear), with a pain score and a commitment score.
4. **Every Friday:** look at the tally. Which of the top 5 assumptions are leaning true or false? Change next week's questions to dig into whatever is still unclear.

**Honesty rule.** Always say this is a student project with no company yet. Practitioners are often generous with students. Misrepresenting yourself would break trust and could break their employer's policies. Never ask for real customer data.

**What we are NOT doing in Phase 0:** building the product, choosing the architecture (that belongs to `backend-data-platform-architect`), making legal claims about anonymization (that belongs to `privacy-compliance-expert`), or choosing benchmark datasets (that belongs to `qa-evaluation-engineer`).

---

## Files in this folder

| File | What it is | Use it when |
|---|---|---|
| [assumptions-register.md](assumptions-register.md) | Every PRD assumption, scored by risk × uncertainty, with a test and pass/fail rule. Top 5 marked. | Planning the week; updating status after synthesis |
| [competitive-landscape.md](competitive-landscape.md) | Vendors, open-source tools and platform bundling as of October 2026, with sources. Gap analysis and a recommended positioning change. | Preparing for interviews; answering "how is this different?" |
| [interview-guide.md](interview-guide.md) | Screener, outreach templates, 30-minute script mapped to assumption IDs, note-taking and synthesis templates. | Every interview |
| [design-partner-plan.md](design-partner-plan.md) | Ideal partner profile, give/get, a one-page agreement outline (needs review) and where to find candidates. | Weeks 2–3 |
| [open-questions-hypotheses.md](open-questions-hypotheses.md) | Our current hypothesis for each PRD §14 question, plus the benchmark handoff to QA. | Writing the end-of-phase decision memo |

## Impact on the PRD

- §13 Phase 0 now links here.
- §2.2's consolidation bullet was corrected with sources (see [competitive-landscape.md](competitive-landscape.md)).
- At the end of week 3, §14 answers and assumption statuses will be written back into the PRD (version bump).

## Next step

Build the 80-person target list and send the first 40 outreach messages this week. Every other activity depends on having interviews booked.

**Key takeaway:** Phase 0 is not about proving the idea right. It is about finding out cheaply, from real past behavior, which of our riskiest beliefs are wrong.
