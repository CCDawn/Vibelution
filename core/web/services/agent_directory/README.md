# Agent directory modules (`core/web/services/agent_directory`)

Ownership map for Agent registry / directory service.
Prefer slice modules over growing `agent_directory_service.py` when possible.

`agent_directory_service.py` remains the **public import facade**.

## Ownership map (claim scopes)

| Task type | Prefer these files | Avoid |
|-----------|-------------------|--------|
| Persona / task profile pure normalizers | `profiles.py` | registry save/load |
| Tool/memory/delegation/supervision policy | `policies.py` | session submit |
| Archive / purge / reset lifecycle | `lifecycle.py` | team membership graph |
| List/get API hydration projections | facade (later `projections.py`) | team canvas |
| Create/update mutations | facade (later `mutations.py`) | lifecycle purge path |
| Registry repair / shrink guards | facade | workflow orchestration |

## Sole-owner rules

1. Pure profile normalizers stay free of registry locks and disk IO.
2. Policy evaluate/normalize stay free of create/update registry mutations.
3. Lifecycle archive/purge/reset keep serializer wrappers on the facade (`__wrapped__` identity).
4. Re-export public symbols from `agent_directory_service` for route stability.

## Extraction progress

| Pack | Status | Notes |
|------|--------|--------|
| Map README | done | this file |
| `profiles.py` | done | persona/task profile normalizers (Stage 4) |
| `policies.py` | done | Phase 11 — policy normalize/evaluate/resolve |
| `lifecycle.py` | done | Phase 11 — archive/purge/reset |
| projections / mutations / repair | deferred | next agent_directory cuts |

## Related

- Routes: `core/web/routes/agents.py`
- Structure plan: `docs/plans/2026-07-20-backend-structure-p0.md`
