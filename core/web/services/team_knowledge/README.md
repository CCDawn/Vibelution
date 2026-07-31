# Team knowledge modules (`core/web/services/team_knowledge`)

Ownership map for Team-scoped knowledge base storage and governance.
Prefer slice modules over growing `team_knowledge_service.py` when possible.

`team_knowledge_service.py` remains the **public import facade**.

## Ownership map (claim scopes)

| Task type | Prefer these files | Avoid |
|-----------|-------------------|--------|
| Source types / enums / BM25 params | `constants.py` | IO; permission checks |
| Search tokenize / BM25 / filters | `search_ranking.py` | store paths; ACL |
| Paths / JSONL / owner context / id helpers | `store.py` | promotion domain; ACL policy |
| ACL / can_* / steward permission helpers | `permissions.py` | inbox promotion domain; store IO |
| Knowledge base CRUD / proposals | facade (until pack) | pure ranking; path helpers |
| Owner inbox / central promotion domain | facade (until pack) | pure path helpers (`store`) |

## Sole-owner rules

1. Pure search ranking stays free of disk and Agent registry writes.
2. Mutable `_LOCK` and `PROJECT_ROOT` remain on the facade for monkeypatch.
3. Re-export public symbols from `team_knowledge_service` for route stability.

## Extraction progress

| Pack | Status | Notes |
|------|--------|--------|
| Map README | done | this file |
| `constants.py` | **done** | source types, adapters, enums, BM25/token patterns |
| `search_ranking.py` | **done** | pure BM25/semantic filter helpers |
| `store.py` | **done** | roots/paths/JSONL/owner context/id helpers late-bind facade |
| `permissions.py` | **done** | can_*/ACL/steward/require gates late-bind facade |
| inbox / central domain packs | pending | next slices |

## Related

- Facade: `core/web/services/team_knowledge_service.py`
- Routes: knowledge-related web routes
- Structure pattern: `core/web/services/team/README.md`
