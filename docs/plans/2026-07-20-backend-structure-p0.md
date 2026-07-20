# Backend Structure P0 Plan

Date: 2026-07-20
Status: in_progress
Owner lane: backend structure / web services
Related: frontend bundle+claim phase (closed); `docs/agents/conversation-flow-map.md`; backend structure review (session)

### Execution log

| When | Stage | Notes |
|------|-------|--------|
| 2026-07-20 | 1 | Added `session/README.md`, `team_workflow/README.md` |
| 2026-07-20 | 2.1 | Extracted `session/list_cache.py`; facade wraps invalidate + collision repair |
| 2026-07-20 | 2.2 | Extracted `session/live_output.py` (store + checkpoint I/O); stream publish / timeline enrichment stay on facade |
| 2026-07-20 | 2.3 | Extracted `session/journal_bridge.py` (events cache + append + ledger seq); facade forwards PROJECT_ROOT |
| 2026-07-20 | 2.4 | Extracted `session/submit.py` (message/guidance/edit-resubmit entrypoints); late-bound facade helpers |
| 2026-07-20 | 2.5 | Extracted `session/schedule.py` (queue/executor handoff); executor/scheduler globals stay on facade |

## 1. Problem Statement

Backend directories look modular (`core/web/routes`, `core/chat`, `core/llm`, …), but **application weight concentrates in a few god services**:

| File | ~LOC | Role |
|------|------|------|
| `core/web/services/team_workflow_orchestration_service.py` | ~22.9k | Research / source-collection / experiment / loop orchestration |
| `core/web/services/session_service.py` | ~22.4k | Session submit, schedule, worker, stream, persist, list cache |
| `core/web/services/agent_directory_service.py` | ~7.1k | Agent directory / binding surface |
| `core/web/services/team_service.py` | ~5.7k | Team CRUD / membership / canvas-adjacent |

HTTP routes (`core/web/routes/*`) are comparatively thin; **structure debt is service-layer, not FastAPI wiring**.
Tests mirror the gods (`test_team_workflow_orchestration_service.py`, `test_web_app.py`, …), so refactor cost is doubled without a staged plan.

Front-end P0 already cleared bundle budgets and started Teams claim maps. Backend P0 should **not** copy a “LOC diet”; it should produce **claimable ownership + behavior-preserving splits** on the two hottest services first.

## 2. P0 Goals

1. **Claimability:** Any Agent can claim a *named slice* without editing a 20k-line file by default.
2. **Hot-path safety:** Chat session turn path remains behavior-stable and covered by existing maps/tests.
3. **Workflow symmetry:** Research/Team workflow backend slices align with frontend Teams pure/claim language (SC / experiment / loop).
4. **Measurable progress:** Each stage has exit criteria (map exists, imports re-export, tests green, no protocol change).
5. **No empty ceremony:** No framework rewrite, no big-bang rewrite of tools/LLM.

## 3. Non-Goals (explicitly out of P0)

- Rewriting FastAPI or replacing React Query / SSE contracts.
- Changing turn journal semantics, ledger sequence rules, or public DTO shapes unless a bug forces it.
- Full decomposition of `agent.py`, `core/llm/client.py`, or all of `tools/`.
- Parallel mega-refactor of frontend Teams + backend orchestration in the same merge window.
- Performance micro-benchmarks as a gate (only correctness + structure gates).
- Remote push/PR unless the user authorizes later.

## 4. Principles

1. **Map before move** — ownership README first; code second.
2. **Behavior freeze during mechanical splits** — re-export facades keep import paths stable where possible.
3. **Follow existing product maps** — session splits follow `docs/agents/conversation-flow-map.md`; workflow splits follow Teams frontend domain language.
4. **Vertical slices over horizontal “utils.py” dumps** — prefer `session_submit.py` / `source_collection_run.py`, not `helpers2.py`.
5. **Tests move with code** — extract or add focused tests when cutting a slice; do not only grow mega-tests.
6. **One god at a time for deep cuts** — session and workflow may be staged sequentially; avoid simultaneous deep rewrites.
7. **Evidence before theory** — runtime_scenes / failing tests drive repair; do not “clean architecture” by feel.
8. **Version impact** — pure structure: `none`; if API/DTO changes: escalate out of P0 mechanical track.

## 5. Success Criteria (P0 complete)

### Hard gates

