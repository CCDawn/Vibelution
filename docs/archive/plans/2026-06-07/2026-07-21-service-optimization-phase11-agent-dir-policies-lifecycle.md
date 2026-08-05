# Service Optimization Phase 11 — Agent Directory Policies / Lifecycle

Date: 2026-07-21
Status: **phase11_closed**
Branch: `codex/svc-opt-p11-agent-dir-policies-lifecycle`

## Goal

Start splitting the `agent_directory_service` god facade into claimable packs after Stage 4 `profiles`.

## Delivered

| Pack | ~LOC | Role |
|------|------|------|
| `agent_directory/policies.py` | ~1.6k | tool/memory/delegation/supervision/visibility/compression policy normalize+evaluate |
| `agent_directory/lifecycle.py` | ~0.6k | archive/purge/reset + guards; serializers rewrapped on facade |

## Metrics

| Surface | Lines (approx) |
|---------|----------------|
| Facade before | ~7.9k |
| Facade after | ~5.9k |

## Verification

- structure re-export asserts
- agent_directory service + lifecycle reset/purge/archive + tool policy configuration
- version: none; Launcher: not needed
