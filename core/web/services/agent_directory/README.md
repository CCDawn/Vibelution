# Agent directory modules (`core/web/services/agent_directory`)

Ownership map for Agent registry / directory service.
Prefer slice modules over growing `agent_directory_service.py` when possible.

`agent_directory_service.py` remains the **public import facade**.

## Ownership map (claim scopes)

| Task type | Prefer these files | Avoid |
|-----------|-------------------|--------|
| Persona / task profile pure normalizers | `profiles.py` | registry save/load |
| List/get API hydration projections | facade (later `projections.py`) | team canvas |
| Create/update/reset/archive mutations | facade | team_service membership |
| Registry repair / shrink guards | facade | workflow orchestration |
| Tool/memory/delegation policy normalize | facade (later `policies.py`) | session submit |

## Sole-owner rules

1. Pure profile normalizers stay free of registry locks and disk IO.
2. Mutations (`create/update/reset/purge`) stay on the facade until a dedicated mutations pack exists.
3. Re-export public symbols from `agent_directory_service` for route stability.

## Extraction progress (Stage 4)

| Pack | Status | Notes |
|------|--------|--------|
| Map README | done | this file |
| `profiles.py` | done | persona/task profile normalizers |
| projections / policies / mutations | deferred | optional P1 |

## Related

- Routes: `core/web/routes/agents.py`
- Structure plan: `docs/plans/2026-07-20-backend-structure-p0.md`
