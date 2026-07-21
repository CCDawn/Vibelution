# Service Optimization Phase 12 — Agent Directory Projections / Mutations

Date: 2026-07-21
Status: **phase12_closed**
Branch: `codex/svc-opt-p12-agent-dir-proj-mutations`

## Goal

Continue splitting `agent_directory_service` after Phase 11 policies/lifecycle.

## Delivered

| Pack | ~LOC | Role |
|------|------|------|
| `agent_directory/projections.py` | ~0.8k | list/get, API hydration cache, runtime context, agent-to-API builders |
| `agent_directory/mutations.py` | ~0.9k | create/update, LLM binding replace, avatar store/resolve + events |

## Metrics

| Surface | Lines (approx) |
|---------|----------------|
| Facade before | ~5.9k |
| Facade after | ~4.3k |

## Verification

- structure re-export asserts (profiles/policies/lifecycle/projections/mutations)
- agent_directory service + lifecycle reset/purge/archive + tool policy configuration
- version: none; Launcher: not needed
