# User Markdown Space Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Vibelution-managed Markdown Space layer so user `.md` content is copied into one managed user directory, indexed, browsed, searched, and read by Agents as reference without becoming formal Team Knowledge automatically.

**Architecture:** Borrow SilverBullet's useful product model of Spaces, Pages, wikilinks, tasks, and indexed objects, but keep Vibelution's backend and governance as the source of truth. A new file-backed `user_content_markdown_service` owns managed storage and indexes, FastAPI routes expose import/browse/search, and `unified_memory_search_tool` reads user Markdown through `unified_knowledge_search_service` as an optional read-only source beside governed formal knowledge.

**Tech Stack:** Python 3, FastAPI, file-backed JSON indexes, existing Vibelution workspace path routing, React + TypeScript + React Query, existing MemoryRoute UI, existing Python pytest and web Vitest build flow. No SilverBullet runtime dependency and no new npm dependency in phase 1.

## Global Constraints

- User selected mode B: imported Markdown is copied into a Vibelution-managed user directory; the managed copy becomes canonical after import.
- Managed directory root: `workspace/user_content/users/<userId>/markdown_spaces/<spaceId>/`.
- Original source directories are read only during import; after import they are kept only as `sourceRef` provenance and hash evidence.
- User Markdown, Agent runtime memory, project governance memory, and formal Team Knowledge remain separate layers.
- Agent reads user Markdown through `unified_memory_search_tool` or the backend unified search boundary; no direct prompt injection by default.
- User Markdown does not write to formal Team Knowledge. Promotion to formal knowledge remains owned by `team_knowledge_service`, source inbox, refinement proposal, and steward review flows.
- Phase 1 includes import, managed storage, deterministic indexes, browse/search UI, and Agent read-only reference search.
- Phase 1 excludes original-path sync, deleting originals, multi-user collaboration semantics, full Markdown editing, live collaborative editing, and automatic formal knowledge ingestion.
- Follow Vibelution worktree rules: root `C:\Users\17533\Desktop\Vibelution` stays on `main`; implement in `C:\Users\17533\Desktop\Vibelution-worktrees\user-markdown-space-memory` on `codex/user-markdown-space-memory`.
- Before implementation, expand the active claim to include `core/web/services/tool_catalog.py` because the tool schema must advertise the new user Markdown knobs.
- SilverBullet references are used as design reference only: [GitHub](https://github.com/silverbulletmd/silverbullet), [official site](https://silverbullet.md/), [Architecture](https://silverbullet.md/Architecture).

---

## Alignment Notes

SilverBullet concepts to adapt:

- `Space`: a directory-like managed knowledge area.
- `Page`: one Markdown file inside a Space.
- Bidirectional `[[wikilink]]` graph.
- Task extraction from Markdown checkboxes.
- Object extraction from frontmatter and inline tags.
- Local-first index that can be rebuilt from canonical Markdown files.

Vibelution constraints that override SilverBullet:

- Server-side Vibelution services remain authoritative for storage, search boundaries, Agent permissions, and UI DTOs.
- Index files are rebuildable cache, not authority.
- The formal knowledge/RAG layer is not changed by importing user notes.
- Agent access is explicit read-only reference retrieval and carries source citations.

## Source Of Truth Table

| Fact | Canonical source | Writer | Readers / derived surfaces | Refresh or invalidation | Old source cleanup |
| --- | --- | --- | --- | --- | --- |
| Managed Markdown page bytes | `workspace/user_content/users/<userId>/markdown_spaces/<spaceId>/pages/**/*.md` | `user_content_markdown_service.import_markdown_space` | browse route, search service, unified search, MemoryRoute preview | Recompute indexes after import; page hash detects stale index | Original import path is never edited; only `sourceRef` retained |
| Space metadata | `manifest.json` beside `pages/` | `user_content_markdown_service` | list spaces route, MemoryRoute selector, search result citations | Rewrite manifest after successful import/index rebuild | Previous manifest replaced only through overwrite flow with backup |
| Page/search/link/task indexes | `index/page_index.json`, `index/link_index.json`, `index/task_index.json`, `index/object_index.json` | `user_content_markdown_service._build_indexes` | search route, graph preview, Agent result metadata | Rebuild from `pages/` after import or explicit rebuild | Index can be deleted and rebuilt |
| Agent-readable result contract | `core/web/services/unified_knowledge_search_service.py` payload schema | unified search service | `unified_memory_search_tool`, tests, future Agent context consumers | Unit tests protect result type, citations, and policy flags | Existing formal knowledge results remain unchanged |
| Memory Library UI state | React Query keys in `web/src/api/queryKeys.ts` | MemoryRoute queries/mutations | MemoryRoute user content panel | Invalidate user content keys after import | No frontend-only source of truth |

## File Structure

- Create `core/web/services/user_content_markdown_service.py`
  - Owns user content root resolution, import preview, managed copy import, deterministic IDs, Markdown metadata parsing, index rebuild, list/get/search functions, and safe errors.
- Create `core/web/routes/user_content.py`
  - Exposes `/api/user-content/markdown-spaces*` endpoints with Pydantic request bodies and route-level HTTP error mapping.
- Modify `core/web/router_registry.py`
  - Imports and registers `user_content_router` with the existing `/api` prefix.
- Modify `core/web/services/unified_knowledge_search_service.py`
  - Adds optional user Markdown result collection while preserving existing formal knowledge behavior by default.
- Modify `tools/team_knowledge_tools.py`
  - Adds optional `include_user_content` and `user_content_space_ids` arguments to `unified_memory_search_tool`.
- Modify `core/web/services/tool_catalog.py`
  - Documents the new tool arguments so Agent-facing tool discovery matches the runtime signature.
- Modify `web/src/api/types.ts`
  - Adds DTOs for user Markdown spaces, pages, search, preview, import, and unified search user content results.
- Modify `web/src/api/queryKeys.ts`
  - Adds stable user content query keys.
- Create `web/src/routes/memory/MemoryUserContentPanel.tsx`
  - UI panel for import preview/import, space list, page list, search results, and selected page preview.
- Create `web/src/routes/memory/MemoryUserContentPanel.styles.ts`
  - Local Tailwind style map so the new panel does not import parent `MemoryRoute.styles`.
- Modify `web/src/routes/MemoryRoute.tsx`
  - Wires the new panel into the existing Memory Library view with minimal route-owned state.
- Create `tests/test_user_content_markdown_service.py`
  - Service tests for preview/import/index/search/path guards.
- Create `tests/test_web_user_content_routes.py`
  - Route tests for preview/import/list/pages/search and error mapping.
- Create `tests/test_unified_knowledge_search_user_content.py`
  - Unified search tests proving default formal-only behavior and opt-in user content results.
- Modify `tests/test_team_knowledge_tools.py`
  - Tool tests for policy-scoped user Markdown inclusion.
- Modify `web/src/routes/MemoryRoute.layout.test.ts`
  - Static UI contract coverage for the panel, query keys, and no parent style import in the child panel.

## Task 1: Backend Managed Markdown Space Service

**Files:**
- Create: `core/web/services/user_content_markdown_service.py`
- Test: `tests/test_user_content_markdown_service.py`

**Interfaces:**
- Consumes: `core.chatroom.store.utc_now_iso`, `core.infrastructure.developer_sandbox.route_workspace_path`.
- Produces:
  - `class UserContentMarkdownError(ValueError)`
  - `preview_markdown_space_import(source_path: str, *, user_id: str = "default") -> dict[str, Any]`
  - `import_markdown_space(source_path: str, *, user_id: str = "default", space_name: str = "", overwrite: bool = False) -> dict[str, Any]`
  - `list_markdown_spaces(*, user_id: str = "default") -> dict[str, Any]`
  - `list_markdown_space_pages(space_id: str, *, user_id: str = "default", query: str = "", tag: str = "") -> dict[str, Any]`
  - `get_markdown_space_page(space_id: str, page_id: str, *, user_id: str = "default") -> dict[str, Any]`
  - `search_user_markdown_spaces(*, user_id: str = "default", query: str = "", space_id: str = "", limit: int = 10, max_excerpt_chars: int = 900) -> dict[str, Any]`

- [ ] **Step 1: Write service tests first**

Add these test cases to `tests/test_user_content_markdown_service.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.web.services import user_content_markdown_service as service


def _write_note(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture()
def routed_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    return tmp_path


def test_preview_import_counts_markdown_links_tasks_and_tags(routed_workspace, tmp_path):
    source = tmp_path / "source"
    _write_note(
        source,
        "Start.md",
        "---\ntags: [alpha, beta]\n---\n# Start\nSee [[Second Page]].\n- [ ] open task\n- [x] done task\n#inline",
    )
    _write_note(source, "Second Page.md", "# Second Page\nBack to [[Start]].")
    _write_note(source, "ignore.txt", "not markdown")

    payload = service.preview_markdown_space_import(str(source))

    assert payload["ok"] is True
    assert payload["summary"]["markdownFileCount"] == 2
    assert payload["summary"]["ignoredFileCount"] == 1
    assert payload["summary"]["wikilinkCount"] == 2
    assert payload["summary"]["taskCount"] == 2
    assert payload["summary"]["tagCount"] == 3
    assert payload["source"]["path"] == str(source.resolve())


def test_import_copies_into_managed_space_and_builds_indexes(routed_workspace, tmp_path):
    source = tmp_path / "source"
    _write_note(source, "Start.md", "# Start\nSee [[Second Page]].\n- [ ] open task\n#alpha")
    _write_note(source, "Second Page.md", "# Second Page\n")

    payload = service.import_markdown_space(str(source), space_name="My Notes")

    assert payload["ok"] is True
    assert payload["space"]["spaceName"] == "My Notes"
    pages_root = Path(payload["space"]["canonicalPagesRoot"])
    assert (pages_root / "Start.md").read_text(encoding="utf-8").startswith("# Start")
    index_root = Path(payload["space"]["indexRoot"])
    page_index = json.loads((index_root / "page_index.json").read_text(encoding="utf-8"))
    assert {item["title"] for item in page_index["pages"]} == {"Start", "Second Page"}
    link_index = json.loads((index_root / "link_index.json").read_text(encoding="utf-8"))
    assert link_index["links"][0]["targetTitle"] == "Second Page"


def test_import_rejects_source_inside_managed_root(routed_workspace):
    managed = service._user_content_root("default")
    nested_source = managed / "incoming"
    nested_source.mkdir(parents=True, exist_ok=True)
    _write_note(nested_source, "Note.md", "# Note")

    with pytest.raises(service.UserContentMarkdownError, match="source_inside_managed_root"):
        service.import_markdown_space(str(nested_source))


def test_search_returns_ranked_excerpts_and_citations(routed_workspace, tmp_path):
    source = tmp_path / "source"
    _write_note(source, "Plan.md", "# Plan\nAgent can use this project reference.\n#agent")
    imported = service.import_markdown_space(str(source), space_name="Reference Notes")

    payload = service.search_user_markdown_spaces(query="agent reference", space_id=imported["space"]["spaceId"], limit=5)

    assert payload["summary"]["resultCount"] == 1
    result = payload["results"][0]
    assert result["resultType"] == "user_markdown_page"
    assert result["sourceDomain"] == "user_content"
    assert result["spaceId"] == imported["space"]["spaceId"]
    assert "Agent can use" in result["excerpt"]
    assert result["citation"]["pageRelativePath"] == "Plan.md"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
& ".venv\Scripts\python.exe" -m pytest tests/test_user_content_markdown_service.py -q
```

Expected: fail during import because `core.web.services.user_content_markdown_service` does not exist.

- [ ] **Step 3: Implement the service**

Implement `core/web/services/user_content_markdown_service.py` with this contract:

```python
SCHEMA_VERSION = 1
MAX_IMPORT_FILES = 5000
MAX_FILE_BYTES = 2 * 1024 * 1024
MARKDOWN_SUFFIXES = {".md", ".markdown"}
SKIPPED_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__"}

class UserContentMarkdownError(ValueError):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code
```

Storage helpers must resolve to this exact layout:

```python
def _user_content_root(user_id: str = "default") -> Path:
    normalized_user_id = _safe_id(user_id or "default", default="default")
    return _workspace_path("users", normalized_user_id, "markdown_spaces")

def _workspace_path(*parts: str) -> Path:
    try:
        from core.infrastructure import developer_sandbox

        return Path(developer_sandbox.route_workspace_path(PROJECT_ROOT, "user_content", *parts, intent="state", seed=True))
    except Exception:
        return Path(PROJECT_ROOT) / "workspace" / "user_content" / Path(*parts)
```

Use these exact page/index fields:

```python
page = {
    "pageId": _page_id_for_relative_path(relative_path),
    "relativePath": relative_path,
    "title": title,
    "tags": tags,
    "wikilinks": wikilinks,
    "taskCounts": {"open": open_count, "done": done_count, "total": total_count},
    "contentHash": sha256,
    "byteSize": byte_size,
    "updatedAt": utc_now_iso(),
}
```

Search results must use this stable result shape:

```python
result = {
    "resultId": f"user-md-{space_id}-{page_id}",
    "resultType": "user_markdown_page",
    "sourceDomain": "user_content",
    "title": page["title"],
    "excerpt": excerpt,
    "score": score,
    "rank": rank,
    "userId": normalized_user_id,
    "spaceId": space_id,
    "spaceName": manifest["spaceName"],
    "pageId": page_id,
    "pageRelativePath": page["relativePath"],
    "searchBackend": "user_markdown_literal",
    "matchReason": match_reason,
    "metadata": {"tags": page["tags"], "taskCounts": page["taskCounts"], "updatedAt": page["updatedAt"]},
    "citation": {"sourceDomain": "user_content", "spaceId": space_id, "pageId": page_id, "pageRelativePath": page["relativePath"]},
}
```

The import implementation must:

- Resolve `source_path` with `Path(source_path).expanduser().resolve()`.
- Raise `UserContentMarkdownError("source_path_missing")` when it does not exist.
- Raise `UserContentMarkdownError("source_not_directory")` when it is not a directory.
- Raise `UserContentMarkdownError("source_inside_managed_root")` when the resolved source is inside `_workspace_path()`.
- Copy only `.md` and `.markdown` files below `pages/`.
- Skip files larger than `MAX_FILE_BYTES` and count them in `ignoredFiles`.
- Skip directories in `SKIPPED_DIRS`.
- Write `manifest.json`, `index/page_index.json`, `index/link_index.json`, `index/task_index.json`, `index/object_index.json`, and append one JSON line to `imports/import_log.jsonl`.
- Raise `UserContentMarkdownError("space_exists")` when the target exists and `overwrite=False`.
- For `overwrite=True`, move the existing space to `<spaceId>.backup.<timestamp>` before replacing it.

- [ ] **Step 4: Run service tests to verify pass**

Run:

```powershell
& ".venv\Scripts\python.exe" -m pytest tests/test_user_content_markdown_service.py -q
```

Expected: all tests in `tests/test_user_content_markdown_service.py` pass.

## Task 2: FastAPI Routes For User Markdown Content

**Files:**
- Create: `core/web/routes/user_content.py`
- Modify: `core/web/router_registry.py`
- Test: `tests/test_web_user_content_routes.py`

**Interfaces:**
- Consumes Task 1 service functions.
- Produces route paths:
  - `POST /api/user-content/markdown-spaces/import-preview`
  - `POST /api/user-content/markdown-spaces/import`
  - `GET /api/user-content/markdown-spaces`
  - `GET /api/user-content/markdown-spaces/{space_id}/pages`
  - `GET /api/user-content/markdown-spaces/{space_id}/pages/{page_id}`
  - `GET /api/user-content/markdown-spaces/search`

- [ ] **Step 1: Write route tests first**

Add `tests/test_web_user_content_routes.py`:

```python
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.services import user_content_markdown_service as service


def _write_note(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_user_content_import_and_search_routes(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path / "project")
    source = tmp_path / "source"
    _write_note(source, "Guide.md", "# Guide\nAgent reference content\n[[Other]]")
    _write_note(source, "Other.md", "# Other\n")
    client = TestClient(create_app())

    preview = client.post("/api/user-content/markdown-spaces/import-preview", json={"sourcePath": str(source)})
    assert preview.status_code == 200
    assert preview.json()["summary"]["markdownFileCount"] == 2

    imported = client.post(
        "/api/user-content/markdown-spaces/import",
        json={"sourcePath": str(source), "spaceName": "Docs"},
    )
    assert imported.status_code == 201
    space_id = imported.json()["space"]["spaceId"]

    listed = client.get("/api/user-content/markdown-spaces")
    assert listed.status_code == 200
    assert listed.json()["summary"]["spaceCount"] == 1

    pages = client.get(f"/api/user-content/markdown-spaces/{space_id}/pages")
    assert pages.status_code == 200
    page_id = pages.json()["pages"][0]["pageId"]

    page = client.get(f"/api/user-content/markdown-spaces/{space_id}/pages/{page_id}")
    assert page.status_code == 200
    assert page.json()["content"].startswith("# Guide") or page.json()["content"].startswith("# Other")

    search = client.get("/api/user-content/markdown-spaces/search", params={"query": "reference"})
    assert search.status_code == 200
    assert search.json()["results"][0]["resultType"] == "user_markdown_page"


def test_user_content_route_maps_service_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path / "project")
    client = TestClient(create_app())

    response = client.post("/api/user-content/markdown-spaces/import-preview", json={"sourcePath": str(tmp_path / "missing")})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "source_path_missing"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
& ".venv\Scripts\python.exe" -m pytest tests/test_web_user_content_routes.py -q
```

Expected: fail with missing route module or 404 for `/api/user-content/markdown-spaces/import-preview`.

- [ ] **Step 3: Implement route module and router registration**

Create `core/web/routes/user_content.py`:

```python
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from core.web.services import user_content_markdown_service


router = APIRouter(tags=["user-content"])


class MarkdownSpaceImportPreviewPayload(BaseModel):
    sourcePath: str = Field(..., min_length=1, max_length=2000)
    userId: str = Field("default", max_length=160)


class MarkdownSpaceImportPayload(MarkdownSpaceImportPreviewPayload):
    spaceName: str = Field("", max_length=180)
    overwrite: bool = False


def _handle_service_error(exc: user_content_markdown_service.UserContentMarkdownError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": exc.code, "message": str(exc)},
    )


@router.post("/user-content/markdown-spaces/import-preview")
def markdown_space_import_preview(payload: MarkdownSpaceImportPreviewPayload) -> dict[str, Any]:
    try:
        return user_content_markdown_service.preview_markdown_space_import(payload.sourcePath, user_id=payload.userId)
    except user_content_markdown_service.UserContentMarkdownError as exc:
        raise _handle_service_error(exc) from exc


@router.post("/user-content/markdown-spaces/import", status_code=status.HTTP_201_CREATED)
def markdown_space_import(payload: MarkdownSpaceImportPayload) -> dict[str, Any]:
    try:
        return user_content_markdown_service.import_markdown_space(
            payload.sourcePath,
            user_id=payload.userId,
            space_name=payload.spaceName,
            overwrite=payload.overwrite,
        )
    except user_content_markdown_service.UserContentMarkdownError as exc:
        raise _handle_service_error(exc) from exc
```

Add the remaining GET handlers in the same file with the route paths listed above. In `core/web/router_registry.py`, add:

```python
from .routes.user_content import router as user_content_router
```

and register it near memory/knowledge routes:

```python
app.include_router(user_content_router, prefix="/api")
```

- [ ] **Step 4: Run route tests**

Run:

```powershell
& ".venv\Scripts\python.exe" -m pytest tests/test_user_content_markdown_service.py tests/test_web_user_content_routes.py -q
```

Expected: both test files pass.

## Task 3: Unified Agent Search Integration

**Files:**
- Modify: `core/web/services/unified_knowledge_search_service.py`
- Modify: `tools/team_knowledge_tools.py`
- Modify: `core/web/services/tool_catalog.py`
- Test: `tests/test_unified_knowledge_search_user_content.py`
- Test: `tests/test_team_knowledge_tools.py`

**Interfaces:**
- Consumes Task 1 `search_user_markdown_spaces`.
- Extends `search_unified_memory` signature with:
  - `include_user_content: bool = False`
  - `allowed_user_content_space_ids: list[str] | set[str] | tuple[str, ...] | None = None`
  - `user_id: str = "default"`
- Extends `unified_memory_search_tool` signature with:
  - `include_user_content: bool = False`
  - `user_content_space_ids: str = ""`

- [ ] **Step 1: Write unified search tests first**

Create `tests/test_unified_knowledge_search_user_content.py`:

```python
from __future__ import annotations

from pathlib import Path

from core.web.services import unified_knowledge_search_service, user_content_markdown_service


def _write_note(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_unified_search_is_formal_only_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(user_content_markdown_service, "PROJECT_ROOT", tmp_path / "project")
    monkeypatch.setattr(
        unified_knowledge_search_service.team_knowledge_service,
        "search_knowledge_items",
        lambda **kwargs: {"summary": {"resultCount": 0, "scannedKnowledgeBaseCount": 0}, "results": []},
    )
    source = tmp_path / "source"
    _write_note(source, "Guide.md", "# Guide\nuser markdown reference")
    user_content_markdown_service.import_markdown_space(str(source), space_name="User Notes")

    payload = unified_knowledge_search_service.search_unified_memory(agent_id="agent-1", query="markdown reference")

    assert all(result["resultType"] != "user_markdown_page" for result in payload["results"])
    assert payload["retrievalPolicy"]["mutatesFormalKnowledge"] is False


def test_unified_search_can_include_user_markdown_results(tmp_path, monkeypatch):
    monkeypatch.setattr(user_content_markdown_service, "PROJECT_ROOT", tmp_path / "project")
    monkeypatch.setattr(
        unified_knowledge_search_service.team_knowledge_service,
        "search_knowledge_items",
        lambda **kwargs: {"summary": {"resultCount": 0, "scannedKnowledgeBaseCount": 0}, "results": []},
    )
    source = tmp_path / "source"
    _write_note(source, "Guide.md", "# Guide\nuser markdown reference")
    imported = user_content_markdown_service.import_markdown_space(str(source), space_name="User Notes")

    payload = unified_knowledge_search_service.search_unified_memory(
        agent_id="agent-1",
        query="markdown reference",
        include_user_content=True,
        allowed_user_content_space_ids=[imported["space"]["spaceId"]],
    )

    assert payload["summary"]["userContentResultCount"] == 1
    assert payload["results"][0]["resultType"] == "user_markdown_page"
    assert payload["citations"][0]["sourceDomain"] == "user_content"
    assert payload["retrievalPolicy"]["honorsUserContentPolicy"] is True
```

Add one tool-level test to `tests/test_team_knowledge_tools.py`:

```python
def test_unified_memory_search_tool_can_include_user_content(tmp_path, monkeypatch):
    from core.web.services import user_content_markdown_service
    from tools import team_knowledge_tools

    monkeypatch.setattr(user_content_markdown_service, "PROJECT_ROOT", tmp_path / "project")
    monkeypatch.setattr(team_knowledge_tools, "_current_runtime", lambda: {"agentId": "agent-1", "memoryPolicy": {}})
    source = tmp_path / "source"
    source.mkdir()
    (source / "Guide.md").write_text("# Guide\nagent-readable user note", encoding="utf-8")
    imported = user_content_markdown_service.import_markdown_space(str(source), space_name="User Notes")

    result = team_knowledge_tools.unified_memory_search_tool(
        query="agent-readable",
        include_user_content=True,
        user_content_space_ids=imported["space"]["spaceId"],
    )

    payload = json.loads(result)
    assert payload["ok"] is True
    assert payload["summary"]["userContentResultCount"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
& ".venv\Scripts\python.exe" -m pytest tests/test_unified_knowledge_search_user_content.py tests/test_team_knowledge_tools.py -q
```

Expected: fail because `search_unified_memory` and `unified_memory_search_tool` do not accept user content parameters.

- [ ] **Step 3: Extend unified search service**

In `core/web/services/unified_knowledge_search_service.py`:

- Import `user_content_markdown_service`.
- Add `include_user_content`, `allowed_user_content_space_ids`, and `user_id` parameters.
- Keep existing formal-only behavior unchanged when `include_user_content=False`.
- When `include_user_content=True`, call `user_content_markdown_service.search_user_markdown_spaces`.
- Merge result lists by score descending, then rank sequentially.
- Add user content citations to `citations`.
- Add summary fields:
  - `formalResultCount`
  - `userContentResultCount`
  - `resultCount`
- Extend `_read_only_policy` return value with:

```python
"honorsUserContentPolicy": True,
"mutatesUserContent": False,
```

- [ ] **Step 4: Extend Agent tool and catalog**

In `tools/team_knowledge_tools.py`, extend the signature:

```python
def unified_memory_search_tool(
    query: str = "",
    query_mode: str = "auto",
    knowledge_base_id: str = "",
    owner_type: str = "",
    owner_id: str = "",
    tags: str = "",
    limit: int = 8,
    max_context_chars: int = 1200,
    include_user_content: bool = False,
    user_content_space_ids: str = "",
) -> str:
```

Inside the tool:

```python
requested_user_content_space_ids = _split_tags(user_content_space_ids)
allowed_user_content_space_ids = _policy_ids(memory_policy, "readUserContentSpaceIds")
if requested_user_content_space_ids and allowed_user_content_space_ids:
    denied = [space_id for space_id in requested_user_content_space_ids if space_id not in allowed_user_content_space_ids]
    if denied:
        return _json_result(_blocked_result(agent_id, "user_content_space_not_in_memory_policy"))
```

Pass:

```python
include_user_content=bool(include_user_content),
allowed_user_content_space_ids=requested_user_content_space_ids or allowed_user_content_space_ids,
```

In `core/web/services/tool_catalog.py`, update the `unified_memory_search_tool` descriptor to include:

```python
{
    "name": "include_user_content",
    "type": "boolean",
    "required": False,
    "description": "Include imported user Markdown Space pages as read-only reference results.",
},
{
    "name": "user_content_space_ids",
    "type": "string",
    "required": False,
    "description": "Comma-separated imported user Markdown Space ids to search when include_user_content is true.",
},
```

- [ ] **Step 5: Run unified/tool tests**

Run:

```powershell
& ".venv\Scripts\python.exe" -m pytest tests/test_unified_knowledge_search_user_content.py tests/test_team_knowledge_tools.py -q
```

Expected: all selected tests pass.

## Task 4: Frontend Types, Query Keys, And User Content Panel

**Files:**
- Modify: `web/src/api/types.ts`
- Modify: `web/src/api/queryKeys.ts`
- Create: `web/src/routes/memory/MemoryUserContentPanel.tsx`
- Create: `web/src/routes/memory/MemoryUserContentPanel.styles.ts`
- Modify: `web/src/routes/MemoryRoute.tsx`
- Test: `web/src/routes/MemoryRoute.layout.test.ts`

**Interfaces:**
- Consumes Task 2 route DTOs.
- Produces:
  - `UserMarkdownSpaceListPayload`
  - `UserMarkdownSpaceImportPreviewPayload`
  - `UserMarkdownSpaceImportPayload`
  - `UserMarkdownSpacePageListPayload`
  - `UserMarkdownSpacePagePayload`
  - `UserMarkdownSpaceSearchPayload`
  - `queryKeys.userMarkdownSpaces()`
  - `queryKeys.userMarkdownSpacePages(spaceId, query, tag)`
  - `queryKeys.userMarkdownSpacePage(spaceId, pageId)`
  - `queryKeys.userMarkdownSpaceSearch(query, spaceId, limit)`

- [ ] **Step 1: Write static UI tests first**

Add assertions to `web/src/routes/MemoryRoute.layout.test.ts`:

```ts
it("wires user Markdown content through dedicated panel and query keys", () => {
  const routeSource = readFileSync(resolve(__dirname, "MemoryRoute.tsx"), "utf8");
  const panelSource = readFileSync(resolve(__dirname, "memory/MemoryUserContentPanel.tsx"), "utf8");
  const queryKeysSource = readFileSync(resolve(__dirname, "../api/queryKeys.ts"), "utf8");

  expect(routeSource).toContain("MemoryUserContentPanel");
  expect(panelSource).toContain("/api/user-content/markdown-spaces/import-preview");
  expect(panelSource).toContain("/api/user-content/markdown-spaces/import");
  expect(panelSource).toContain("queryKeys.userMarkdownSpaces()");
  expect(queryKeysSource).toContain("userMarkdownSpaces");
  expect(panelSource).not.toContain("MemoryRoute.styles");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
npm --prefix web run test -- MemoryRoute.layout.test.ts
```

Expected: fail because `MemoryUserContentPanel.tsx` and query keys do not exist.

- [ ] **Step 3: Add DTOs and query keys**

In `web/src/api/types.ts`, add:

```ts
export interface UserMarkdownSpaceSummary {
  spaceId: string;
  spaceName: string;
  userId: string;
  canonicalPagesRoot: string;
  indexRoot: string;
  sourceRef: Record<string, unknown>;
  counts: {
    markdownFileCount: number;
    pageCount: number;
    linkCount: number;
    taskCount: number;
    tagCount: number;
  };
  updatedAt: string;
}

export interface UserMarkdownPageSummary {
  pageId: string;
  relativePath: string;
  title: string;
  tags: string[];
  wikilinks: string[];
  taskCounts: { open: number; done: number; total: number };
  contentHash: string;
  byteSize: number;
  updatedAt: string;
}

export interface UserMarkdownSpaceListPayload {
  ok: boolean;
  summary: { spaceCount: number };
  spaces: UserMarkdownSpaceSummary[];
}

export interface UserMarkdownSpacePageListPayload {
  ok: boolean;
  space: UserMarkdownSpaceSummary;
  summary: { pageCount: number };
  pages: UserMarkdownPageSummary[];
}

export interface UserMarkdownSpacePagePayload {
  ok: boolean;
  space: UserMarkdownSpaceSummary;
  page: UserMarkdownPageSummary;
  content: string;
}

export interface UserMarkdownSearchResult {
  resultId: string;
  resultType: "user_markdown_page";
  sourceDomain: "user_content";
  title: string;
  excerpt: string;
  score: number;
  rank: number;
  userId: string;
  spaceId: string;
  spaceName: string;
  pageId: string;
  pageRelativePath: string;
  metadata: Record<string, unknown>;
}

export interface UserMarkdownSpaceSearchPayload {
  ok: boolean;
  summary: { resultCount: number };
  results: UserMarkdownSearchResult[];
}
```

In `web/src/api/queryKeys.ts`, add:

```ts
userMarkdownSpaces: () => ["user-content", "markdown-spaces"] as const,
userMarkdownSpacePages: (spaceId: string, query = "", tag = "") =>
  ["user-content", "markdown-spaces", spaceId, "pages", query, tag] as const,
userMarkdownSpacePage: (spaceId: string, pageId: string) =>
  ["user-content", "markdown-spaces", spaceId, "pages", pageId] as const,
userMarkdownSpaceSearch: (query = "", spaceId = "", limit = 10) =>
  ["user-content", "markdown-spaces", "search", query, spaceId, limit] as const,
```

- [ ] **Step 4: Add panel component**

Create `web/src/routes/memory/MemoryUserContentPanel.styles.ts` with local class keys for root, toolbar, form row, list, selected page, result list, badge, error, and empty state. Do not import `MemoryRoute.styles`.

Create `web/src/routes/memory/MemoryUserContentPanel.tsx` with these props:

```ts
export interface MemoryUserContentPanelProps {
  defaultUserId?: string;
}
```

The component must:

- Use `useQuery` for `queryKeys.userMarkdownSpaces()`.
- Use `fetchJson<UserMarkdownSpaceListPayload>("/api/user-content/markdown-spaces")`.
- Hold local state for `sourcePath`, `spaceName`, `selectedSpaceId`, `selectedPageId`, and `searchQuery`.
- Preview import through `POST /api/user-content/markdown-spaces/import-preview`.
- Import through `POST /api/user-content/markdown-spaces/import`.
- Invalidate `queryKeys.userMarkdownSpaces()` after import success.
- Fetch pages through `/api/user-content/markdown-spaces/${encodeURIComponent(selectedSpaceId)}/pages`.
- Fetch selected page through `/api/user-content/markdown-spaces/${encodeURIComponent(selectedSpaceId)}/pages/${encodeURIComponent(selectedPageId)}`.
- Search through `/api/user-content/markdown-spaces/search?query=...&spaceId=...&limit=10`.
- Show canonical path and sourceRef as bounded text; do not show entire imported file contents in lists.
- Use regular buttons for commands and avoid nested cards.

- [ ] **Step 5: Wire panel into MemoryRoute**

In `web/src/routes/MemoryRoute.tsx`, import:

```ts
import { MemoryUserContentPanel } from "./memory/MemoryUserContentPanel";
```

Render it inside the memory management/content area near existing source and item panels:

```tsx
<MemoryUserContentPanel defaultUserId="default" />
```

Keep route-owned state unchanged except the new panel mount.

- [ ] **Step 6: Run frontend validation**

Run:

```powershell
npm --prefix web run test -- MemoryRoute.layout.test.ts
npm --prefix web run build
```

Expected: layout test passes and build completes.

## Task 5: Cross-Layer Validation And Project Memory Handoff

**Files:**
- Modify only if implementation occurred: `.docs/project-memory` through the project memory sync script from root.
- No code file changes in this task unless validation reveals a concrete failure.

**Interfaces:**
- Consumes completed Tasks 1 through 4.
- Produces validation evidence and a project-memory update proposal or sync.

- [ ] **Step 1: Run Python focused validation**

Run:

```powershell
& ".venv\Scripts\python.exe" -m pytest tests/test_user_content_markdown_service.py tests/test_web_user_content_routes.py tests/test_unified_knowledge_search_user_content.py tests/test_team_knowledge_tools.py -q
```

Expected: all selected Python tests pass.

- [ ] **Step 2: Run frontend focused validation**

Run:

```powershell
npm --prefix web run test -- MemoryRoute.layout.test.ts
npm --prefix web run build
```

Expected: MemoryRoute layout test passes and web build completes.

- [ ] **Step 3: Run diff hygiene**

Run:

```powershell
git diff --check
git status --short --branch
```

Expected: `git diff --check` emits no whitespace errors. `git status` lists only current-task files.

- [ ] **Step 4: Make runtime refresh decision**

Report:

```text
Launcher refresh: recommended before user testing
Reason: backend routes, Agent tool schema, and frontend MemoryRoute changed.
```

Do not restart through Launcher unless the user asks for runtime verification in the same round and active-work guard allows it.

- [ ] **Step 5: Project memory update**

If implementation completes, run from root:

```powershell
& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\sync_project_memory.py" "C:\Users\17533\Desktop\Vibelution" --lane "agent-runtime-core" --focus "User Markdown Space memory integration" --update "Imported user Markdown Spaces now live under workspace/user_content, remain separate from formal Team Knowledge, and can be searched by Agents through unified_memory_search_tool when include_user_content is enabled."
```

Expected: project memory updates without editing generated HTML by hand.

## Self-Review

- Spec coverage: B-mode managed import, user/Agent content separation, Agent read-only reference access, SilverBullet Space/Page/link/task concepts, and no automatic formal knowledge promotion are covered by Tasks 1 through 4.
- Placeholder scan: plan text was scanned for banned placeholder markers and vague edge-case instructions; none remain.
- Type consistency: backend `resultType` is `user_markdown_page`; frontend `UserMarkdownSearchResult.resultType` matches; unified search and tool parameters use `include_user_content` and `user_content_space_ids`.
- Developer mode impact: parity preserved. The storage root uses the existing workspace path routing helper, so developer and formal runtime modes share the same managed-copy contract while sandbox path routing remains centralized.
- Logging decision: no new runtime-scene logging in phase 1 service routes because imports are direct user-triggered content management operations and route responses contain bounded status evidence. Tool calls continue to use existing `memory.tool.unified_search.*` events.
- Version impact: minor feature addition, no version files changed by task Agents.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-04-user-markdown-space-memory.md`. Two execution options:

**1. Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
