# Team workflow modules (`core/web/services/team_workflow`)

Agent-oriented ownership map for **research / Team workflow** backend orchestration.
Prefer editing a **pack module** over growing `team_workflow_orchestration_service.py` when possible.

Align language with frontend claim map: `web/src/routes/teams/README.md`.

`team_workflow_orchestration_service.py` remains the **public import facade** for
`core/web/routes/team_workflows/` (package) and other callers.

**Clarity P5/B1**: HTTP routes live in `core/web/routes/team_workflows/` package
(`orchestration.py`, `research_projects.py`, `source_collection.py`, `stage_rounds.py`,
`experiment.py`, `knowledge.py`, `research_ops.py`). Shared `router` is exported from
`__init__.py`. URL paths unchanged.

Historical structure/optimization notes (non-authoritative): `docs/archive/plans/2026-06-07/`.

## 30-second routing (edit here first)

| You are changing… | Open first |
|-------------------|------------|
| ensure/get orchestration document | `orchestration_core.py` |
| Candidates register/import/extract/list | `source_collection/candidates.py` |
| SC run start / search entry / summary | `source_collection/runs.py` |
| SC search execution body | `source_collection/search_execution.py` |
| SC stage task start/seed/gates | `source_collection/stage_session.py` (re-export: `stages.py`) |
| SC stage writeback/context/reconcile | `source_collection/stage_writeback.py` (re-export: `stages.py`) |
| SC stage reconcile / cards | `source_collection/stage_reconcile.py` |
| SC writeback materialize | `source_collection/writeback_materialize.py` |
| SC import/plan/exclusion/work-run residual | `source_collection/residual.py` |
| SC storage open | `source_collection/storage.py` |
| SC projection / summary helpers | `source_collection_projection.py` |
| SC agent session context seed | `source_collection_context.py` |
| Experiment plan/smoke/full-run (public re-export) | `experiment.py` → `experiment_api/` |
| Experiment plan/catalog/freeze/baseline | `experiment_api/plan.py` |
| Experiment hypothesis materialize/complete | `experiment_api/hypothesis.py` |
| Experiment smoke run/result | `experiment_api/smoke.py` |
| Experiment full run prepare/execute/register | `experiment_api/full_run.py` |
| Experiment result knowledge ingestion | `experiment_api/knowledge.py` |
| Experiment private kernel | `experiment_kernel.py` |
| Research loop / stage round | `research_loop.py` |
| Research-project Agent tasks / scoped sessions | `research_project_agent_tasks.py` + `research_project_agent_sessions.py` |
| Knowledge / steward / graph / paper-note entry | `knowledge.py` |
| Knowledge private kernel | `knowledge_kernel.py` |
| Iteration / export / inbox / stage-round glue | `workflow_ops.py` |
| Small shared workflow helpers | `facade_helpers.py` |
| Public import surface only | `../team_workflow_orchestration_service.py` (re-export shell) |

Frontend claim alignment: `web/src/routes/teams/README.md` when present. Structure awareness (soft): `docs/standards/development-standard.md` §8.3.

## Ownership map (claim scopes)

| Task type | Prefer these files | Avoid |
|-----------|-------------------|--------|
| ensure/get orchestration document | `orchestration_core.py` | session_service |
| Source-collection pure normalizers | `source_collection_common.py` | HTTP routes |
| SC stage task pure helpers | `source_collection_stage_tasks.py` | experiment smoke runs |
| SC stage session task start/writeback/context | `source_collection/stages.py` | experiment full-run |
| SC stage reconcile / cards projection / task message | `source_collection/stage_reconcile.py` | knowledge mega APIs |
| SC search execution kernel (impl/query/quality/bg) | `source_collection/search_execution.py` | knowledge mega APIs |
| SC writeback materialize kernel | `source_collection/writeback_materialize.py` | session_service |
| SC storage open | `source_collection/storage.py` | candidates register |
| SC projection / summary helpers | `source_collection_projection.py` | agent directory |
| SC agent session context seeding | `source_collection_context.py` | LLM client internals |
| Research memory context packing | `research_memory_context.py` | chat stream capture |
| Candidates register/import/extract/list | `source_collection/candidates.py` | pet system |
| SC runs / search entry + summaries | `source_collection/runs.py` | session list cache |
| Experiment plan/smoke/full-run APIs | `experiment.py` | session submit |
| Experiment private records/status/notify kernel | `experiment_kernel.py` | session_service |
| Research loop / stage round | `research_loop.py` | CLI terminal |
| Knowledge / graph / steward / coordination / paper-note APIs | `knowledge.py` | session_service |
| Knowledge private ingestion/graph/coordination kernel | `knowledge_kernel.py` | session_service |
| SC residual helpers (import/plan/exclusion/work-run) | `source_collection/residual.py` | session_service |
| Iteration/export/inbox/stage-round glue | `workflow_ops.py` | session_service |
| Residual private helpers | `facade_helpers.py` | new public mega APIs on facade |
| Public re-export shell | facade re-exports only | business logic on facade |
| Public HTTP-facing API surface | `../team_workflow_orchestration_service.py` (facade) | dumping new mega-functions into facade |

## Product surface ↔ packs

