# Vibelution Docs Index

This directory contains project documentation that is useful across sessions. Use this file as the first stop before opening older implementation plans.

## Current Entrypoints

| Area | Document | Use |
| --- | --- | --- |
| Project operation | [../DEVELOPMENT_STANDARD.md](../DEVELOPMENT_STANDARD.md) | Canonical development, worktree, validation, and release rules. |
| Domain language | [../CONTEXT.md](../CONTEXT.md) | Stable product and architecture vocabulary. |
| Multi-agent work | [agents/worktree-collaboration.md](agents/worktree-collaboration.md) | Worktree, branch, claim, and merge protocol. |
| Tests | [../tests/README.md](../tests/README.md) | Test entrypoints and validation guidance. |
| Runtime logging | [../core/logging/README.md](../core/logging/README.md) | Logging module overview. |
| Challenge Cup flow | [../挑战杯/research_team_flow_design.html](../挑战杯/research_team_flow_design.html) | Current generated research-flow site. |

## Directory Map

| Directory | Status | Notes |
| --- | --- | --- |
| [adr/](adr/) | Current | Architecture decisions that should remain stable. |
| [agents/](agents/) | Current | Multi-agent collaboration, issue, triage, and domain docs. |
| [ops/](ops/) | Current/reference | Operational audits, policies, and baselines. |
| [plans/](plans/) | Current planning | Recent active or near-current plans only. |
| [prds/](prds/) | Historical/reference | Product requirement documents with durable context. |
| [security/](security/) | Generated/reference | Security and tool-risk reports; verify source data before pruning. |
| [testing/](testing/) | Current/reference | Test reports and validation records. |
| [archive/](archive/) | Historical | Superseded implementation plans and old generated material. |

## Current Plans

- [plans/2026-06-03-memory-platform-rag-retrieval.md](plans/2026-06-03-memory-platform-rag-retrieval.md)
- [plans/2026-06-04-memory-platform-vector-rag-next-phase.md](plans/2026-06-04-memory-platform-vector-rag-next-phase.md)
- [plans/2026-06-05-llm-model-protocol-routing-architecture.md](plans/2026-06-05-llm-model-protocol-routing-architecture.md)
- [plans/2026-06-07-general-data-processing-substrate.md](plans/2026-06-07-general-data-processing-substrate.md)
- [plans/2026-06-19-vibelution-agent-kernel-protocol-plan.md](plans/2026-06-19-vibelution-agent-kernel-protocol-plan.md)

## Archive Boundary

The 2026-05 implementation plans were moved to [archive/plans/2026-05/](archive/plans/2026-05/) because they are useful historical design evidence, but they should not compete with current task entrypoints.

Do not archive or delete `.docs/project-memory/**`, root `PROJECT_MEMORY.html`, or generated Challenge Cup HTML as part of ordinary docs cleanup. Those surfaces have their own governance paths.
