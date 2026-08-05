# Service Optimization Phase 1 — SC Search / Writeback Kernel

Date: 2026-07-21
Status: **phase1_closed** (Gate 1.1–1.3 executed in worktree `codex/svc-opt-p1-sc-search`)
Owner lane: backend web services / team_workflow
Parent context: P0 structure closed (`docs/plans/2026-07-21-backend-structure-p0-completion.md`); service analysis (session).
Related maps: `core/web/services/team_workflow/README.md`

## 1. Goal

Eliminate the **split-brain** where SC product entrypoints live in packs (`runs.py` / `stages.py`) while the heavy execution bodies remain in `team_workflow_orchestration_service.py`.

**Success = claimable ownership of SC search + stage writeback materialization kernels**, with public imports still on the facade, behavior unchanged.

## 2. Why this phase (not session / knowledge)

| Evidence | Implication |
|----------|-------------|
| `runs.execute_source_collection_search` → `s._execute_source_collection_search_impl` | Entry already claimed; body ~505 LOC still on facade |
| Facade still holds search helpers cluster | Named search-path helpers ≈ **1.2k LOC** (impl + bg + query + quality + plan/sync) |
| `stages.writeback_*` → five `_materialize_*` + large helper web | Writeback/materialize-named funcs ≈ **2.9k LOC** still on facade |
| Tests call facade symbols + monkeypatch facade | Must keep re-export / attribute identity for patches |
| Knowledge mega APIs deferred | Out of Phase 1 (later optimization phase) |

## 3. Scope

### In scope

**Gate 1.1 — Search execution kernel** (primary, ship first)

| Symbol / cluster | Approx LOC | Target home |
|------------------|------------|-------------|
| `_execute_source_collection_search_impl` | ~505 | `source_collection/search_execution.py` (new) **or** fold into `runs.py` if file stays &lt; ~1.5k |
| `_run_source_collection_search_background` | ~27 | same pack |
| `_source_collection_search_background_response` | ~53 | same pack |
| `_sync_source_collection_stage_round_after_search` | ~100 | same pack (search completion side-effect) |
| `_source_collection_stage_round_status_after_search` | ~27 | same pack |
| `_execute_source_collection_query` | ~26 | same pack |
| `_source_collection_search_result_quality_gate` + quality terms | ~56 | same pack |
| `_source_collection_record_from_search_result` + search trace | ~69 | same pack |
| Exclusion / identity / next-query / execution event helpers **only if** call graph is search-private | ~150–250 | same pack |
| Plan build/write/ref used by start-run **and** search | ~117 | **prefer leave on facade** or pure helper module if already shared with `start_source_collection_run` — do not break runs start path |

**Gate 1.2 — Stage writeback materialize kernel** (after 1.1 green)

| Cluster | Approx LOC | Target home |
|---------|------------|-------------|
| `_materialize_source_collection_stage_writeback_*` (sources / content / quality / graph / knowledge_ingestion / record_extractions / invalid_sources) | ~1.0k+ | `source_collection/writeback_materialize.py` (new) |
| Direct private helpers only used by those materializers (ids, coverage, summaries, record payload, quality notes, steward pack fragments **if** solely writeback) | remainder of ~2.9k named set | same pack; **stop** when a helper is shared with knowledge public APIs or non-SC paths |

**Gate 1.3 — Docs / structure tests / README map**

- Update `team_workflow/README.md` ownership rows.
- Extend `tests/test_team_workflow_structure_packs.py` re-export / module-home asserts.
- Brief execution log on this plan file.

### Out of scope (explicit)

1. Session facade / projection / SSE.
2. Knowledge public mega APIs (`run_knowledge_collection_*`, steward HTTP surface) — next optimization phase.
3. Full late-bind elimination across all SC packs (only reduce `s.` for symbols **moved into the same pack**).
4. Changing REST paths, JSON field names, work-run phase strings, or runtime-scene event names.
5. Import-path migration off the facade for routes/tests.
6. Performance tuning / query provider changes.
7. `agent_directory` / `team_service` / `runtime_scene` secondary gods.

## 4. Recommended design

### 4.1 Placement

```
core/web/services/team_workflow/source_collection/
  runs.py                 # public: start run / execute / background / summaries (thin orchestration)
  search_execution.py     # NEW Gate 1.1: impl + query + quality + bg thread target + after-search sync
  stages.py               # public: stage task lifecycle (stays)
  writeback_materialize.py # NEW Gate 1.2: materialize_* + writeback-private helpers
  candidates.py / storage.py  # unchanged ownership
```

