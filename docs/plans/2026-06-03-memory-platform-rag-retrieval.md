# Memory Platform RAG Retrieval Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade the existing memory platform from explicit team-knowledge search into a governed RAG retrieval substrate that can optionally use vector retrieval and safely provide compact, cited context to Agents.

**Architecture:** Keep the current Team Knowledge governance model as the source of truth: formal knowledge still requires review, access is filtered by Team ACL and MemoryPolicy, and knowledge is not injected into prompts by default. Add a typed RAG retrieval contract above the existing `exact` / `semantic` / `hybrid` search service, then optionally add an embedding-backed retrieval provider behind that contract. Agent prompt/context injection must be explicit, budgeted, source-cited, and logged.

**Tech Stack:** Python/FastAPI backend, file-backed JSON/JSONL Team Knowledge storage, runtime scene logging, Agent ToolPolicy/MemoryPolicy governance, TypeScript React frontend, Vitest layout/API tests, pytest backend/tool tests.

---

## Current Baseline

The memory platform already has the retrieval foundation:

- `core/web/services/team_knowledge_service.py`
  - `search_knowledge_items(...)` supports `search_mode` values `exact`, `semantic`, and `hybrid`.
  - Current `semantic` is lightweight local scoring through `_semantic_match_score(...)`, not embedding similarity.
  - Searches already log `knowledge.search.executed`.
- `core/web/routes/knowledge.py`
  - `/api/knowledge/search` exposes `searchMode`.
- `tools/team_knowledge_tools.py`
  - `knowledge_query_tool(...)` exposes read-only Agent retrieval for formal Team knowledge.
  - Tool visibility is controlled by Agent ToolPolicy and MemoryPolicy.
- `tools/research_knowledge_tools.py`
  - `research_knowledge_query_tool(...)` provides a separate read-only research knowledge query path.
- `core/web/services/memory_service.py`
  - The usage contract says Team shared knowledge is explicitly retrieved by permission and P1 does not inject it into prompt by default.
- `web/src/api/types.ts`
  - `KnowledgeSearchPayload` and `KnowledgeSearchResult` already exist.
- `web/src/routes/MemoryRoute.tsx`
  - The Memory page already exposes Team Knowledge search controls and graph exploration.

The missing pieces for full RAG are:

- no stable RAG retrieval response contract with chunk-level source references,
- no embedding/vector index provider,
- no explicit Agent context assembly boundary,
- no retrieval health/index status surface,
- no tests proving ACL, token budgets, citations, and no-default-prompt-injection behavior together.

## Non-Negotiable Behavior Contract

1. RAG retrieval must never bypass Team ACL, Agent ToolPolicy, or MemoryPolicy.
2. Formal Team knowledge remains the canonical source; RAG must not create or mutate `KnowledgeItem`.
3. Retrieval is explicit by default. Agent prompts must not receive retrieved text unless a tool call or future explicitly configured context policy requests it.
4. Every returned context block must preserve source identifiers:
   - `teamId`
   - `knowledgeBaseId`
   - `knowledgeItemId`
   - source artifact ids when available
   - retrieval mode/provider
5. Logs must record metadata only:
   - query length
   - mode/provider
   - scanned base count
   - candidate/result count
   - selected context block count
   - failure type
   - no raw query text, no full retrieved content, no secrets.
6. Vector retrieval must be optional. The system must still work with the current local lexical/scoring path.

## Proposed Phases

### Phase 0: Contract Alignment

Goal: make RAG boundaries explicit without changing runtime behavior.

Deliverables:

- Add a documented `RagRetrievalRequest` / `RagRetrievalPayload` concept.
- Keep existing `/api/knowledge/search` unchanged.
- Add tests that define what "RAG retrieval" means before implementation.

### Phase 1: Retrieval Contract Service

Goal: add a backend service that wraps existing Team Knowledge search into RAG-shaped context blocks.

Deliverables:

- New service file:
  - `core/web/services/rag_retrieval_service.py`
- New tests:
  - `tests/test_rag_retrieval_service.py`
