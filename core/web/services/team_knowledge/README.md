# Team knowledge modules (`core/web/services/team_knowledge`)

Ownership map for Team-scoped knowledge base storage and governance.
Prefer slice modules over growing `team_knowledge_service.py` when possible.

`team_knowledge_service.py` remains the **public import facade**.

## Ownership map (claim scopes)

| Task type | Prefer these files | Avoid |
|-----------|-------------------|--------|
| Financial evidence profile / private finance library | `financial.py` (re-exported by facade) | Separate database/index writers; generated answers promoted as facts |
| Source types / enums / BM25 params | `constants.py` | IO; permission checks |
| Search tokenize / BM25 / filters | `search_ranking.py` | store paths; ACL |
| Paths / JSONL / owner context / id helpers | `store.py` | promotion domain; ACL policy |
| ACL / can_* / steward permission helpers | `permissions.py` | inbox promotion domain; store IO |
| Owner inbox / central promotion domain | `source_inbox.py` | KB CRUD/proposals; pure path helpers |
| Public structure curation (`workspace/knowledge/public`) | `public_catalog.py` | items.jsonl bodies; `KNOWLEDGE_OWNER_TYPES` |
| Knowledge base CRUD / proposals | facade (until pack) | pure ranking; path helpers |
| Reviewed proposals and immutable revisions | `governance.py` | body replacement; bypassing reviewers |
| Canonical reads and eligible search candidates | `retrieval.py` | another knowledge store; truncated pre-ranking candidate sets |
| Full-body semantic index and RRF over eligible candidates | `semantic.py` (public build/health via facade) | query-time downloads; a parallel knowledge store |
| Revision lineage, source validity, linked source snapshots | `lifecycle.py` | arbitrary paths; hard deletion |

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
| `source_inbox.py` | **done** | collect/list/review inbox + central promote/list late-bind facade |
| `public_catalog.py` | **done** | `workspace/knowledge/public` cards, hash freshness, mixed read, startup budget, archive/conflict, proposals; facade re-export only |
| KB CRUD / proposals / ratings packs | pending | next slices |
| `governance.py` / `retrieval.py` / `lifecycle.py` | **done** | immutable revision IDs with optimistic body hashes; source lifecycle generations; common eligibility before body/search/RAG/index reads |
| `semantic.py` | **done** | full-body Chinese BGE chunks, current hash/dimension checks, publish-time review recheck and BM25/cosine RRF; `knowledge_embeddings.py` owns offline model loading |

## Related

- Memory operation telemetry: [memory-operation-logging.md](../../../../docs/agents/memory-operation-logging.md); existing owner audit storage is unchanged.

- Facade: `core/web/services/team_knowledge_service.py`
- Routes: knowledge-related web routes
- Structure pattern: `core/web/services/team/README.md`

## Financial evidence profile

`financial_reports_v1` is an Agent-owned base in the existing owner store. The profile adds bounded PDF provenance, exact-excerpt validation, reviewed-version supersession and live expiry/withdrawal guards shared by native search and vector-index eligibility. `financial.py` is the sole profile owner; canonical persistence/audit/ACL remain on the facade and store.

- `stage_financial_evidence` only collects a source in the existing owner inbox; it does not approve or ingest
- Existing source review / proposal review create formal evidence only when the content hash matches the source excerpt
- Existing RAG and unified-memory projections preserve `financialEvidence` citation metadata
- Hard deletion stays on `memory_cleanup_service` preview/confirmation/execute; no profile-specific purge path
- Profile-specific API data is additive; ordinary knowledge-base contracts do not gain empty profile fields