| Gate | Criterion |
|------|-----------|
| Ownership maps | `session` + `team_workflow` README/claim tables exist and match real symbols |
| Session facade | `session_service.py` remains public entry **or** documented re-export module; call sites compile |
| Workflow facade | same for `team_workflow_orchestration_service` |
| Tests | Relevant suites green: session routes/service tests, team workflow service/routes tests, chat protocol smoke if available |
| Protocol | No intentional change to journal event types, SSE event names, or REST paths in mechanical stages |
| Claims | Active work uses project-memory claim scopes per slice |
| Docs | Plan progress section updated; conversation-flow-map still accurate or patched |

### Soft / quality targets (P0 end, not line-count vanity)

| Target | Intent |
|--------|--------|
| Session monolith | Reduced to **facade + ≤6–8 owned modules** with clear names from flow map |
| Workflow monolith | Reduced to **facade + domain packs** (at least SC run/search, stage task, experiment/loop hooks, candidate/knowledge) |
| New code | Prefer landing in slice modules, not growing facade body |
| Claim default | Editing session stream path does not require opening workflow file, and vice versa |

Exact LOC of facades is secondary to **clear sole owners**.

## 6. Target Architecture (P0)

```text
core/web/routes/*.py                    # keep thin; only adjust imports if needed
core/web/services/
  session_service.py                    # facade: re-export public API
  session/
    README.md                           # ownership map
    list_cache.py
    live_output.py
    journal_bridge.py                   # conversation events / ledger helpers
    submit.py                           # submit_session_message*
    schedule.py                         # queue / schedule turn
    worker.py                           # _run_session_turn orchestration
    stream_capture.py                   # UI stream → journal/SSE
    persist.py                          # turn result persistence
    projection.py                       # detail/list DTO builders (if extracted)
  team_workflow_orchestration_service.py  # facade
  team_workflow/
    README.md
    orchestration_core.py               # ensure/get orchestration state
    source_collection/
      runs.py                           # start run, search, background
      stages.py                         # stage session task / writeback
      storage.py                        # open storage targets
      candidates.py                     # register/import/extract candidates
    experiment.py                       # experiment plan/smoke/full-run entrypoints (or thin delegates)
    research_loop.py                    # loop templates/status entrypoints
    knowledge.py                        # knowledge ingestion / steward hooks (as needed)
    common.py                           # shared errors, utc_now, pure normalizers

core/chat, core/llm, …                  # domain packages: receive pure logic when ready
agent.py                                # unchanged in P0 mechanical track
```

**Import stability strategy**

- Phase A–B: keep `from core.web.services.session_service import submit_session_message` working via re-exports.
- Only after facades stabilize, optionally migrate internal imports to submodules (not required for P0 exit).

## 7. Work Stages

### Stage 0 — Align & inventory (0.5–1 day)

**Do**

- Confirm this plan with user (or treat “规划方案” acceptance as go).
- Freeze P0 scope: session + team_workflow (+ optional map-only for directory/team).
- Inventory public symbols:
  - exported functions used by `core/web/routes/sessions.py`, `team_workflows.py`, tests.
  - internal `_run_*` / background jobs.

**Exit**

- Symbol inventory appendix (can live in stage READMEs).
- Claim scopes reserved if multi-agent.

### Stage 1 — Ownership maps only (0.5–1 day) 【must first】

**Deliverables**

1. `core/web/services/session/README.md`
   - Table: task type → prefer files → avoid
   - Map rows to conversation-flow-map steps 1–11
   - Sole owners: submit, worker, stream, journal, list cache
2. `core/web/services/team_workflow/README.md`
   - Table aligned with frontend `web/src/routes/teams/README.md` language
   - SC run/search/stage/storage/candidates vs experiment vs loop

**Rules**

- No behavior code changes required.
- Link from `docs/agents/conversation-flow-map.md` (one line pointer).

**Exit**

- Maps merged; reviewers can assign claims without reading 20k lines.

### Stage 2 — Session service mechanical split (3–6 days)

Order (dependency-safe):

