# Vibelution Docs Index

This directory contains project documentation that is useful across sessions. Use this file as the first stop before opening older implementation plans.

## Current Entrypoints

| Area | Document | Use |
| --- | --- | --- |
| Project operation | [../DEVELOPMENT_STANDARD.md](../DEVELOPMENT_STANDARD.md) | Canonical development, worktree, validation, and release rules. |
| Structure / file-size awareness | [../DEVELOPMENT_STANDARD.md#83-structure-and-file-size-awareness](../DEVELOPMENT_STANDARD.md#83-structure-and-file-size-awareness) | Soft guidance to prefer packs over god files; no hard fail. |
| Frontend style ownership | [../DEVELOPMENT_STANDARD.md#9-frontend-standards](../DEVELOPMENT_STANDARD.md#9-frontend-standards) | Tailwind-first styling, HeroUI primitive usage, and VUI composition rules. |
| Domain language | [../CONTEXT.md](../CONTEXT.md) | Stable product and architecture vocabulary. |
| Multi-agent work | [agents/worktree-collaboration.md](agents/worktree-collaboration.md) | Worktree, branch, claim, and merge protocol. |
| Conversation flow | [agents/conversation-flow-map.md](agents/conversation-flow-map.md) | Chat/Coding message path from submit to model stream, journal facts, SSE, and frontend projection. |
| Tests | [../tests/README.md](../tests/README.md) | Test entrypoints and validation guidance. |
| Runtime logging | [../core/logging/README.md](../core/logging/README.md) | Logging module overview. |
| Challenge Cup flow | [../挑战杯/research_team_flow_design.html](../挑战杯/research_team_flow_design.html) | Current generated research-flow site. |
| Spec/plan lifecycle | [superpowers/](superpowers/) | Status metadata and ownership rules for active design specs and implementation plans. |

## Norms Map (how work is governed)

Use this map when you need **where the rule lives**, not a second full process manual. Prefer awareness and smallest useful change over rigid enforcement.

| Concern | Canonical place | Notes |
| --- | --- | --- |
| How to develop / validate / merge / release | [../DEVELOPMENT_STANDARD.md](../DEVELOPMENT_STANDARD.md) | Full operating standard |
| Red lines & short Agent entry | [../AGENTS.md](../AGENTS.md) | Compact index; details stay in Standard |
| Backend “which file do I edit?” | [../core/web/services/session/README.md](../core/web/services/session/README.md), [../core/web/services/team_workflow/README.md](../core/web/services/team_workflow/README.md), [../core/web/services/agent_directory/README.md](../core/web/services/agent_directory/README.md), [../core/web/services/runtime_scene/README.md](../core/web/services/runtime_scene/README.md) | Claim maps + 30-second routing tables |
| Frontend TS / Tailwind / HeroUI / VUI | [../DEVELOPMENT_STANDARD.md#9-frontend-standards](../DEVELOPMENT_STANDARD.md#9-frontend-standards) | Implementation style for `web/` |
| Domain vocabulary | [../CONTEXT.md](../CONTEXT.md) | Product language, not code style |
| Architecture decision memory | [adr/](adr/) | Why a major choice exists |
| Tests how-to | [../tests/README.md](../tests/README.md) | Suite layout and matrix |
| Commit Python fatal checks | `scripts/local_quality_gate.py` + `.githooks` | Ruff subset for crash-class issues only |
| Project structure snapshot | [../INDEX.md](../INDEX.md) | Orientation index; verify hot numbers when they matter |

There is **no** separate full-stack `CODING_STYLE.md`. Python style is mostly project habit plus fatal Ruff at commit; frontend style is Standard §9. Structure preferences are Standard §8.3 plus service pack READMEs.

## Directory Map

| Directory | Status | Notes |
| --- | --- | --- |
| [adr/](adr/) | Current | Architecture decisions that should remain stable. |
| [agents/](agents/) | Current | Multi-agent collaboration, issue, triage, and domain docs. |
| [ops/](ops/) | Current/reference | Operational audits, policies, and baselines. |
| [plans/](plans/) | Current planning | Recent active or near-current plans only. |
| [prds/](prds/) | Historical/reference | Product requirement documents with durable context. |
| [security/](security/) | Generated/reference | Security and tool-risk reports; verify source data before pruning. |
| [superpowers/](superpowers/) | Current planning | User-approved design specs and implementation plans from Superpowers/CCDawn workflows; active files may be untracked until their owning claim closes. |
| [testing/](testing/) | Current/reference | Test reports and validation records. |
| [archive/](archive/) | Historical | Superseded implementation plans and old generated material. |

## Current And Recent Plans

- Use [superpowers/specs/](superpowers/specs/) and [superpowers/plans/](superpowers/plans/) for active CCDawn/Superpowers design and execution artifacts.
- Use [plans/](plans/) for durable architecture plans that remain current or near-current when cited by active work.
- Use [../.docs/project-memory/INDEX.md](../.docs/project-memory/INDEX.md) and [../PROJECT_MEMORY.html](../PROJECT_MEMORY.html) for live lane state, active claims, recent updates, and merge readiness.

## Spec And Plan Lifecycle

Files in [superpowers/specs/](superpowers/specs/) and [superpowers/plans/](superpowers/plans/) should begin with compact metadata: `Status`, `Owner`, `Claim` or branch/worktree when applicable, `Scope`, `Supersedes` or `Replaces`, `Implementation link`, `Validation`, and `Close condition`.

Use status values from [../DEVELOPMENT_STANDARD.md#191-spec-and-plan-lifecycle](../DEVELOPMENT_STANDARD.md#191-spec-and-plan-lifecycle): `draft`, `user-approved`, `active-plan`, `in-progress`, `implemented`, `superseded`, `blocked`, or `historical`.

When a spec or plan starts implementation, finishes, or is replaced, update the status or the relevant project-memory lane in the same governance round.

Durable architecture reference plans:

- [plans/2026-06-03-memory-platform-rag-retrieval.md](plans/2026-06-03-memory-platform-rag-retrieval.md)
- [plans/2026-06-04-memory-platform-vector-rag-next-phase.md](plans/2026-06-04-memory-platform-vector-rag-next-phase.md)
- [plans/2026-06-05-llm-model-protocol-routing-architecture.md](plans/2026-06-05-llm-model-protocol-routing-architecture.md)
- [plans/2026-06-07-general-data-processing-substrate.md](plans/2026-06-07-general-data-processing-substrate.md)
- [plans/2026-06-19-vibelution-agent-kernel-protocol-plan.md](plans/2026-06-19-vibelution-agent-kernel-protocol-plan.md)

## Archive Boundary

The 2026-05 implementation plans were moved to [archive/plans/2026-05/](archive/plans/2026-05/) because they are useful historical design evidence, but they should not compete with current task entrypoints.

Do not archive or delete `.docs/project-memory/**`, root `PROJECT_MEMORY.html`, or generated Challenge Cup HTML as part of ordinary docs cleanup. Those surfaces have their own governance paths.