- Existing search remains available.
- RAG payload includes:
  - `schemaVersion`
  - `agentId`
  - `request`
  - `summary`
  - `contexts`
  - `citations`
  - `retrievalPolicy`
  - `updatedAt`

Recommended context shape:

```json
{
  "contextId": "ctx-...",
  "text": "compact answer-ready excerpt or summary",
  "title": "Knowledge item title",
  "score": 0.82,
  "rank": 1,
  "retrievalMode": "hybrid",
  "provider": "local",
  "source": {
    "teamId": "team-...",
    "teamName": "Research Team",
    "knowledgeBaseId": "kb-...",
    "knowledgeBaseName": "Team Memory",
    "knowledgeItemId": "ki-...",
    "sourceArtifactIds": ["src-..."]
  },
  "metadata": {
    "tags": ["governance"],
    "importanceLevel": "high",
    "confidence": 0.8,
    "stability": "stable"
  }
}
```

### Phase 2: API And Tool Entry

Goal: expose RAG retrieval to UI and Agent tools without automatic prompt injection.

Deliverables:

- Add route:
  - `GET /api/knowledge/rag/retrieve`
- Add Agent tool:
  - `knowledge_rag_retrieve_tool`
- Tool should be explicit-allow gated like `knowledge_query_tool`.
- Tool result returns compact JSON with `contexts` and `citations`.
- The old `knowledge_query_tool` can stay as a simpler search/read tool.

### Phase 3: Optional Vector Provider

Goal: introduce embedding-backed retrieval as a provider, not as a hard dependency.

Deliverables:

- New provider abstraction:
  - `core/web/services/rag_retrieval_providers.py`
- Providers:
  - `local`: current token/scoring search.
  - `vector`: optional embedding-backed provider.
- New index storage path:
  - `workspace/knowledge/vector_index/`
- Index metadata:
  - model/provider name
  - source item ids
  - source content hash
  - indexedAt
  - stale/missing status
- If embeddings are unavailable, vector mode returns a clear `providerUnavailable` or falls back only when explicitly requested.

Recommended provider behavior:

- `retrievalMode=exact`: local provider only.
- `retrievalMode=semantic`: local semantic by default; vector if `provider=vector`.
- `retrievalMode=hybrid`: combine local and vector scores when vector is enabled.
- `retrievalMode=auto`: use vector if healthy, otherwise local hybrid.

### Phase 4: Agent Context Assembly Boundary

Goal: safely convert retrieved contexts into prompt-ready blocks only when explicitly requested.

Deliverables:

- New helper:
  - `core/orchestration/rag_context.py`
- Optional integration point:
  - `core/orchestration/context_engine.py`
- No default injection.
- Supported future policies:
  - `disabled`
  - `tool_only`
  - `explicit_context_policy`
- Context assembly must enforce:
  - max contexts
  - max characters/tokens approximation
  - citation preservation
  - no pending proposal content unless explicitly allowed by a separate governance route
  - no full prompt logging

### Phase 5: Frontend Visibility

Goal: make retrieval status and output inspectable from the Memory platform.

Deliverables:

- Extend `web/src/api/types.ts` with RAG DTOs.
- Extend `web/src/routes/MemoryRoute.tsx` knowledge search area with:
  - retrieval mode/provider selector,
  - topK / budget controls,
  - context block preview,
  - citation list,
  - index health/last indexed signal.
- Add compact CSS only in:
  - `web/src/routes/MemoryRoute.module.css`
- Keep the page ops-heavy and dense; no large cards or marketing hero.

### Phase 6: Observability And Health

Goal: make future failures diagnosable from runtime logs and UI.

Deliverables:

- Runtime scene events:
  - `knowledge.rag.retrieve.succeeded`
  - `knowledge.rag.retrieve.failed`
  - `knowledge.rag.retrieve.blocked`
  - `knowledge.rag.index.rebuilt`
  - `knowledge.rag.index.stale_detected`
- Health endpoint:
  - `GET /api/knowledge/rag/health`
- Health payload:
  - provider status,
  - indexed item count,
  - stale item count,
  - unavailable reason,
  - last rebuild timestamp.