**Why not dump everything into `runs.py`:** Gate 1.1 alone can exceed ~1k LOC; `runs.py` already ~557. Vertical `search_execution.py` keeps claim scope “search kernel” vs “run summary API”.

**Why writeback not under `stages.py`:** `stages.py` already ~1k; materialize cluster ~2k+ would recreate a god file. Separate pack + stages late-bind or direct import.

### 4.2 Binding strategy (same as Stage 3)

- New modules use `_service()` late-bind to facade for: locks, normalize helpers left behind, `data_processing_service`, `team_service`, `TeamWorkflowOrchestrationError`, work-run store, shared constants.
- Facade **imports** moved symbols and binds them as module attributes so:
  - `from core.web.services.team_workflow_orchestration_service import execute_source_collection_search` unchanged
  - `monkeypatch.setattr(facade, "start_source_collection_search_background", ...)` still works
  - Tests calling `facade._execute_source_collection_search_impl` / `_materialize_*` keep working **via re-export**
- Prefer: **move body once**, leave **name on facade as same object** (`from .team_workflow.source_collection.search_execution import _execute_...` then either keep private name on facade or assign after import).

### 4.3 Call-graph fix after move

Current:

```
runs.execute_source_collection_search
  -> s._execute_source_collection_search_impl   # facade
runs.start_source_collection_search_background
  -> s._run_source_collection_search_background # facade thread target
facade._run_source_collection_search_background
  -> execute_source_collection_search           # pack (already)
```

Target:

```
runs.execute_source_collection_search
  -> search_execution._execute_source_collection_search_impl  # same pack family; may call via s. for patchability
OR keep s._execute_... which is re-exported from search_execution (preserves monkeypatch on facade)
```

**Patchability rule:** any symbol tests or production may monkeypatch on the facade must remain an attribute of `team_workflow_orchestration_service` pointing at the implementation function object.

### 4.4 Extraction order (mechanical safety)

For each gate:

1. Create target module with module docstring + `_service()`.
2. Cut contiguous functions (prefer bottom-up: leaves first, then impl).
3. Facade: import + re-export; **delete** original bodies (no duplicate defs).
4. Run focused tests before next symbol batch.
5. If a helper is shared with start-run / knowledge / experiment: **leave on facade** or extract to pure module without forcing full late-bind rewrite.

## 5. Risk register

| Risk | Level | Mitigation |
|------|-------|------------|
| Behavior drift in search dedupe / quality gate / work-run phases | Med-High | No logic edits; only moves; run existing `test_execute_source_collection_search_*` suite |
| Circular import (`search_execution` → facade → pack) | Med | Keep late-bind `_service()`; facade imports packs at bottom or existing Stage 3 import block pattern |
| Missing re-export of private used by tests/stages | Med | Grep for `_execute_source_collection` / `_materialize_source_collection` / `_sync_source_collection_stage_round_after_search` before delete |
| Writeback helper also used by knowledge ingestion public path | Med | Gate 1.2 stop condition: if helper called from knowledge public API, leave on facade or dual-re-export without renaming |
| Oversized single PR / dirty main | Low-Med | Prefer worktree `codex/svc-opt-p1-sc-search` per `Agents.md`; merge after each gate green |
| Hot-file collision with other agents | Med | Claim via project-memory guard before edit |

## 6. Verification contract

### Per gate (must pass)

```text
# Structure identity
tests/test_team_workflow_structure_packs.py

# SC search behavior (Gate 1.1; also smoke after 1.2)
tests/test_team_workflow_orchestration_service.py -k "execute_source_collection_search"

# Writeback / materialize (Gate 1.2)
tests/test_team_workflow_orchestration_service.py -k "writeback or materialize_source_collection"

# Routes monkeypatch surface (both gates)
tests/test_team_workflow_routes.py
```

Optional wider smoke after Gate 1.2: `tests/test_web_runtime_routes.py` if time permits (not a hard gate for pure moves).

### Success evidence checklist

- [ ] No duplicate function bodies for moved symbols (only one definition site).
- [ ] Facade attributes for moved symbols are the pack functions (`is` identity in structure test).
- [ ] `runs.py` / `stages.py` still public entry owners; README updated.
- [ ] Facade LOC drop roughly tracks moved LOC (expect **~1.0–1.2k** after 1.1, **+~1.5–2.5k** after 1.2 depending on helper cutoff).
- [ ] Version impact: **none**; Launcher refresh: **not needed** (structure-only).
- [ ] No REST/protocol string changes in diff.

