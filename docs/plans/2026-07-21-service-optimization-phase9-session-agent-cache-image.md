# Service Optimization Phase 9 — Session Agent Runtime / Cache / Image

Date: 2026-07-21
Status: **phase9_closed**
Branch: `codex/svc-opt-p9-session-agent-cache-image`

## Goal

Move remaining session **agent runtime**, **cache/context estimation**, and **image attachment** helpers out of `session_service.py`.

## Delivered

| Pack | ~LOC | Role |
|------|------|------|
| `session/agent_runtime.py` | ~1.1k | acquire agent, prompt snapshot, binding recovery, LLM diagnostics |
| `session/cache_context.py` | ~0.4k | context segments + provider cache estimation |
| `session/image_attachments.py` | ~0.5k | image store/resolve + LLM attachment assembly |

## Metrics

| Surface | Lines (approx) |
|---------|----------------|
| Facade before | ~8.5k |
| Facade after | ~6.8k |

## Verification

- structure re-export asserts
- session service/detail/llm/image + web runtime routes
- version: none; Launcher: not needed