### Phase 7: Version, Memory, And Release

Goal: close the development round cleanly.

Deliverables:

- PATCH version bump if only RAG retrieval contract/tool/UI lands.
- MINOR version bump if vector index becomes a new user-visible capability.
- Update:
  - `CHANGELOG.md`
  - `.docs/project-memory/lanes/agent-runtime-core.json`
  - `.docs/project-memory/memory.json`
  - `.docs/project-memory/INDEX.md`
  - generated memory HTML views through the project memory sync tool.

---

## Task Breakdown

### Task 1: Write RAG Retrieval Contract Tests

**Files:**

- Create: `tests/test_rag_retrieval_service.py`
- Read: `tests/test_knowledge_routes.py`
- Read: `tests/test_team_knowledge_tools.py`

**Step 1: Add a fixture with one Team, one Agent, one readable knowledge base, and two formal items.**

Use existing Team Knowledge test patterns instead of inventing new storage setup.

**Step 2: Write a failing test for local RAG retrieval.**

Expected behavior:

- returns `schemaVersion`,
- returns `contexts`,
- every context has a source with `teamId`, `knowledgeBaseId`, `knowledgeItemId`,
- respects `topK`,
- returns `provider=local`.

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_rag_retrieval_service.py -q
```

Expected: fails because `rag_retrieval_service` does not exist.

**Step 3: Write a failing ACL test.**

Expected behavior:

- unreadable knowledge base returns no contexts,
- payload reports the scanned/readable counts,
- no raw content leaks from unauthorized bases.

**Step 4: Write a failing budget test.**

Expected behavior:

- context text is trimmed to the requested budget,
- citation/source ids remain intact after trimming.

### Task 2: Implement `rag_retrieval_service`

**Files:**

- Create: `core/web/services/rag_retrieval_service.py`
- Modify: `tests/test_rag_retrieval_service.py`

**Step 1: Implement DTO-normalizing helpers.**

Functions:

- `retrieve_rag_contexts(...) -> dict[str, Any]`
- `_context_from_search_result(...) -> dict[str, Any]`
- `_trim_context_text(...) -> str`
- `_citation_from_context(...) -> dict[str, Any]`

**Step 2: Delegate candidate discovery to `team_knowledge_service.search_knowledge_items(...)`.**

Initial provider:

- `provider="local"`
- `retrieval_mode` maps to existing `search_mode`.

**Step 3: Run tests.**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_rag_retrieval_service.py -q
```

Expected: all new service tests pass.

**Step 4: Commit.**

```powershell
git status --short --branch
git add tests/test_rag_retrieval_service.py core/web/services/rag_retrieval_service.py
git commit -m "feat: add governed rag retrieval service"
```

### Task 3: Add RAG API Route

**Files:**

- Modify: `core/web/routes/knowledge.py`
- Test: `tests/test_knowledge_routes.py`

**Step 1: Add failing route test.**

Test:

- `GET /api/knowledge/rag/retrieve?agentId=...&query=...&retrievalMode=hybrid&topK=3`
- returns contexts and citations.

**Step 2: Add invalid mode test.**

Expected:

- unsupported mode returns `422`.

**Step 3: Implement route.**

Route signature should accept:

- `agentId`
- `query`
- `teamId`
- `knowledgeBaseId`
- `tags`
- `retrievalMode`
- `provider`
- `topK`
- `maxContextChars`

