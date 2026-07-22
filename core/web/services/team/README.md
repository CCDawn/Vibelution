# Team modules (`core/web/services/team`)

Ownership map for Team registry / organization canvas service.
Prefer slice modules over growing `team_service.py` when possible.

`team_service.py` remains the **public import facade**.

## Ownership map (claim scopes)

| Task type | Prefer these files | Avoid |
|-----------|-------------------|--------|
| Canvas edge / token pure helpers | `canvas_primitives.py` | Agent mutations |
| Team kind / template / chat-room purpose pure maps | `kind_helpers.py` | Agent mutations |
| AI search page link ranking pure | `ai_search_ranking.py` | HTTP fetch / disk scope files |
| Canvas node/member normalize (Agent lookup) | facade (later pack) | workflow SC runs |
| Team CRUD list/get/create/archive | facade | agent_directory profiles |
| System team bootstrap / AI search team | facade | session stream |
| Canvas save/load IO | facade | knowledge steward |

## Sole-owner rules

1. Pure canvas primitives stay free of Agent registry writes.
2. Membership conflict checks that need full team state stay on the facade.
3. Re-export public symbols from `team_service` for route stability.

## Extraction progress

| Pack | Status | Notes |
|------|--------|--------|
| Map README | done | this file |
| `canvas_primitives.py` | done | safe token/float, issue DTO, edge normalize |
| `kind_helpers.py` | done (ROI D3) | kind/template inference + chat room purpose defaults |
| `ai_search_ranking.py` | done (ROI D3) | page link keyword rank/filter |
| node/member normalize pack | deferred | still Agent-IO coupled |
| system bootstrap pack | deferred | optional P1 |
| chat-room link pack | deferred | still multi-service IO |

## Related

- Routes: `core/web/routes/teams.py`
- Structure plan: `docs/plans/2026-07-20-backend-structure-p0.md`
