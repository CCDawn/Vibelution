# Team workflow modules (`core/web/services/team_workflow`)

Agent-oriented ownership map for **research / Team workflow** backend orchestration.
Prefer editing a **pack module** over growing `team_workflow_orchestration_service.py` when possible.

Align language with frontend claim map: `web/src/routes/teams/README.md`.

During P0 structure work, `team_workflow_orchestration_service.py` remains the **public import facade** for `core/web/routes/team_workflows.py` and other callers. Existing extracted helpers already live in this package; continue that pattern.

## Ownership map (claim scopes)

| Task type | Prefer these files | Avoid |
|-----------|-------------------|--------|
| ensure/get orchestration document | `orchestration_core.py` (planned) or facade until extracted | session_service |
| Source-collection pure normalizers | `source_collection_common.py` | HTTP routes |
| SC stage task / writeback helpers | `source_collection_stage_tasks.py` | experiment smoke runs |
| SC projection / summary helpers | `source_collection_projection.py` | agent directory |
| SC agent session context seeding | `source_collection_context.py` | LLM client internals |
| Research memory context packing | `research_memory_context.py` | chat stream capture |
| SC runs / search / background | `source_collection/runs.py` (planned) | session list cache |
| SC storage open targets | `source_collection/storage.py` (planned) | supervised evolution |
| Candidates register/import/extract | `source_collection/candidates.py` (planned) | pet system |
| Experiment plan/smoke/full-run APIs | `experiment.py` (planned) | session submit |
| Research loop templates/status | `research_loop.py` (planned) | CLI terminal |
| Knowledge ingestion / graph / coordination status | `knowledge.py` or candidates pack (planned) | launcher daemon |
| Public HTTP-facing API surface | `../team_workflow_orchestration_service.py` (facade) | dumping new mega-functions into facade |

## Product surface ↔ packs

| Product / frontend language | Backend home |
|-----------------------------|--------------|
| SC runs / search | planned `source_collection/runs.py` (+ facade entrypoints today) |
| Stage agents / writeback | `source_collection_stage_tasks.py` + facade `start_*` / `writeback_*` |
| Storage open | planned storage pack |
| Candidates / quality / paper_note | facade + planned candidates pack |
| Experiment design/execution | facade + planned `experiment.py` |
| Research loop | facade + planned `research_loop.py` |
| ensure/get orchestration | facade + planned `orchestration_core.py` |

## Sole-owner rules

1. **Do not** implement Team workflow business rules inside `session_service` except thin post-turn reconcile hooks that already exist.
2. Keep route imports stable via the orchestration facade until Stage 5.
3. Pure normalizers stay free of FastAPI / Request objects.
4. Prefer vertical packs (SC / experiment / loop) over a single `helpers.py`.
5. When moving a public function, re-export it from the facade in the same change.

## Already extracted (pre-P0 / continue)

| File | Role |
|------|------|
| `source_collection_common.py` | pure stage/role/metadata normalizers |
| `source_collection_projection.py` | SC projection helpers |
| `source_collection_context.py` | SC context helpers |
| `source_collection_stage_tasks.py` | stage task helpers |
| `research_memory_context.py` | research memory context packing |

## Extraction progress

- **Done (map):** this README.
- **Partial:** source_collection_* helpers above.
- **Planned:** orchestration_core, runs/search, storage, candidates pack, experiment, research_loop, facade slim.

## Related

- Routes: `core/web/routes/team_workflows.py`
- Frontend: `web/src/routes/teams/README.md`
- Structure plan: `docs/plans/2026-07-20-backend-structure-p0.md`
