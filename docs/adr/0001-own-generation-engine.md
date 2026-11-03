# ADR 0001: Build our own generation engine instead of wrapping SDV

- **Status:** Accepted (Milestone 1)
- **Date:** 2026-11-02
- **Context sources:** PRD §9 ("build vs. buy"), [competitive landscape](../discovery/competitive-landscape.md) finding 3

## Context

PRD §9 suggested wrapping a proven open-source tabular synthesis library. The best known one, SDV (DataCebo), is released under the Business Source License. Its Additional Use Grant excludes running it as a "Synthetic Data Service" until four years after each release. Synthetic *is* a hosted synthetic data service, so on a plain reading SDV can't be its engine without a commercial agreement. (The legal reading belongs to `privacy-compliance-expert` and counsel. This ADR assumes the plain reading.)

## Options considered

1. **Wrap SDV.** It's mature and has many models, but the license blocks our core use case. Rejected.
2. **Wrap a permissive library** (MOSTLY AI SDK, Synthcity; both Apache 2.0). They're strong, but they're heavy dependencies (PyTorch). One of them is now owned by a competitor's brand group, and neither covers our schema-first relational orchestration or the report we want to own. Kept as future candidates behind the model interface.
3. **Own engine on numpy, pandas and scipy** (BSD), plus Faker (MIT) for PII-type values. Chosen.

## Decision

We write our own engine:

- a relational orchestrator (parents first, realistic children per parent, constraint repair and validation);
- per-type generators;
- a Gaussian copula for sample learning.

All of it sits behind `synthetic.engine.base.TabularModel`, so a deep generative model (for example the Apache-2.0 MOSTLY AI SDK) can be added later without touching the API.

## Consequences

- **Gain:** no license risk. The dependencies are small and permissive, everything is deterministic (FR10) and fast (1M × 20 in about 10 s locally), and we fully control the relational and privacy logic, which is where we differentiate.
- **Give up:** model quality on complex, non-linear data. A Gaussian copula captures marginals and pairwise (monotone) correlations, but not interactions or multi-table learning.
- **Revisit when:** benchmark fidelity drops below the PRD §10.2 target (median 85) on design-partner data, or when customers need multi-table learning from samples. At that point, add a second `TabularModel` and pick automatically by data size and type (PRD F3).
