# Service Optimization Phase 4 — Session Control + Agent Lifecycle

Date: 2026-07-21
Status: **phase4_closed**
Parent: Phase 3 closed
Branch: `codex/svc-opt-p4-session-lifecycle`

## Goal

Move session **stop/interrupt control** and **agent-linked session lifecycle** (purge/archive/child/inbox/cli) out of `session_service.py` into claimable packs.

## Delivered

| Pack | ~LOC | Role |
|------|------|------|
| `session/control.py` | ~0.35k | `request_stop_session_turn`, interrupt snapshot, stopped/paused builders |
| `session/agent_sessions.py` | ~3.2k | purge/archive/delete/reset, child sessions, inbox wake, CLI lifecycle bridges |

Facade re-exports keep route imports and monkeypatches stable.

## Metrics

| Surface | Lines (approx) |
|---------|----------------|
| Facade before Phase 4 | ~16.8k |
| Facade after Phase 4 | ~13.4k |

## Verification

- structure pack re-export asserts
- agent purge/archive lifecycle tests
- session service/submit/worker/detail + web runtime routes
- Pre-existing deselected failures unchanged (detail toolCalls shape; event cache singleflight)

## Ops

- Version impact: none
- Launcher refresh: not needed
- Push: only on explicit request
