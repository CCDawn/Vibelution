# Service Optimization Phase 2 — Knowledge Vertical Pack

Date: 2026-07-21
Status: **phase2_closed**
Parent: Phase 1 closed (`docs/plans/2026-07-21-service-optimization-phase1-sc-search-kernel.md`)
Owner: team_workflow backend structure
Branch: `codex/svc-opt-p2-knowledge`

## Goal

Move **knowledge / candidate-graph / steward / coordination / paper-note pipeline** public mega APIs out of `team_workflow_orchestration_service.py` into a claimable pack, keeping facade re-exports for routes and monkeypatches.

## Delivered (Gate 2.1)

New module: `core/web/services/team_workflow/knowledge.py` (~3.6k lines)

Public surfaces moved (32 functions), including:

- paper-note / mechanism / hypothesis pipeline
- source quality assess + status
- candidate graph build
- knowledge ingestion status / precheck / steward submit-review
- knowledge collection completion + ingestion (sync + background start)
- local research model task/output/invoke/validate
- official research graph sync/rollback + model evidence
- coordination status
- transfer request submit/decide
- research review decide + PRD validate
- `extract_candidate_source_pages`

Private helpers remain on the facade and are reached via late-bound `_service()`.

## Metrics

| Surface | Lines (approx) |
|---------|----------------|
| Facade before Phase 2 | ~16.9k |
| Facade after Phase 2 | ~13.4k |
| `knowledge.py` | ~3.6k |

## Verification

- `tests/test_team_workflow_structure_packs.py` (knowledge re-export asserts)
- focused orchestration + routes: 105 passed (knowledge-related -k filter)
- full `tests/test_team_workflow_routes.py`
- ruff F821/E9 on `knowledge.py`

## Ops

- Version impact: none
- Launcher refresh: not needed (structure-only)
- Push: only on explicit user request

## Deferred

1. Move private knowledge helpers into the pack
2. Late-bind removal
3. Session projection/SSE (Phase 3)

## Execution log

| When | Notes |
|------|-------|
| 2026-07-21 | Extracted knowledge public APIs; structure + focused tests green; merged path via worktree commit |
