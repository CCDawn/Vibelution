# Service Optimization Phase 3 — Session Projection + SSE Publish

Date: 2026-07-21
Status: **phase3_closed**
Parent: Phase 2 closed (`docs/plans/2026-07-21-service-optimization-phase2-knowledge.md`)
Branch: `codex/svc-opt-p3-session-projection`

## Goal

Move session **list/detail DTO projection** and **SSE publish/transport** out of `session_service.py` into claimable packs, without changing journal event types or SSE event names.

## Delivered

| Pack | ~LOC | Role |
|------|------|------|
| `session/publish.py` | ~0.8k | `stream_session_events`, stream initial helpers, `_publish_session_detail_snapshot`, `_publish_session_assistant_delta`, queue coalesce |
| `session/projection.py` | ~3.1k | `list_sessions`, `get_session_detail`, summary/detail/cache composition builders |

Facade re-exports keep route imports and monkeypatches stable. Late-bind via `_service()`.

## Metrics

| Surface | Lines (approx) |
|---------|----------------|
| Facade before Phase 3 | ~20.5k |
| Facade after Phase 3 | ~16.8k |
| publish + projection | ~3.9k |

## Verification

- `tests/test_session_structure_packs.py` (new)
- focused session detail/service/submit/worker/persist/stream + `test_web_runtime_routes`
- Pre-existing failure (also on main, unrelated to this move):
  `test_session_detail_window_can_omit_native_transcript_for_light_payloads` (toolCalls `callId` shape)

## Ops

- Version impact: none
- Launcher refresh: not needed for structure-only
- Push: only on explicit request

## Deferred

1. Stop/agent lifecycle residual still on facade
2. Late-bind removal
3. Import-path migration off facade