| Step | Module | Pull from session_service (examples) | Validation |
|------|--------|--------------------------------------|------------|
| 2.1 | `session/list_cache.py` | list cache get/set/invalidate | list sessions tests |
| 2.2 | `session/live_output.py` | checkpoint load/write/delete/discard | live overlay / recovery tests |
| 2.3 | `session/journal_bridge.py` | conversation events cache, append helpers, ledger seq | journal/event tests |
| 2.4 | `session/submit.py` | `submit_session_message*` | POST messages + async prefer |
| 2.5 | `session/schedule.py` | schedule/queue helpers | busy/queue state tests |
| 2.6 | `session/stream_capture.py` | `_capture_session_ui_stream` and batching | assistant_delta / tool events |
| 2.7 | `session/worker.py` | `_run_session_turn` continuation loop orchestration | full turn success/fail/interrupt |
| 2.8 | `session/persist.py` | `_persist_session_turn_result` | final session_detail |
| 2.9 | Facade slim | re-exports only + thin wrappers | full session suite |

**Constraints**

- Do **not** change SSE event names or journal event types.
- Prefer move-then-reexport commits; one step one commit when possible.
- If a step needs semantic change, stop and reclassify as bugfix, not structure.

**Primary tests (adjust to repo actual names)**

- `tests/test_web_runtime_routes.py` / session-related
- `tests/test_multi_agent_conversations.py` (if session coupling)
- Any `session_service` focused tests
- Optional live: `scripts/chat_protocol_live_acceptance.py` when workbench up

### Stage 3 — Team workflow mechanical split (4–8 days)

Order by **frontend/product surfaces** (not random LOC):

| Step | Pack | Examples already in file | Validation |
|------|------|--------------------------|------------|
| 3.1 | `orchestration_core` | `get/ensure_team_workflow_orchestration` | basic workflow GET |
| 3.2 | `source_collection/candidates` | register/import/extract candidates | candidate tests/routes |
| 3.3 | `source_collection/runs` | start run, execute/search background | SC run/search tests |
| 3.4 | `source_collection/stages` | stage session task, writeback, context | stage task tests |
| 3.5 | `source_collection/storage` | open storage target | storage open tests |
| 3.6 | `experiment` | plan/smoke/full-run/knowledge entrypoints used by routes | experiment route/service tests |
| 3.7 | `research_loop` | templates/status/create/evidence/decision | research_loop routes |
| 3.8 | Facade slim | re-export public API for `team_workflows` routes | `test_team_workflow_*` |

**Constraints**

- Keep route imports stable via facade.
- Align pack names with frontend pure modules language (SC / experiment / loop).
- Do not merge unrelated “cleanup” into SC run extraction.

**Primary tests**

- `tests/test_team_workflow_orchestration_service.py` (split gradually or add pack-level tests)
- `tests/test_team_workflow_routes.py`
- Research/SC related suites as touched

### Stage 4 — Secondary gods (map + one cut each) (2–4 days, optional within P0 if time)

Only after Stage 2–3 facades are stable:

| Service | P0 action |
|---------|-----------|
| `agent_directory_service.py` | Ownership map + extract **read projections** vs **mutations** if hot |
| `team_service.py` | Ownership map + extract pure canvas/member helpers if contested |

If calendar tight: **maps only** for Stage 4; code cuts deferred to P1.

### Stage 5 — Hardening & close (1–2 days)

- Update conversation-flow-map module paths if symbols moved.
- Ensure facades documented as “public import surface”.
- Run broader regression: `scripts/local_quality_gate.py` or project-standard backend subset.
- Write short **P0 completion note** (what closed / what remains).
- Release claims; version impact judgment: structure-only → `none`.

## 8. Task Graph (DAG)

```text
Stage0 inventory
    → Stage1 maps (session + workflow)
        → Stage2 session splits (2.1→2.9 sequential preferred)
        → Stage3 workflow splits (3.1→3.8; can start 3.1 after Stage1 even if Stage2 mid-way,
           but avoid same agent editing both facades)
            → Stage4 secondary (optional)
                → Stage5 close
```

**Parallelism**