**Step 4: Run route tests.**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_knowledge_routes.py -q
```

**Step 5: Commit.**

```powershell
git status --short --branch
git add core/web/routes/knowledge.py tests/test_knowledge_routes.py
git commit -m "feat: expose rag retrieval api"
```

### Task 4: Add Agent Tool

**Files:**

- Modify: `tools/team_knowledge_tools.py`
- Modify: `tools/Key_Tools.py`
- Modify: `core/web/services/tool_catalog.py`
- Test: `tests/test_team_knowledge_tools.py`
- Test: `tests/test_tool_registry_service.py`
- Test: `tests/test_tool_executor.py`

**Step 1: Add failing tool visibility test.**

Expected:

- `knowledge_rag_retrieve_tool` is hidden by default if explicit allow is missing.
- visible/callable only when ToolPolicy allows it.

**Step 2: Add failing tool execution test.**

Expected:

- tool returns `ok=true`, `contexts`, and `citations`,
- honors MemoryPolicy read boundaries.

**Step 3: Implement tool.**

Tool parameters:

- `query`
- `knowledge_base_id`
- `retrieval_mode`
- `provider`
- `top_k`
- `max_context_chars`

Tool output:

- compact JSON,
- no prompt injection,
- no mutation.

**Step 4: Register tool in catalog and Key_Tools.**

Classify as:

- category: memory
- permissionTier: explicit allow
- riskTags: knowledge_access, prompt_context_candidate

**Step 5: Run tests.**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_team_knowledge_tools.py tests/test_tool_registry_service.py tests/test_tool_executor.py -q
```

**Step 6: Commit.**

```powershell
git status --short --branch
git add tools/team_knowledge_tools.py tools/Key_Tools.py core/web/services/tool_catalog.py tests/test_team_knowledge_tools.py tests/test_tool_registry_service.py tests/test_tool_executor.py
git commit -m "feat: add rag retrieval agent tool"
```

### Task 5: Add Runtime Scene Logging Contract

**Files:**

- Modify: `core/web/services/rag_retrieval_service.py`
- Modify: `tests/test_rag_retrieval_service.py`

**Step 1: Add failing logging test.**

Expected event:

- `knowledge.rag.retrieve.succeeded`
- fields include `queryLength`, `provider`, `retrievalMode`, `contextCount`, `citationCount`.
- fields do not include raw query or context text.

**Step 2: Add failure logging test.**

Expected event:

- `knowledge.rag.retrieve.failed`
- fields include `errorType`.

**Step 3: Implement logging at retrieval boundary.**

Use existing `record_runtime_scene_event` style through service helpers.

**Step 4: Run tests.**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_rag_retrieval_service.py -q
```

**Step 5: Commit.**

```powershell
git status --short --branch
git add core/web/services/rag_retrieval_service.py tests/test_rag_retrieval_service.py
git commit -m "test: lock rag retrieval logging contract"
```

### Task 6: Add Frontend DTOs And API Consumption

**Files:**

- Modify: `web/src/api/types.ts`
- Modify: `web/src/routes/MemoryRoute.tsx`
- Modify: `web/src/routes/MemoryRoute.module.css`
- Test: `web/src/routes/MemoryRoute.layout.test.ts`

**Step 1: Add TypeScript DTOs.**

Types:

- `KnowledgeRagContext`
- `KnowledgeRagCitation`
- `KnowledgeRagRetrievalPayload`
- `KnowledgeRagHealthPayload`

**Step 2: Add failing layout test.**

Expected UI copy/structure:

- retrieval mode selector exists,
- provider indicator exists,
- context preview exists,
- citations are shown.

**Step 3: Wire query action.**

Use existing Memory page fetch patterns. Do not create a landing page.

**Step 4: Keep search and RAG retrieval distinct.**

The old search result list should remain available. RAG context preview should be labeled as context candidates, not final answer.

**Step 5: Run frontend tests.**

```powershell
npm --prefix web run test -- MemoryRoute.layout.test.ts
npm --prefix web run build
```

**Step 6: Visual check.**

Start or reuse the workbench, then open:

```text
http://127.0.0.1:8000/agents/memory/knowledge
```

or the current Memory knowledge route used by the app.

Verify:

- controls fit desktop and mobile,
- context blocks are dense and scannable,
- citations do not overlap,
- no card-in-card clutter.

**Step 7: Commit.**

```powershell
git status --short --branch
git add web/src/api/types.ts web/src/routes/MemoryRoute.tsx web/src/routes/MemoryRoute.module.css web/src/routes/MemoryRoute.layout.test.ts
git commit -m "feat: show rag retrieval contexts in memory platform"
```

### Task 7: Add RAG Health Endpoint

**Files:**

- Modify: `core/web/services/rag_retrieval_service.py`
- Modify: `core/web/routes/knowledge.py`
- Modify: `tests/test_knowledge_routes.py`
- Modify: `web/src/api/types.ts`
- Modify: `web/src/routes/MemoryRoute.tsx`

**Step 1: Add backend health test.**

Expected local provider payload:

- `provider=local`
- `status=ready`
- `vectorEnabled=false`
- `indexedItemCount=0`
- `staleItemCount=0`

**Step 2: Implement route.**

Route:

- `GET /api/knowledge/rag/health`

**Step 3: Add UI status strip.**

Show:

- active provider,
- local/vector availability,
- stale index warning if applicable.

**Step 4: Run tests.**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_knowledge_routes.py -q
npm --prefix web run test -- MemoryRoute.layout.test.ts
npm --prefix web run build
```

