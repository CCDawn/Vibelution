# Memory Platform Vector RAG Next Phase Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade the current governed local RAG retrieval surface into an optional vector-backed RAG substrate with explicit indexing, stale detection, health visibility, and safe prompt-context assembly boundaries.

**Architecture:** Keep Team Knowledge as the canonical governed store: only reviewed formal knowledge can be indexed, all retrieval remains filtered by Team ACL, ToolPolicy, and MemoryPolicy, and retrieved text is never injected into prompts by default. Add a provider abstraction above the existing local retriever, then introduce a file-backed vector index provider that can be disabled or degraded without breaking local retrieval.

**Tech Stack:** Python/FastAPI backend, file-backed JSON/JSONL index metadata, optional embedding provider adapter, runtime scene logging, pytest, TypeScript React frontend, TanStack Query, Vitest layout tests, project memory sync.

---

## Current Baseline

Already completed:

- `core/web/services/rag_retrieval_service.py`
  - local governed RAG retrieval contract
  - contexts and citations
  - ACL/MemoryPolicy-preserving search boundary
  - no mutation and no default prompt injection
- `GET /api/knowledge/rag/retrieve`
- `GET /api/knowledge/rag/health`
  - currently reports `provider=local`, `status=ready`, `vectorEnabled=false`, `indexedItemCount=0`, `staleItemCount=0`
- `knowledge_rag_retrieve_tool`
  - ToolPolicy gated
  - runtime scene success/failure summary logs
- Memory platform UI
  - RAG context preview
  - RAG health strip
  - retrieval policy strip

Still missing for full RAG:

- vector provider abstraction
- embedding/index storage
- stale detection and rebuild workflow
- health endpoint backed by real index metadata
- retrieval quality/evaluation checks
- explicit context assembly helper for future prompt usage

## Non-Negotiable Behavior

1. Vector indexing must only index reviewed formal `KnowledgeItem` content.
2. Vector retrieval must never bypass Team ACL, ToolPolicy, or MemoryPolicy.
3. `local` provider must remain available even when vector provider is disabled or unhealthy.
4. Retrieved contexts must keep citations: `teamId`, `knowledgeBaseId`, `knowledgeItemId`, source artifact ids, provider, and retrieval mode.
5. No retrieved text is injected into prompts by default.
6. Logs must not contain raw query text, full retrieved content, secrets, or full prompt payloads.
7. Health and rebuild surfaces must report counts/statuses, not leak knowledge bodies.

## Recommended Rollout

### Task 1: Lock Vector Provider Contract With Failing Tests

**Files:**

- Modify: `tests/test_rag_retrieval_service.py`
- Create: `tests/test_rag_vector_index_service.py`
- Read: `core/web/services/rag_retrieval_service.py`
- Read: `core/web/services/team_knowledge_service.py`

**Steps:**

1. Add tests for provider status shape:
   - vector disabled by default
   - local ready remains true
   - indexed/stale counts start at zero
2. Add tests for indexable item selection:
   - approved formal knowledge is indexable
   - pending proposals are not indexable
   - unreadable knowledge bases are excluded for retrieval even if indexed
3. Run:
   - `.venv\Scripts\python.exe -m pytest tests\test_rag_retrieval_service.py tests\test_rag_vector_index_service.py -q`
4. Expected first result:
   - new vector index tests fail because service does not exist.

**Commit:** `test: define rag vector index contract`

### Task 2: Add File-Backed Vector Index Metadata Service

**Files:**

- Create: `core/web/services/rag_vector_index_service.py`
- Modify: `tests/test_rag_vector_index_service.py`

**Storage:**

- `workspace/knowledge/vector_index/index.json`
- `workspace/knowledge/vector_index/items/*.json`

**Minimum metadata per item:**

- `knowledgeItemId`
- `knowledgeBaseId`
- `teamId`
- `contentHash`
- `embeddingProvider`
- `embeddingModel`
- `indexedAt`
- `status`: `indexed | stale | missing | failed`
- `errorType`

**Steps:**

1. Implement index metadata load/save helpers with atomic writes.
2. Implement content hash from title/summary/content/source artifact ids.
3. Implement `list_indexable_knowledge_items()`.
4. Implement `get_vector_index_health()`.
5. Add tests for empty index, indexed item, stale item, and missing item.
6. Run:
   - `.venv\Scripts\python.exe -m pytest tests\test_rag_vector_index_service.py -q`
   - `.venv\Scripts\python.exe -m py_compile core\web\services\rag_vector_index_service.py`

**Commit:** `feat: add rag vector index metadata`

### Task 3: Add Embedding Provider Boundary

**Files:**

- Create: `core/web/services/rag_embedding_provider.py`
- Modify: `tests/test_rag_vector_index_service.py`
- Modify: `config.example.toml` only if a config key is required

**Policy:**

- Start with a deterministic local test embedder for tests.
- Production provider remains optional.
- Missing embedding provider should degrade health, not break local retrieval.

**Steps:**

1. Define provider result shape:
   - `provider`
   - `model`
   - `dimensions`
   - `vector`
2. Add deterministic test embedder.
3. Add provider unavailable error class.
4. Ensure no secret/config values are logged.
5. Run focused tests.

**Commit:** `feat: add rag embedding provider boundary`

### Task 4: Implement Rebuild And Stale Detection

**Files:**

- Modify: `core/web/services/rag_vector_index_service.py`
- Modify: `core/web/routes/knowledge.py`
- Modify: `tests/test_knowledge_routes.py`
- Modify: `tests/test_rag_vector_index_service.py`

**API:**

