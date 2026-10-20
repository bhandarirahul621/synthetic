# Interview guide

| | |
|---|---|
| **Last updated** | 2026-10-20 |
| **Use with** | [assumptions-register.md](assumptions-register.md) (IDs like A14 below refer to it) |
| **Target** | 15 interviews: 6 × P1 (Data/ML engineer), 6 × P2 (Software/QA engineer), 3 × P3 (Privacy/Compliance lead) |

**Contents:** 1. Screener · 2. Outreach templates · 3. Interview rules · 4. 30-minute script · 5. Note-taking template · 6. Synthesis template

---

## 1. Screener: who qualifies

A **screener** is a short filter that makes sure you spend interview time only on people whose experience matches our target personas (PRD §3).

### 1.1 Qualifying rules

| | P1 "Dana": Data / ML engineer | P2 "Sam": Software / QA engineer | P3 "Priya": Privacy / Compliance lead |
|---|---|---|---|
| **Typical titles** | Data engineer, ML engineer, analytics engineer, data scientist | Backend/full-stack engineer, QA/SDET, platform/DevOps engineer, engineering manager | Privacy officer/manager, DPO, compliance manager, GRC/security analyst, data governance lead |
| **Must have (all)** | Needed training, test or sharing data in the **last 6 months** | Built or tested features against a relational DB (Postgres, MySQL, Snowflake…) in the **last 6 months** | Reviewed or approved a request to use personal data outside production in the **last 12 months** |
| **Company** | Prefer 200–5,000 employees in fintech, insurance, health-tech or e-commerce (PRD §3.1). Accept 50–10,000 and tag it. | Same | Same |
| **Bonus (tag it)** | Was blocked by a data-access request | Uses an AI coding assistant weekly | Has evaluated anonymization or synthetic data before |