**Step 5: Commit.**

```powershell
git status --short --branch
git add core/web/services/rag_retrieval_service.py core/web/routes/knowledge.py tests/test_knowledge_routes.py web/src/api/types.ts web/src/routes/MemoryRoute.tsx
git commit -m "feat: expose rag retrieval health"
```

### Task 8: Optional Vector Provider Spike

**Files:**

- Create: `core/web/services/rag_retrieval_providers.py`
- Create: `tests/test_rag_retrieval_providers.py`
- Modify: `core/web/services/rag_retrieval_service.py`
- Optional storage: `workspace/knowledge/vector_index/`

**Step 1: Decide embedding provider.**

Recommended first implementation:

- local/offline deterministic test embedding for tests,
- production provider disabled unless config exists.

Do not hard-code external API keys or require a network call for tests.

**Step 2: Add provider interface.**

Functions/classes:

- `RagRetrievalProvider`
- `LocalRagRetrievalProvider`
- `VectorRagRetrievalProvider`
- `get_rag_provider(provider_name: str)`

**Step 3: Add stale index detection.**

Use item content hash and indexed metadata.

**Step 4: Add tests.**

Expected:

- vector unavailable gives explicit status,
- stale item is detected,
- hybrid merge de-duplicates by `knowledgeItemId`,
- ACL is still enforced before vector candidates are returned.

