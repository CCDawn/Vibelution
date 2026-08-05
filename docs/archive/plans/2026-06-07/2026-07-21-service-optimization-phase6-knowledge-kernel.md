# Service Optimization Phase 6 — Knowledge Private Kernel

Date: 2026-07-21
Status: **phase6_closed**
Branch: `codex/svc-opt-p6-knowledge-kernel`
Parent: Phase 5 closed (stage_reconcile + experiment_kernel)

## Goal

Move knowledge-domain **private helpers** still late-bound from `knowledge.py` into a claimable pack, continuing facade slim-down.

## Delivered

| Pack | ~LOC | Role |
|------|------|------|
| `team_workflow/knowledge_kernel.py` | ~4.0k | ingestion/steward/graph/coordination/paper-note/source-quality private helpers + background runners |

Facade re-exports; public APIs remain in `knowledge.py`.

## Metrics

| Surface | Lines (approx) |
|---------|----------------|
| Facade before Phase 6 | ~9.4k |
| Facade after Phase 6 | ~5.7k |
| knowledge_kernel | ~4.0k |

## Verification

- structure re-export asserts for knowledge_kernel
- knowledge/steward/graph/coordination focused orchestration + routes tests
- version impact: none; Launcher: not needed