**Disqualify** (or interview separately and **don't count** toward the 15):
- Employees of synthetic data or test data vendors (useful for market insight, but they are not customers).
- Students or academics without a current industry role.
- Close friends or family. They will be kind, not honest.
- Large enterprises that only buy on-premises software through long procurement (PRD §3.3). You may talk to them, but tag them "out of segment."

### 1.2 Screener questions (ask in the outreach reply or the first 2 minutes)

| # | Question | Qualifies if |
|---|---|---|
| S1 | What's your role, and roughly how many people work at your company? | Matches a persona; 50–10,000 employees |
| S2 | What industry is the company in? | Fintech, insurance, health-tech, e-commerce, or other regulated (tag it) |
| S3 | (P1/P2) In the last 6 months, have you needed realistic data for testing, a demo, training a model, or sharing with someone? | Yes |
| S3′ | (P3) In the last 12 months, have you reviewed a request to use customer or patient data outside production? | Yes |
| S4 | Do you work for a company that sells synthetic data or test data tools? | No |

**Quotas** (to answer PRD §14 Q1): aim for at least 4 interviews in each of fintech, health-tech and e-commerce across all personas, and at least one P3 in two different industries.

---

## 2. Outreach templates

Keep messages short and specific, and always ask for a small, clear thing (a 30-minute call). Personalize the first line every time: mention their post, talk or project.

### 2.1 LinkedIn connection note (≤ 300 characters)

> Hi {first name}, I'm an MSBA student researching how {data / QA} teams get realistic test data without using production data. Your {post on X / work at Y} stood out. Could I ask you about your experience in a 30-min call? No sales; it's a student project.

### 2.2 LinkedIn message or cold email: MSBA student version (honest about being a student project)

**Subject:** Student research: how does your team get test data?

> Hi {first name},
>
> I'm {your name}, a Master of Science in Business Analytics student at {university}. For an independent project, I'm studying how {data engineers / software teams / privacy teams} at {fintech / health-tech / e-commerce} companies get realistic data for testing and AI work without exposing customer data.
>
> I'm **not selling anything**. There's no company or product yet. I'm trying to understand the real problems before building anything. I'd value 30 minutes to hear how it works at {company}: what you do today, and what's frustrating about it.
>
> I won't ask for any confidential or customer data, I'm happy to keep your company name out of my notes, and I'll share a summary of what I learn across all interviews if that's useful.
>
> Would any of these times work? {2–3 options with time zone}
>
> Thank you,
> {name} · {LinkedIn URL} · {university email}

### 2.3 Practitioner-to-practitioner version (short, for warm communities like Slack groups)

> Hi all, I'm researching how teams handle test data for staging/CI and AI evaluation without production copies. If you've dealt with this in the last few months (data, QA or privacy roles), I'd love a 30-min chat about what you do today. Student project, no pitch. DM me if you're open to it. Thank you!

### 2.4 Warm-intro request (to professors, alumni, interviewees)

> Hi {name}, thanks again for {last conversation}. I'm interviewing {data engineers / QA leads / privacy leads} at regulated mid-size companies about how they get safe test data. Do you know one or two people who might be open to a 30-min student research call? I've drafted a short note you can forward: {paste 2.2}.

### 2.5 Follow-up (send once, 4–5 days later)

> Hi {first name}, just floating this back up in case it got buried. 30 minutes on how your team gets test data, student research, no pitch. If now's a bad time, could you point me to a colleague who deals with this? Thanks either way.

### 2.6 Thank-you (same day)

> Thanks so much for your time today, {first name}. The point about {specific thing they said} was really useful. You mentioned {person/introduction}; I'd be grateful for an intro if you're comfortable. I'll send you the summary of findings when I finish in {month}.

---

## 3. Interview rules ("Mom Test" principles)

*The Mom Test* (Rob Fitzpatrick) teaches you to ask questions that even someone who loves you can't answer with a polite lie.

| Do | Don't |
|---|---|
| Ask about **specific past events**: "Tell me about the last time…" | Ask hypotheticals: "Would you use…?" "Would you pay…?" |
| Ask what they **already did** to solve it, and what it cost | Describe or pitch Synthetic before the very end |
| Dig with "Why?", "What happened next?", "How did you decide?" | Accept vague answers like "usually" or "it's fine." Ask for an example. |
| Count **commitments** (time, introductions, sharing a schema) | Count compliments ("cool idea!") as evidence |
| Let silences sit; they will fill them | Talk more than ~20% of the time |
| Write down **exact quotes** | Paraphrase into what you hoped to hear |

**Bad → good question examples**

| Bad (hypothetical / leading) | Good (past behavior) |
|---|---|
| "Would a tool that generates test data be useful?" | "Tell me about the last time you needed test data. What did you do?" |
| "Is privacy a big concern for you?" | "Who had to approve that data use? What did they ask for?" |
| "Would you pay $49 a month?" | "What did your team last pay for a dev tool? How did that purchase happen?" |
| "Do you want your coding agent to generate data?" | "Walk me through the last time your coding assistant wrote a test that needed data." |

---

## 4. 30-minute interview script

Use **Module A** for P1 and P2, and **Module B** for P3. Each question lists the assumption IDs it tests. Time boxes are guides; follow the stories.

### 0. Opening (2 min)

> "Thanks for making time. I'm a business analytics student researching how teams get realistic data for testing and AI work. There's no product and I'm not selling anything. I'm here to learn from your experience, so there are no wrong answers, and 'it's fine as it is' is a very useful answer. Is it OK if I take notes? I won't record your company name unless you're comfortable with that. Please don't share anything confidential."

### Module A: P1 (Data/ML) and P2 (Software/QA)

| # | Time | Question | Follow-ups | Tests |
|---|---|---|---|---|
| A1 | 3 min | "Tell me about your role and what your team is working on right now." | "What does your data stack look like: databases, warehouse, CI?" | A17, A22, A29 (context) |
| A2 | 12 min (A2–A9) | "Tell me about the **last time** you needed realistic data for testing, a demo, training a model or sharing. What was it for?" | "When was that?" | A14, A17 |
| A3 | | "Where did the data come from? Walk me through the steps." | "Did you start from a schema, a sample, a production copy, or nothing?" | A14, A20, A13 |
| A4 | | "How long did it take from needing it to having usable data?" | "What were you waiting on?" | A17, A21 |
| A5 | | "Who had to approve it, if anyone? What did they ask for?" | "Has a request ever been refused?" | A15, A19, A18 |
| A6 | | "What went wrong or was annoying about the data you ended up with?" | "Did relationships between tables break? Missing edge cases? Unrealistic values?" | A13, A22 |
| A7 | | "What did that cost you: time, a bug that reached production, a delayed launch?" | "Can you put a rough number on it?" | **A14** |
| A8 | | "What have you tried to make this easier: scripts, Faker, masking tools, a vendor, Snowflake/Databricks features?" | "Why did you keep or drop it?" | **A01**, A13, A29, A14 |
| A9 | | "How often does this come up? This week, this month, this quarter?" | "Is it getting more or less frequent?" | A05, A14 |
| A10 | 5 min | "Do you use an AI coding assistant? Walk me through the **last time** it wrote a test or a feature that needed data." | "What did it do for data? Did you have to step in?" | **A16**, A04 |
| A11 | | "Have you connected any outside tools to your assistant (for example through MCP)? Which ones, and how did you find them?" | "Does your company allow that?" | **A16**, A12 |
| A12 | 4 min | "Tell me about the **last developer tool your team started paying for**. How did it go from trial to paid? Who signed off? How long did it take?" | "Was there a security review? What triggered it?" | **A18**, A09, A10 |
| A13 | | "When a new tool touches anything related to customer data, even just schemas, what does your security or privacy review require?" | "Would an outside service ever be allowed to receive a data sample?" | A19, A02, A20, A26 |
| A14 | | "How did you discover the last dev tool you adopted?" | "Docs? GitHub? A colleague? A directory?" | A12 |

### Module B: P3 (Privacy / Compliance)

| # | Time | Question | Follow-ups | Tests |
|---|---|---|---|---|
| B1 | 3 min | "Tell me about your role. Which teams bring you data-use requests?" | "How many a month, roughly?" | A15 (context) |
| B2 | 12 min (B2–B6) | "Tell me about the **last request** you reviewed to use personal data outside production. What was it?" | "When was it?" | A15, A19 |
| B3 | | "What did you decide, and why?" | "How long did it take?" | A15, A17 |
| B4 | | "What evidence or documentation did you ask for?" | "What would have let you say yes faster?" | **A19** |
| B5 | | "Have you ever approved anonymized, masked or synthetic data? What did you accept as proof it was safe?" | "Who else had to agree: legal, security, a DPO?" | **A19** |
| B6 | | "Is there a written policy about production data in test or dev environments? Has an audit ever flagged it?" | "When was it last updated?" | A15 |
| B7 | 5 min | "Tell me about the last new vendor you approved that handles data. What did you require?" | "SOC 2? A DPA? A questionnaire? How long did it take?" | A02, A18, A26 |
| B8 | | "What makes you reject a vendor outright?" | | A02, A20, A26 |
| B9 | 4 min | **Artifact review (only after B1–B8):** "I've sketched what a privacy evidence report could contain. Could you tell me what's missing for you to file something like this, and what you'd ignore?" (Show a one-page mock. Not a pitch: don't defend it, just listen.) | "Who would read it besides you?" | **A19** |

> The mock report for B9 must be reviewed by `privacy-compliance-expert` before use, so it makes no legal claims (PRD §4.2).

### Closing (all personas, 3–4 min)

| # | Question | Tests |
|---|---|---|
| C1 | "Is there anything I should have asked but didn't?" | n/a |
| C2 | "Who else should I talk to about this, inside or outside your company?" | A25, A26 |
| C3 | **Commitment test** (only if the pain score is 2–3): "I'm picking three teams to shape an early version over the next ~10 weeks: a 30-minute session every two weeks, using schemas only, never real data. Would you be open to a follow-up in two weeks to look at a first prototype?" | A26, design partner pipeline |

**Commitment ladder** (record the highest step reached): 0 = nothing · 1 = "send me the summary" · 2 = agreed to a follow-up call · 3 = intro to a colleague or their compliance lead · 4 = offered to share a schema/DDL or agreed to the design-partner outline.

---

## 5. Note-taking template

Copy this block for each interview (one file or one doc tab per interview). Fill it in within 24 hours.

```markdown
# Interview #__ — {date}
- Persona: P1 / P2 / P3      Title: ____      Industry: ____      Company size: ____
- Source: cold LinkedIn / email / community / warm intro (from whom?)
- Tags: in-segment / out-of-segment; uses AI coding agent Y/N; on Snowflake/Databricks Y/N

## The last-time story (facts only)
- What they needed and why:
- Where the data came from (schema / sample / prod copy / nothing):
- Time to usable data:
- Approvals and who:
- What went wrong:
- Cost (time / bugs / delays), with numbers if given:
- What they tried before (tools, scripts, vendors) and why kept or dropped:
- How often this happens:

## Agent workflow (P1/P2)
- Uses coding agent? Which? How often?
- Connected tools / MCP? Allowed by policy?
- Data need inside an agent session? Story:

## Buying and trust
- Last dev tool purchase: how, who, how long, security review?
- Requirements for vendors touching data:
- (P3) Evidence they accept / reject:
- (P3) Feedback on mock report:

## Exact quotes (3–5)
> "..."

## Scores
- Pain score (0 none · 1 mild · 2 real, recurring · 3 severe, has spent money/time trying to fix):
- Commitment ladder step (0–4):
- Introductions offered:

## Assumption signals (+ supports / − contradicts / ? unclear)
A14: _  A19: _  A16: _  A18: _  A01: _  A29: _  A13: _  A20: _  A02: _  A15: _  A17: _  A22: _  A09: _  A12: _

## Surprises / new assumptions
-
```

---

## 6. Synthesis template (tallying 15 interviews)

**Synthesis** means turning many separate conversations into patterns you can act on. Use a spreadsheet with one row per interview and one column per assumption, then count.

### 6.1 Interview log (one row per interview)

| # | Date | Persona | Industry | Size | Source | Pain (0–3) | Commit (0–4) | Agent user? | Tools tried | A14 | A19 | A16 | A18 | A01 | A29 | A13 | A20 | A02 | Key quote |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | | P2 | fintech | 800 | warm | 2 | 2 | Y | Faker, prod copy | + | n/a | + | − | + | ? | + | + | ? | "…" |
| … | | | | | | | | | | | | | | | | | | | |

### 6.2 Assumption tally (fill in every Friday)

| ID | + | − | ? | n/a | Decision rule (from register) | Verdict this week |
|---|---|---|---|---|---|---|
| A14 | | | | | ≥ 8 of 12 P1/P2 show a costly, recent incident **and** a past attempt to fix it | |
| A19 | | | | | ≥ 2 of 3 P3 could approve with the report + feasible additions | |
| A16 | | | | | ≥ 4 of 6 P2 use agents weekly; ≥ 3 describe a data need in an agent session | |
| A18 | | | | | ≥ half of P1/P2 describe a self-serve/under-threshold purchase | |
| A01 | | | | | Interviewees name unmet needs after trying existing tools, or never found a fitting tool | |
| A29 | | | | | Platform users still list unmet needs | |
| A13 | | | | | Broken relationships / privacy exposure in top-3 pains for ≥ half | |
| A20 | | | | | ≥ 60% of stories could start from a schema | |
| A02 | | | | | ≤ 1 of 3 design-partner candidates require SOC 2 first | |

Verdicts: **Supported**, **Challenged**, **Rejected** or **Need more data**. Copy them into the register's Status column.

### 6.3 Segment view (answers PRD §14 Q1)

| Industry | # interviews | Avg pain | Avg commitment | # design-partner candidates | Notes |
|---|---|---|---|---|---|
| Fintech | | | | | |
| Health-tech | | | | | |
| E-commerce | | | | | |
| Other | | | | | |

**Decision rule:** the beta industry is the one with the highest *average commitment* (not pain), with at least 4 interviews. Commitment is behavior; pain is talk.

### 6.4 Pattern log

- **Top 5 pains** (count mentions): …
- **Tools tried and why they failed** (competitive input): …
- **Words customers use** (for landing-page copy later): …
- **Surprises and new assumptions** (add to the register from A30): …

**Key takeaway:** ask about the last real time something happened, write down exactly what people said, and trust what they did (spent, tried, committed) over what they say they would do.
