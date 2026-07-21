# Team workflow modules (`core/web/services/team_workflow`)

Agent-oriented ownership map for **research / Team workflow** backend orchestration.
Prefer editing a **pack module** over growing `team_workflow_orchestration_service.py` when possible.

Align language with frontend claim map: `web/src/routes/teams/README.md`.

`team_workflow_orchestration_service.py` remains the **public import facade** for
`core/web/routes/team_workflows.py` and other callers.

**P0 structure closed** (2026-07-21): see `docs/plans/2026-07-21-backend-structure-p0-completion.md`.

**Service optimization Phase 1** (2026-07-21): SC search + writeback kernels — `docs/plans/2026-07-21-service-optimization-phase1-sc-search-kernel.md`.

**Service optimization Phase 2** (2026-07-21): knowledge / graph / steward public APIs — `docs/plans/2026-07-21-service-optimization-phase2-knowledge.md`.

## Ownership map (claim scopes)

| Task type | Prefer these files | Avoid |
|-----------|-------------------|--------|
| ensure/get orchestration document | `orchestration_core.py` | session_service |
| Source-collection pure normalizers | `source_collection_common.py` | HTTP routes |
| SC stage task pure helpers | `source_collection_stage_tasks.py` | experiment smoke runs |
| SC stage session task start/writeback/context | `source_collection/stages.py` | experiment full-run |
| SC search execution kernel (impl/query/quality/bg) | `source_collection/search_execution.py` | knowledge mega APIs |
| SC writeback materialize kernel | `source_collection/writeback_materialize.py` | session_service |
| SC storage open | `source_collection/storage.py` | candidates register |
| SC projection / summary helpers | `source_collection_projection.py` | agent directory |
| SC agent session context seeding | `source_collection_context.py` | LLM client internals |
| Research memory context packing | `research_memory_context.py` | chat stream capture |
| Candidates register/import/extract/list | `source_collection/candidates.py` | pet system |
| SC runs / search entry + summaries | `source_collection/runs.py` | session list cache |
| Experiment plan/smoke/full-run APIs | `experiment.py` | session submit |
| Research loop / stage round | `research_loop.py` | CLI terminal |
| Knowledge / graph / steward / coordination / paper-note APIs | `knowledge.py` | session_service |
| Residual private helpers still on facade | facade remainder | new public mega APIs on facade |
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
| Storage open | `source_collection/storage.py` |
| Experiment design/execution | `experiment.py` |
| Research loop / stage round | `research_loop.py` |
| Knowledge ingestion / steward / graph / coordination | `knowledge.py` |

## Sole-owner rules

1. **Do not** implement Team workflow business rules inside `session_service` except thin post-turn reconcile hooks that already exist.
2. Keep route imports stable via the orchestration facade until a later import-migration stage.
3. Pure normalizers stay free of FastAPI / Request objects.
4. Prefer vertical packs (SC / experiment / loop) over a single `helpers.py`.
5. When moving a public function, re-export it from the facade in the same change.

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
| Facade remainder (after Phase 2) | ~13.4k total lines | private helpers, residual glue |

**Phase 1 exit:** search + writeback execution bodies claimable outside facade.

**Phase 2 exit:** knowledge/graph/steward/coordination public mega APIs claimable in `knowledge.py`; private helpers still late-bound on facade; structure + focused knowledge/routes tests green.

**Still deferred:**

1. Full facade slim to re-exports only (move remaining private helpers).
2. Late-bind removal (packs still call facade via `_service()` for shared helpers).
3. Session projection/SSE packs (separate optimization track).

## Related

- Routes: `core/web/routes/team_workflows.py`
- Frontend: `web/src/routes/teams/README.md`
- Structure plan: `docs/plans/2026-07-20-backend-structure-p0.md`
- Phase 1 plan: `docs/plans/2026-07-21-service-optimization-phase1-sc-search-kernel.md`
- Phase 2 plan: `docs/plans/2026-07-21-service-optimization-phase2-knowledge.md`