### Stop / rollback

- Any failing `test_execute_source_collection_search_*` → fix or revert gate commit; do not open Gate 1.2.
- Unexpected circular import at import time → keep more helpers on facade, thinner pack.
- Active claim / dirty unrelated main → stop and report; do not force.

## 7. Task graph

Mode: **TASK_GRAPH** (serial gates; Gate 1.2 depends on 1.1 green; shared facade file).

```text
Task 1.0: Claim + worktree + baseline tests
- Owner: current backend structure agent
- Boundary: no production code yet
- Mode: SIMPLE
- Verification: record baseline pass counts for structure + search -k suite
- Stop: baseline red → diagnose before moves

Task 1.1a: Add search_execution.py; move leaf search helpers + query + quality + record_from_result
- Dependency: 1.0
- Mode: SIMPLE (mechanical)
- Verification: import facade; structure tests; search -k

Task 1.1b: Move _execute_source_collection_search_impl + background + after-search sync; re-export
- Dependency: 1.1a
- Mode: SIMPLE
- Verification: full Gate 1.1 suite; grep no second def of moved names

Task 1.1c: README + structure asserts for search_execution; plan log 1.1 closed
- Dependency: 1.1b
- Mode: SIMPLE
- Verification: structure packs green; docs match files

Task 1.2a: Add writeback_materialize.py; move materialize_* entrypoints used by stages.writeback
- Dependency: 1.1c
- Mode: SIMPLE
- Verification: materialize/writeback -k; stages still call via s. or direct re-export

Task 1.2b: Move writeback-private helpers required by materialize cluster; leave shared/knowledge helpers
- Dependency: 1.2a
- Mode: SIMPLE
- Verification: Gate 1.2 suite; manual grep of knowledge public callers

Task 1.3: Closeout — README ownership, plan status closed, optional routes smoke
- Dependency: 1.2b
- Mode: SIMPLE
- Verification: success evidence checklist complete
```

**Critical path:** 1.0 → 1.1a → 1.1b → 1.1c → 1.2a → 1.2b → 1.3

**Parallelism:** none on facade/packs (same write surface).

**Natural user gates:** after **1.1c** (search done) and after **1.3** (phase complete). Continuous execution within a gate is preferred; do not pause mid-move for status-only reports.

## 8. Non-goals restated for implementers

- Do not “improve” search quality, provider selection, or work-run copy while moving.
- Do not rename public API functions.
- Do not expand into `experiment.py` or research_loop unless a moved symbol is incorrectly placed (fix ownership, don’t feature-creep).

## 9. Version / ops

| Item | Decision |
|------|----------|
| Version impact | none (structure only) |
| Launcher refresh | not needed for structure-only; recommended only if operator will manually exercise SC UI |
| Push / PR | only on explicit user request |
| Worktree | recommended: `C:\Users\17533\Desktop\Vibelution-worktrees\svc-opt-p1-sc-search` branch `codex/svc-opt-p1-sc-search` from local `main` |

## 10. Open decisions (resolved defaults)

| Question | Default for execution |
|----------|---------------------|
| New file vs grow `runs.py`? | **New `search_execution.py`** |
| Keep late-bind on moved code? | **Yes** for cross-cutting helpers left on facade |
| Include writeback in Phase 1? | **Yes as Gate 1.2**, after search green |
| Include knowledge pack? | **No** |
| Full pure decoupling of search pack? | **No** (deferred maintenance) |

If product owner wants **search-only Phase 1**, cancel Tasks 1.2* and close after 1.1c with plan status `phase1_search_closed; writeback deferred`.

## 11. Execution log

| When | Gate | Notes |
|------|------|-------|
| 2026-07-21 | plan | Plan authored from service analysis; no code moved yet |
| 2026-07-21 | 1.0 | Worktree `svc-opt-p1-sc-search` / branch `codex/svc-opt-p1-sc-search`; baseline search tests green |
| 2026-07-21 | 1.1 | Added `search_execution.py` (~1.1k); facade re-exports; sibling calls via `s.` for monkeypatch |
| 2026-07-21 | 1.2 | Added `writeback_materialize.py` (~2.7k); facade re-exports; materialize/normalize cluster moved |
| 2026-07-21 | 1.3 | README + structure asserts; facade ~17k lines (was ~20.7k); SC search/writeback + routes subset green |