**Step 5: Run tests.**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_rag_retrieval_service.py tests/test_rag_retrieval_providers.py -q
```

**Step 6: Commit.**

```powershell
git status --short --branch
git add core/web/services/rag_retrieval_providers.py core/web/services/rag_retrieval_service.py tests/test_rag_retrieval_providers.py tests/test_rag_retrieval_service.py
git commit -m "feat: add optional vector rag provider"
```

### Task 9: Optional Agent Context Assembly

**Files:**

- Create: `core/orchestration/rag_context.py`
- Modify: `core/orchestration/context_engine.py`
- Test: `tests/test_context_engine.py`
- Create: `tests/test_rag_context.py`

**Step 1: Write context assembly tests.**

Expected:

- disabled policy injects nothing,
- tool-only policy injects nothing automatically,
- explicit policy injects compact context with citations,
- max context budget is enforced,
- no full retrieved payload is logged.

**Step 2: Implement formatter.**

Output block example:

```text
Retrieved Team Knowledge Context:
[1] Title - compact context text
Source: teamId=..., knowledgeBaseId=..., knowledgeItemId=...
```

**Step 3: Integrate only behind explicit policy.**

Do not change default Agent behavior.

**Step 4: Run tests.**

```powershell
.venv\Scripts\python.exe -m pytest tests/test_rag_context.py tests/test_context_engine.py -q
```

**Step 5: Commit.**

```powershell
git status --short --branch
git add core/orchestration/rag_context.py core/orchestration/context_engine.py tests/test_rag_context.py tests/test_context_engine.py
git commit -m "feat: add explicit rag context assembly"
```

### Task 10: Version, Changelog, Project Memory

**Files:**

- Modify: `CHANGELOG.md`
- Modify: `web/package.json`
- Modify: `web/package-lock.json`
- Modify: `.docs/project-memory/*`
- Modify: `PROJECT_MEMORY.html`

**Step 1: Decide version bump.**

- PATCH if only local RAG retrieval API/tool/UI ships.
- MINOR if vector provider/index ships.

**Step 2: Update changelog.**

Mention:

- retrieval contract,
- tool/API,
- no default prompt injection,
- ACL and logging guarantees.

**Step 3: Sync project memory.**

Use the project memory sync scripts:

```powershell
python C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\sync_project_memory.py C:\Users\17533\Desktop\Vibelution --lane "agent-runtime-core" --focus "记忆平台 RAG 检索能力" --update "记忆平台新增受治理的 RAG 检索契约，保留显式检索、不默认注入 prompt、ACL/ToolPolicy/MemoryPolicy 边界。"
python C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\render_overview.py C:\Users\17533\Desktop\Vibelution
```

**Step 4: Final validation.**

Recommended full focused validation:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_rag_retrieval_service.py tests/test_knowledge_routes.py tests/test_team_knowledge_tools.py tests/test_tool_registry_service.py tests/test_tool_executor.py -q
npm --prefix web run test -- MemoryRoute.layout.test.ts
npm --prefix web run build
git diff --check
```

**Step 5: Commit release closure.**

```powershell
git status --short --branch
git add CHANGELOG.md web/package.json web/package-lock.json .docs/project-memory PROJECT_MEMORY.html
git commit -m "docs: record rag retrieval memory platform update"
```

---

## Recommended Execution Order

1. Phase 1 local RAG retrieval service.
2. Phase 2 API route.
3. Phase 2 Agent tool.
4. Phase 6 logging contract.
5. Phase 5 frontend visibility.
6. Phase 7 PATCH release closure.
7. Only then decide whether Phase 3 vector provider is worth doing.
8. Only after vector/local retrieval is stable, decide whether Phase 4 explicit Agent context assembly should be enabled.

This order gives user-visible value quickly while preserving the current safety model.

## Acceptance Criteria

The first release is complete when:

- `/api/knowledge/rag/retrieve` returns context blocks with citations.
- `knowledge_rag_retrieve_tool` can retrieve only authorized formal knowledge.
- Unauthorized knowledge never appears in contexts.
- Retrieval logs metadata without raw content.
- Memory UI shows RAG context candidates and citations.
- Existing `knowledge_query_tool` and `/api/knowledge/search` behavior still works.
- Tests cover service, route, tool, policy, logging, and frontend layout.
- Project memory and changelog are updated.

The vector release is complete when:

- vector provider can be disabled without breaking local retrieval,
- index health reports ready/stale/unavailable,
- stale index detection is tested,
- hybrid local/vector merge is deterministic,
- no external API call is required in tests.

## Risks And Mitigations

- Risk: Vector retrieval returns unauthorized data.
  - Mitigation: ACL filtering must happen before returning candidates, and tests must seed unreadable items.
- Risk: Prompt injection scope creeps in accidentally.
  - Mitigation: keep context assembly out of default prompt path; tests assert no default injection.
- Risk: Embedding dependency makes tests flaky.
  - Mitigation: vector provider uses deterministic fake embeddings in tests and is disabled by default.
- Risk: Logs leak query/content.
  - Mitigation: log only counts, ids, lengths, provider, mode, and error type.
- Risk: UI makes RAG look like an answer generator.
  - Mitigation: label outputs as context candidates and citations, not final answers.
- Risk: Existing search API becomes overloaded.
  - Mitigation: keep `/api/knowledge/search` as search; add `/api/knowledge/rag/retrieve` for context assembly.

## Open Decisions Before Implementation

1. Should the first shipped version include vector retrieval, or only local governed RAG context retrieval?
   - Recommendation: ship local governed RAG first, vector second.
2. Should `knowledge_query_tool` gain `search_mode`, or should RAG remain a separate `knowledge_rag_retrieve_tool`?
   - Recommendation: separate tool, so old query behavior remains stable.
3. Should Agent context injection be allowed at all in the first release?
   - Recommendation: no. First release returns context candidates through tool/API/UI only.
4. Which embedding provider should be used if vector retrieval is later enabled?
   - Recommendation: defer provider choice until contract/API/tool are stable.