- Safe: Stage1 session map ∥ Stage1 workflow map (two agents).
- Risky: Stage2 deep cut ∥ Stage3 deep cut on same branch without worktrees.
- Preferred multi-agent: one agent owns **session/**, one owns **team_workflow/** after maps land, separate worktrees, merge session first if conflict on shared `services/__init__` or routes.

## 9. Claim Scopes (suggested)

| Claim id (example) | Paths |
|--------------------|--------|
| `backend-session-map` | `core/web/services/session/README.md`, flow-map pointer |
| `backend-session-split` | `core/web/services/session/**`, `session_service.py` facade |
| `backend-workflow-map` | `core/web/services/team_workflow/README.md` |
| `backend-workflow-split` | `core/web/services/team_workflow/**`, orchestration facade |
| `backend-structure-p0-close` | plan status, completion note |

Hot files: facades remain hot; require narrow staging and stronger tests.

## 10. Validation Matrix

| Change type | Minimum validation |
|-------------|-------------------|
| Map-only | doc review; no tests required |
| Move pure helpers | unit/import tests; no protocol tests if pure |
| Move submit/worker/stream | session route + turn path tests; prefer runtime_scene on failure |
| Move SC run/search | workflow service + routes tests |
| Facade re-export only | import smoke + previously failing suite |
| Any accidental API change | stop; add contract test; reclassify |

**Workbench live (optional but high value after Stage2.4+):**

- Start workbench via Launcher.
- One Chat message stream (async submit + SSE).
- One Teams SC run or read path if SC code moved.

## 11. Risk Register

| Risk | Mitigation |
|------|------------|
| Silent behavior drift in stream/journal | Freeze event names; compare tests; use flow map as oracle |
| Merge conflicts on facade | One writer per facade; re-export only patches |
| Test file still 20k lines | Follow code with pack-level tests; split tests in same stage when cost is low |
| Over-split into 50 microfiles | Cap packs per plan tables; no file without README row |
| Scope creep into agent.py/tools | Refuse in P0; file as P1 |
| Dual EventSource / dual workers | Session stage: keep single schedule/worker owner |

## 12. Effort Band (calendar, 1 experienced agent)

| Stage | Days |
|-------|------|
| 0–1 | 1–2 |
| 2 | 3–6 |
| 3 | 4–8 |
| 4 | 1–4 |
| 5 | 1–2 |
| **Total** | **~10–22 days** |

Two specialized agents (session ∥ workflow after maps) can compress wall-clock ~30–40%, not total effort.

## 13. Version, Git, Runtime

- **Version impact:** structure-only stages → `none`. Escalate if REST/SSE/journal changes.
- **Git:** worktrees under project protocol; root `main` integration after merge gates; no push without user ask.
- **Launcher:** structure-only → refresh **not needed**; behavior verification → refresh **recommended before user testing**.

## 14. P1 Backlog (after P0 close)

- Split mega-tests alongside remaining service body.
- `agent.py` phase extraction (context build / tool loop / result format).
- `agent_directory_service` / `team_service` deep cuts.
- tools registry cleanup (`Key_Tools` etc.).
- Optional: domain logic migration from web services into `core/research` / `core/chat` packages (only when boundaries proven).

## 15. Immediate Next Action

When user approves execution:

1. Open claim `backend-session-map` + `backend-workflow-map`.
2. Land Stage 1 READMEs (no code behavior change).
3. Start Stage 2.1 `session/list_cache.py` **or** Stage 3.1 `orchestration_core` — prefer **session first** if Chat stability is higher priority; prefer **workflow first** if research/Teams is the active product fire.

**Default recommendation:** Stage 1 maps both → Stage 2 session (Chat hot path) → Stage 3 workflow.

## 16. Approval Checklist

- [ ] User accepts P0 scope and non-goals
- [ ] User picks default order: session-first (recommended) / workflow-first / maps-only
- [ ] Multi-agent: yes/no (if yes, separate worktrees)
- [ ] Live workbench verification required: yes/no

---

## Appendix A — Session split ↔ flow map

| Flow map step | P0 module home |
|---------------|----------------|
| POST messages / Prefer async | `session/submit.py` |
| turn start, journal user_message | submit + journal_bridge |
| schedule background | `session/schedule.py` |
| run turn / agent create | `session/worker.py` |
| UI stream capture | `session/stream_capture.py` |
| persist assistant_message / turn_completed | `session/persist.py` |
| list/detail cache | `session/list_cache.py` + projection |
| live output checkpoint | `session/live_output.py` |

## Appendix B — Workflow split ↔ frontend language

| Frontend / product | Backend pack |
|--------------------|--------------|
| Source collection runs/search | `team_workflow/source_collection/runs.py` |
| Stage agents / writeback | `…/stages.py` |
| Storage open | `…/storage.py` |
| Candidates / extract | `…/candidates.py` |
| Experiment design/execution APIs | `team_workflow/experiment.py` |
| Research loop APIs | `team_workflow/research_loop.py` |
| ensure/get orchestration | `orchestration_core.py` |
