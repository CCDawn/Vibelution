# Team workflow modules (`core/web/services/team_workflow`)

Agent-oriented ownership map for **research / Team workflow** backend orchestration.
Prefer editing a **pack module** over growing `team_workflow_orchestration_service.py` when possible.

Align language with frontend claim map: `web/src/routes/teams/README.md`.

`team_workflow_orchestration_service.py` remains the **public import facade** for
`core/web/routes/team_workflows.py` and other callers.

## Ownership map (claim scopes)

| Task type | Prefer these files | Avoid |
|-----------|-------------------|--------|
| ensure/get orchestration document | `orchestration_core.py` | session_service |
| Source-collection pure normalizers | `source_collection_common.py` | HTTP routes |
| SC stage task / writeback helpers | `source_collection_stage_tasks.py` | experiment smoke runs |
| SC projection / summary helpers | `source_collection_projection.py` | agent directory |
| SC agent session context seeding | `source_collection_context.py` | LLM client internals |
| Research memory context packing | `research_memory_context.py` | chat stream capture |
| Candidates register/import/extract/list | `source_collection/candidates.py` | pet system |
| SC runs / search / background | `source_collection/runs.py` (planned) | session list cache |
| SC storage open targets | `source_collection/storage.py` (planned) | supervised evolution |
| Experiment plan/smoke/full-run APIs | `experiment.py` (planned) | session submit |
| Research loop templates/status | `research_loop.py` (planned) | CLI terminal |
| Knowledge ingestion / graph / coordination | facade + planned `knowledge.py` | launcher daemon |
| Public HTTP-facing API surface | `../team_workflow_orchestration_service.py` (facade) | dumping new mega-functions into facade |

## Product surface ↔ packs

| Product / frontend language | Backend home |
|-----------------------------|--------------|
| ensure/get orchestration | `orchestration_core.py` |
| Candidates / quality entry (register/import/extract/list) | `source_collection/candidates.py` |
| SC runs / search | planned `source_collection/runs.py` (+ facade today) |
| Stage agents / writeback | `source_collection_stage_tasks.py` + facade `start_*` / `writeback_*` |
| Storage open | planned storage pack |
| Experiment design/execution | facade + planned `experiment.py` |
| Research loop | facade + planned `research_loop.py` |

## Sole-owner rules

1. **Do not** implement Team workflow business rules inside `session_service` except thin post-turn reconcile hooks that already exist.
2. Keep route imports stable via the orchestration facade until a later import-migration stage.
3. Pure normalizers stay free of FastAPI / Request objects.
4. Prefer vertical packs (SC / experiment / loop) over a single `helpers.py`.
5. When moving a public function, re-export it from the facade in the same change.

## Extraction progress

| Pack | Status | Notes |
|------|--------|--------|
| Map README | done | this file |
| Pre-existing helpers | done | `source_collection_*`, `research_memory_context` |
| `orchestration_core.py` | done | get/ensure entrypoints (late-bound facade) |
| `source_collection/candidates.py` | done | register/import/extract/list/validate entrypoints |
| `source_collection/runs.py` | planned | next vertical pack |
| storage / experiment / research_loop | planned | after runs |

## Related

- Routes: `core/web/routes/team_workflows.py`
- Frontend: `web/src/routes/teams/README.md`
- Structure plan: `docs/plans/2026-07-20-backend-structure-p0.md`
