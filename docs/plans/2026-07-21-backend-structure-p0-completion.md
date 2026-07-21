# Backend Structure P0 — Completion Note

Date: 2026-07-21
Plan: `docs/plans/2026-07-20-backend-structure-p0.md`
Status: **structure stages closed** (Stages 1–5 docs/hardening); optional deep facade slim deferred to maintenance/P1

## What closed

### Stage 1 — Ownership maps

- `core/web/services/session/README.md`
- `core/web/services/team_workflow/README.md`

### Stage 2 — Session hot path (claim packs)

| Module | Role |
|--------|------|
| `session/list_cache.py` | session list index cache |
| `session/live_output.py` | live overlay store + checkpoint I/O |
| `session/journal_bridge.py` | events cache / append / ledger seq |
| `session/submit.py` | message / guidance / edit-resubmit |
| `session/schedule.py` | queue / executor handoff |
| `session/stream_capture.py` | UI capture batching + hooks |
| `session/worker.py` | run turn + continuation |
| `session/persist.py` | turn result / failure writers |

Facade: `session_service.py` remains public import surface (~19.2k LOC remainder).

### Stage 3 — Team workflow product surfaces

| Module | Role |
|--------|------|
| `team_workflow/orchestration_core.py` | get/ensure orchestration |
| `team_workflow/source_collection/candidates.py` | register/import/extract/list |
| `team_workflow/source_collection/runs.py` | start run / search / summaries |
| `team_workflow/source_collection/stages.py` | stage session tasks |
| `team_workflow/source_collection/storage.py` | open storage target |
| `team_workflow/experiment.py` | experiment plan/smoke/full-run |
| `team_workflow/research_loop.py` | research stage round |

Plus pre-existing pure helpers under `team_workflow/`.
Facade: `team_workflow_orchestration_service.py` (~20.7k remainder).

### Stage 4 — Secondary gods

| Package | Pure cut |
|---------|----------|
| `agent_directory/profiles.py` | persona/task profile normalizers |
| `team/canvas_primitives.py` | canvas token/edge primitives |

Maps: `agent_directory/README.md`, `team/README.md`.

### Stage 5 — Hardening

- Conversation flow map owners for session hot path kept current.
- Facades documented as public import surfaces in package READMEs.
- Structure pack regression suite green (see evidence below).
- This completion note.

## Public import rule (stable)

Routes and external callers should continue to import from facades:

- `core.web.services.session_service`
- `core.web.services.team_workflow_orchestration_service`
- `core.web.services.agent_directory_service`
- `core.web.services.team_service`

Slice/pack modules are claim scopes for implementation; facades re-export public entrypoints.

## Protocol / version

- No intentional change to journal event types, SSE event names, or REST paths in mechanical stages.
- **Version impact:** none
- **Launcher refresh:** not needed for structure-only work
- **Remote push/PR:** not performed (requires explicit user authorization)

## What remains (out of P0 structure exit / P1 maintenance)

1. Full facade slim to re-exports-only (session projection/SSE; workflow private helpers/knowledge mega APIs).
2. Optional `session/projection.py`, workflow `knowledge.py`.
3. Agent list/get projection + mutations packs; team node/member normalize pack.
4. Full `scripts/local_quality_gate.py` or mega `test_team_workflow_orchestration_service` full file as release gate when shipping.

## Evidence (Stage 5 regression subset)

Stage 5 combined regression (2026-07-21 local):

- `tests/test_session_{list_cache,live_output,journal_bridge,submit,schedule,stream_capture,worker,persist}.py`
- `tests/test_team_workflow_structure_packs.py`
- `tests/test_stage4_secondary_structure.py`
- `tests/test_web_runtime_routes.py`

**Result: 148 passed**

Also used throughout P0: pack-scoped subsets of `tests/test_team_workflow_orchestration_service.py` at each workflow gate.

## Summary judgment

P0 **claimability goal met** for the two hottest gods (session + team workflow) plus secondary pure cuts.
P0 **did not** require facades to become empty shells; that remains optional maintenance.

Structure work is closed for planning purposes; further splits are demand-driven, not open-ended P0 continuation.