| Product / frontend language | Backend home |
|-----------------------------|--------------|
| ensure/get orchestration | `orchestration_core.py` |
| Candidates register/import/extract/list | `source_collection/candidates.py` |
| SC runs / search entry | `source_collection/runs.py` |
| SC search execution body | `source_collection/search_execution.py` |
| Stage agents / writeback entry | `source_collection/stages.py` + pure helpers in `source_collection_stage_tasks.py` |
| Stage writeback materialize body | `source_collection/writeback_materialize.py` |
| Stage reconcile / cards projection | `source_collection/stage_reconcile.py` |
| Storage open | `source_collection/storage.py` |
| Experiment design/execution entry | `experiment.py` |
| Experiment plan/status/notify kernel | `experiment_kernel.py` |
| Research loop / stage round | `research_loop.py` |
| Project Agent task lifecycle | `research_project_agent_tasks.py` |
| Knowledge ingestion / steward / graph / coordination entry | `knowledge.py` |
| Knowledge private kernel | `knowledge_kernel.py` |

## Sole-owner rules

1. **Do not** implement Team workflow business rules inside `session_service` except thin post-turn reconcile hooks that already exist.
2. Keep route imports stable via the orchestration facade until a later import-migration stage.
3. Pure normalizers stay free of FastAPI / Request objects.
4. Prefer vertical packs (SC / experiment / loop) over a single `helpers.py`.
5. When moving a public function, re-export it from the facade in the same change.

## Project Agent session identity

- Manual project tasks keep one flat session per project Agent.
- Formal workflow tasks carry both `workflowRunId` and `workflowNodeId`; their
  canonical Chat session is isolated by that exact pair. A different node or
  different Run must not reuse another node's messages or tool-result history.
- Partial workflow scope fails closed. Registry recovery reads the same scoped
  fields from the canonical session binding and never falls back to an
  unscoped Agent session.

## Extraction progress

### Stage 3 closed (product surfaces)

| Pack | ~LOC | Role |
|------|------|------|
| `orchestration_core.py` | ~64 | get/ensure orchestration |
| `source_collection/candidates.py` | ~591 | register/import/extract/list/validate |
| `source_collection/runs.py` | ~556 | start run / search entry / summaries |
| `source_collection/stages.py` | ~1052 | stage session task lifecycle entry |
| `source_collection/storage.py` | ~67 | open storage target |
| `experiment.py` | ~1148 | plan/smoke/full-run entrypoints |
| `research_loop.py` | ~374 | stage round status/start/retry |
| Pre-existing helpers | ~1.9k | common/projection/context/stage_tasks/memory |

### Service optimization Phase 1 (SC kernels)

| Pack | ~LOC | Role |
|------|------|------|
| `source_collection/search_execution.py` | ~1.1k | search impl / query / quality / bg / after-search sync |
| `source_collection/writeback_materialize.py` | ~2.7k | writeback normalize/merge + materialize_* |

### Service optimization Phase 2 (knowledge public APIs)

| Pack | ~LOC | Role |
|------|------|------|
| `knowledge.py` | ~3.6k | paper-note pipeline, source quality, graph, steward, ingestion/completion, coordination, transfer, local research model |

### Service optimization P1 / Phase 5 (stage residual + experiment kernel)

| Pack | ~LOC | Role |
|------|------|------|
| `source_collection/stage_reconcile.py` | ~2.9k | stage cards projection, reconcile, repair, task message/progress, stage support |
| `experiment_kernel.py` | ~1.4k | plan records, readiness, lifecycle projection, steward notify |
| Facade remainder (after Phase 5) | ~9.4k total lines | shared glue + residual helpers |

### Service optimization Phase 6 (knowledge private kernel)

| Pack | ~LOC | Role |
|------|------|------|
| `knowledge_kernel.py` | ~4.0k | ingestion/steward/graph/coordination/paper-note/source-quality private helpers |
| Facade remainder (after Phase 6) | ~5.7k total lines | shared glue residual |

**Phase 1 exit:** search + writeback execution bodies claimable outside facade.

**Phase 2 exit:** knowledge public mega APIs claimable in `knowledge.py`.

**Phase 5 (P1 residual) exit:** SC stage reconcile/projection + experiment private kernel claimable.

**Phase 6 exit:** knowledge private helpers claimable in `knowledge_kernel.py`; structure + knowledge-focused tests green.

**Still deferred:**

1. Full facade slim to re-exports only (remaining shared glue).
2. Late-bind removal (packs still call facade via `_service()`).
3. Session residual glue / secondary gods (`runtime_scene`, `agent_directory`).

## Related

- Routes: `core/web/routes/team_workflows/` (package)
- Frontend: `web/src/routes/teams/README.md`
- Historical plans: `docs/archive/plans/2026-06-07/`


### Service optimization Phase 15 (SC residual + workflow ops)

| Pack | ~LOC | Role |
|------|------|------|
| `source_collection/residual.py` | ~3.1k | import/plan/exclusion/work-run/extraction residual |
| `workflow_ops.py` | ~0.9k | propose_iteration, export, inbox, stage-round glue |
| facade after Phase 15 | ~2.0k | re-exports + thinner residual |


### Service optimization Phase 18 (facade helpers)

| Pack | ~LOC | Role |
|------|------|------|
| `facade_helpers.py` | ~0.9k | remaining workflow/stage/json helpers |
| facade after Phase 18 | ~1.2k | re-exports only (0 residual function defs) |
