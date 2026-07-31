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
| AI search runs / source-scope IO | `ai_search.py` | system team materialize; pure ranking |
| Research organization team sync | `research_organization.py` | generic CRUD |
| Canvas node/member normalize (Agent lookup) | `canvas_normalize.py` | pure edge normalize (`canvas_primitives`) |
| Team CRUD list/get/create/archive | `team_crud.py` | repair index internals; pure ranking |
| System team bootstrap control plane | `system_bootstrap.py` | ensure_* materialization bodies |
| System team ensure / AI search team materialize | `system_teams.py` | bootstrap control-plane state; generic CRUD |
| Team linked chat-room sync / repair | `chat_room_links.py` | team CRUD; canvas IO |
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
| node/member normalize pack | **done** | Agent-IO normalize/validate/default canvas late-binds facade |
| system bootstrap pack | **done** | control plane late-binds facade ensure_* bodies |
| system teams materialize pack | **done** | ensure_*/need_repair probes late-bind facade index helpers |
| chat-room link pack | **done** | sync/repair/historical link helpers late-bind facade index locks |
| AI search runs pack | **done** | list/start/scope/page-fallback late-binds facade ensure/constants |
| research organization pack | **done** | ensure/canvas/role sync late-binds facade index/contract helpers |
| team CRUD pack | **done** | list/create/update/archive/membership/message late-binds facade |

## Related

- Routes: `core/web/routes/teams.py`
- Structure plan: `docs/plans/2026-07-20-backend-structure-p0.md`
