# synthetic

Privacy-safe synthetic data for AI, analytics and software teams.

**Status: Milestone 1 (Phase 1 MVP core) runs locally.** You can generate realistic multi-table data from SQL DDL, a JSON/YAML schema, or a CSV/Parquet sample. Foreign keys and constraints are enforced, and output is byte-reproducible from a seed. Every dataset comes with a Fidelity and Privacy Report. You can use it through a REST API, the Python SDK, the CLI, an MCP server for AI agents, or a minimal web UI.

- [Quickstart](docs/dev/quickstart.md) · [Architecture and known gaps](docs/dev/architecture.md) · [ADR 0001: own engine](docs/adr/0001-own-generation-engine.md)
- [Product Requirements Document](docs/PRD.md)

## Expert agents

Claude Code subagents in `.claude/agents/`:

| Agent | Use for |
|---|---|
| `product-strategist` | Positioning, pricing, prioritization, keeping the PRD current |
| `privacy-compliance-expert` | Privacy checks, PII handling, regulation, honest privacy claims |
| `backend-data-platform-architect` | API, workers, data model, connectors, SDK/CLI, MCP server |
| `qa-evaluation-engineer` | Test strategy, benchmarks, requirement verification, release readiness |