- `POST /api/knowledge/rag/index/rebuild`
- optional query/body:
  - `agentId`
  - `knowledgeBaseId`
  - `force`

**Behavior:**

- Rebuild only formal reviewed items.
- Mark changed hashes as stale before re-indexing.
- Return counts:
  - `indexedCount`
  - `staleCount`
  - `skippedCount`
  - `failedCount`

**Logging:**

- `knowledge.rag.index.rebuilt`
- `knowledge.rag.index.stale_detected`

**Tests:**

- rebuild indexes approved items
- rebuild skips pending proposals
- modified item becomes stale then indexed
- failed embedding records `failed` without crashing whole rebuild

**Commit:** `feat: rebuild rag vector index`

### Task 5: Add Vector Retrieval Provider

**Files:**

- Create: `core/web/services/rag_retrieval_providers.py`
- Modify: `core/web/services/rag_retrieval_service.py`
- Modify: `tests/test_rag_retrieval_service.py`

**Provider rules:**

- `provider=local`: existing behavior
- `provider=vector`: use vector index only; if unavailable, return 422/provider unavailable
- `provider=auto`: use vector when healthy, otherwise local
- `retrievalMode=hybrid`: combine vector score and local score when vector is available

**Tests:**

- vector provider returns cited contexts
- vector unavailable is explicit
- auto falls back to local
- hybrid dedupes by `knowledgeItemId`
- ACL still filters final contexts

**Commit:** `feat: add optional rag vector retrieval provider`

### Task 6: Wire Real Health Into API And UI

**Files:**

- Modify: `core/web/services/rag_retrieval_service.py`
- Modify: `core/web/routes/knowledge.py`
- Modify: `tests/test_knowledge_routes.py`
- Modify: `web/src/api/types.ts`
- Modify: `web/src/routes/MemoryRoute.tsx`
- Modify: `web/src/routes/MemoryRoute.module.css`
- Modify: `web/src/routes/MemoryRoute.layout.test.ts`

**UI behavior:**

- RAG health strip shows:
  - local provider ready
  - vector provider ready/degraded/unavailable
  - indexed/stale counts
  - last rebuild time
- Add rebuild action only if backend rebuild API is in place and permission model is explicit.

**Tests:**

- backend health route reports real vector metadata
- layout test locks provider/health/rebuild wiring
- build passes

**Commit:** `feat: surface rag vector health`

### Task 7: Add Explicit Context Assembly Boundary

**Files:**

- Create: `core/orchestration/rag_context.py`
- Modify: `tests/test_rag_context.py`
- Optional read: `core/orchestration/context_engine.py`

**Behavior:**

- Convert retrieved contexts into a bounded prompt-ready block only when explicitly called.
- Preserve citations.
- Enforce max contexts and max characters.
- Do not integrate into default prompt injection yet.

**Tests:**

- trims context budget
- keeps citations
- excludes empty text
- does not log full content

**Commit:** `feat: add explicit rag context assembly boundary`

### Task 8: Add Retrieval Quality Evaluation Harness

**Files:**

- Create: `tests/test_rag_retrieval_quality.py`
- Optional create: `core/evaluation/rag_retrieval_eval.py`

**Purpose:**

- Prevent vector rollout from silently getting worse than local retrieval.

**Minimum checks:**

- known query returns expected item in top 3
- private/unreadable item never appears
- citations match source item
- vector disabled path still works

**Commit:** `test: add rag retrieval quality checks`

### Task 9: Version, Changelog, Project Memory

**Files:**

- Modify: canonical version source if vector capability lands
- Modify: `CHANGELOG.md`
- Update project memory through:
  - `sync_project_memory.py`
  - `render_overview.py`

**Version decision:**

- PATCH if only health/index metadata improves existing RAG.
- MINOR if vector-backed retrieval becomes user-visible and usable.

**Commit:** `docs: record rag vector retrieval rollout`

## Validation Matrix

Run before final delivery:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_rag_retrieval_service.py tests\test_rag_vector_index_service.py tests\test_knowledge_routes.py -q
.venv\Scripts\python.exe -m py_compile core\web\services\rag_retrieval_service.py core\web\services\rag_vector_index_service.py core\web\routes\knowledge.py
npm --prefix web run test -- MemoryRoute.layout.test.ts
npm --prefix web run build
git diff --check -- core/web/services/rag_retrieval_service.py core/web/services/rag_vector_index_service.py core/web/routes/knowledge.py tests/test_rag_retrieval_service.py tests/test_rag_vector_index_service.py tests/test_knowledge_routes.py web/src/routes/MemoryRoute.tsx web/src/routes/MemoryRoute.module.css web/src/routes/MemoryRoute.layout.test.ts web/src/api/types.ts web/src/api/queryKeys.ts
```

If a dev server is available:

```powershell
Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:8000/api/knowledge/rag/health -TimeoutSec 10
```

## Risk Register

- **Embedding dependency instability:** keep vector optional and local provider always available.
- **Permission leakage:** filter final retrieval contexts through existing Team Knowledge ACL and MemoryPolicy even if index contains broader metadata.
- **Stale index confusion:** health must clearly distinguish indexed, stale, missing, and failed items.
- **Prompt pollution:** context assembly helper exists, but default context engine integration remains disabled.
- **Large index files:** start with metadata and simple vectors, then optimize only after usage evidence.

## Suggested Execution Order

1. Vector index metadata first.
2. Rebuild/stale lifecycle second.
3. Provider abstraction third.
4. Retrieval integration fourth.
5. UI health and rebuild controls fifth.
6. Explicit context assembly last.

This order keeps the system observable before it becomes more capable, which is the safer path for a memory substrate.
