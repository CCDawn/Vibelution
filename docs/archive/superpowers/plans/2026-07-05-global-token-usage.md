# Global Token Usage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Vibelution-owned global Token usage ledger, Codex-style usage summary API, and a top "工作台工具" menu route entry parallel to "启动器 / 日志 / Git / 文件".

**Architecture:** `core/llm` owns the canonical usage ledger because all Vibelution model calls converge through `LLMClient`; Web routes and React views are read-only projections. Usage is stored in a small SQLite ledger under the routed workspace path so formal mode and developer mode do not pollute each other. The frontend adds one `/usage` workbench route and one compact `Token` entry in `AppShellUtilityMenu`.

**Tech Stack:** Python 3, FastAPI, SQLite via stdlib `sqlite3`, existing `core/llm` usage normalization, React, TypeScript, TanStack Query, Tailwind/VUI style maps, Vitest, pytest.

## Status Metadata

- **Status:** active-plan
- **Owner:** codex-global-token-usage-plan
- **Claim:** claim-02d5d9cd7ce7
- **Branch:** `codex/global-token-usage-design`
- **Worktree:** `C:\Users\17533\Desktop\Vibelution-worktrees\global-token-usage-design`
- **Scope:** plan-only now; implementation must claim backend ledger/API scopes and frontend route/menu scopes before editing code.
- **Supersedes:** none
- **Implementation link:** not started
- **Validation:** plan self-review, placeholder scan, `git diff --check`
- **Close condition:** `/usage` route shows Vibelution global Token usage from the ledger; top utility menu shows a same-grid `Token` link; focused backend/frontend tests and `npm --prefix web run build` pass.

## Global Constraints

- "Global" means Vibelution global usage only; do not read or merge Codex App, Codex CLI, or `.codex` usage files.
- Codex is the accounting-shape reference: preserve `lastTokenUsage`, `sessionTokenUsage`, and `globalTokenUsage`.
- Provider-observed normalized usage is the source of truth when present; estimated, missing, and not-called states must be visibly distinct.
- Preserve `inputTokens`, `cachedInputTokens`, `cacheReadInputTokens`, `cacheCreationInputTokens`, `uncachedInputTokens`, `outputTokens`, `reasoningOutputTokens`, `totalTokens`, and `cacheHitRate`.
- Do not log prompt text, response text, tool output, provider secrets, raw provider payload values, or API keys in ledger rows or runtime-scene events.
- The top UI entry must live in `web/src/app/AppShellUtilityMenu.tsx` beside Launcher, Logs, Git, and Files; it opens an independent workbench route.
- Use `/usage` as the route and `Token` as the short entry label.
- First version is not a billing dashboard, cost estimator, provider rate-limit dashboard, or conversation token UI redesign.
- Source-of-truth rule: global usage totals are derived from the new ledger, not from `ui_runtime_state.json`, session message metadata, runtime state, or frontend cache.
- Developer-mode parity: ledger path must use `developer_sandbox.route_workspace_path(...)` so developer mode records into its sandbox workspace while formal mode records into the formal workspace.
- Hot-file serialization: before execution, claim exact scopes for `web/src/api/types.ts`, `web/src/api/queryKeys.ts`, `web/src/app/router.tsx`, `web/src/app/AppShellUtilityMenu.tsx`, `web/src/i18n/shellDictionary.ts`, and any touched backend hot files.
- Frontend visual style must stay compact and operational: no card wall, no hero, no nested cards, no wide explanatory text blocks.
- Runtime refresh after implementation is required before release/runtime verification and recommended before user testing; docs-only planning may skip refresh.

---

## Source Of Truth Table

| Fact | Canonical source | Writer | Readers / derived surfaces | Refresh or invalidation | Old source cleanup |
| --- | --- | --- | --- | --- | --- |
| Single LLM call usage | `workspace/usage/usage_ledger.sqlite3` row in `usage_events` | `core.llm.client.LLMClient` after invoke or stream completion | Usage API, `/usage`, diagnostics | Append one row per completed model call | Keep existing round/UI counters as local projections only |
| Last usage | Latest `usage_events.recorded_at` row for the requested scope | Ledger writer | `/api/usage/summary`, `/usage` | Query latest row | Do not derive global last usage from `ui_runtime_state.json` |
| Session total | Aggregation over `usage_events.session_id` | Ledger reader | Session-scoped summary query, future session links | Query by `sessionId` | Existing session `llmUsage` remains compatible UI metadata |
| Global total | Aggregation over all Vibelution `usage_events` rows | Ledger reader | `/usage` route | Query `today`, `last7Days`, `allTime` | No old global source exists |
| Usage source status | `usage_events.source` | Usage normalizer and ledger writer | Source badges, diagnostics, tests | Persisted per row | Estimated rows must never be counted as provider-observed rows |

## File Structure

- Create `core/llm/usage_ledger.py`: SQLite schema, path routing, event normalization, append function, rollup aggregation, summary query, diagnostics.
- Modify `core/llm/types.py`: add `reasoning_output_tokens` to `UsageStats`.
- Modify `core/llm/usage.py`: normalize reasoning token fields from common provider payload shapes.
- Modify `core/llm/client.py`: record one ledger row after successful non-streaming invoke and one ledger row after successful streaming completion.
- Create `core/web/routes/usage.py`: read-only FastAPI route for `/api/usage/summary`.
- Modify `core/web/router_registry.py`: include the usage router with `/api` prefix.
- Create `tests/test_llm_usage_ledger.py`: ledger schema, append, source classification, rollups, bad-row diagnostics, developer-mode path routing.
- Create `tests/test_llm_client_usage_ledger.py`: LLM client invoke/stream recording and no duplicate event proof.
- Create `tests/test_web_usage_routes.py`: API summary contracts and query filters.
- Modify `web/src/api/types.ts`: shared `UsageSummaryResponse` DTOs.
- Modify `web/src/api/queryKeys.ts`: add stable usage summary query key.
- Create `web/src/routes/UsageRoute.tsx`: compact global Token usage workbench route.
- Create `web/src/routes/UsageRoute.styles.ts`: typed Tailwind style map.
- Create `web/src/routes/UsageRoute.layout.test.ts`: route rendering, source badges, empty/error/loading states.
- Modify `web/src/app/router.tsx`: lazy-load and guard `/usage`.
- Modify `web/src/app/router.test.ts`: assert `/usage` route has workbench fallback and error boundary.
- Modify `web/src/app/AppShellUtilityMenu.tsx`: add same-grid `Token` NavLink.
- Modify `web/src/i18n/shellDictionary.ts`: add `navUsage`, `usageRouteTitle`, `usageRouteHint`, and update utility menu hint copy.
- Modify `web/src/app/AppShell.layout.test.ts`: assert Token is in the utility menu and primary nav stays clean.

## Implementation Preflight

- [ ] **Step 1: Start from root main and create or reuse a scoped task worktree**

Run from the root checkout:

```powershell
cd C:\Users\17533\Desktop\Vibelution
git status --short --branch
git worktree add C:\Users\17533\Desktop\Vibelution-worktrees\global-token-usage -b codex/global-token-usage main
```

Expected: root remains on `main`; task branch is `codex/global-token-usage`.

- [ ] **Step 2: Check and claim backend and frontend scopes before implementation**

Run:

```powershell
& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py" "C:\Users\17533\Desktop\Vibelution" check --lane "agent-runtime-core" --scope "core/llm/usage_ledger.py" --scope "core/llm/types.py" --scope "core/llm/usage.py" --scope "core/llm/client.py" --scope "core/web/routes/usage.py" --scope "core/web/router_registry.py" --scope "tests/test_llm_usage_ledger.py" --scope "tests/test_llm_client_usage_ledger.py" --scope "tests/test_web_usage_routes.py"
& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py" "C:\Users\17533\Desktop\Vibelution" check --lane "web-workbench-surface" --scope "web/src/api/types.ts" --scope "web/src/api/queryKeys.ts" --scope "web/src/routes/UsageRoute.tsx" --scope "web/src/routes/UsageRoute.styles.ts" --scope "web/src/routes/UsageRoute.layout.test.ts" --scope "web/src/app/router.tsx" --scope "web/src/app/router.test.ts" --scope "web/src/app/AppShellUtilityMenu.tsx" --scope "web/src/i18n/shellDictionary.ts" --scope "web/src/app/AppShell.layout.test.ts"
```

Expected: no overlapping active or ready claims. If there is an overlap, stop and report the claim ids before editing.

- [ ] **Step 3: Claim the implementation scopes**

Run only after both checks are clear:

```powershell
& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py" "C:\Users\17533\Desktop\Vibelution" claim --lane "agent-runtime-core" --scope "core/llm/usage_ledger.py" --scope "core/llm/types.py" --scope "core/llm/usage.py" --scope "core/llm/client.py" --scope "core/web/routes/usage.py" --scope "core/web/router_registry.py" --scope "tests/test_llm_usage_ledger.py" --scope "tests/test_llm_client_usage_ledger.py" --scope "tests/test_web_usage_routes.py" --agent "codex-global-token-usage" --task "Implement global Token usage ledger and API" --ttl-minutes 180 --note "Canonical usage ledger, Codex-style summary API, no prompt/provider secret storage."
& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py" "C:\Users\17533\Desktop\Vibelution" claim --lane "web-workbench-surface" --scope "web/src/api/types.ts" --scope "web/src/api/queryKeys.ts" --scope "web/src/routes/UsageRoute.tsx" --scope "web/src/routes/UsageRoute.styles.ts" --scope "web/src/routes/UsageRoute.layout.test.ts" --scope "web/src/app/router.tsx" --scope "web/src/app/router.test.ts" --scope "web/src/app/AppShellUtilityMenu.tsx" --scope "web/src/i18n/shellDictionary.ts" --scope "web/src/app/AppShell.layout.test.ts" --agent "codex-global-token-usage" --task "Implement Token usage route and utility menu entry" --ttl-minutes 180 --note "Adds /usage route and same-grid Token entry beside Launcher/Logs/Git/Files."
```

Expected: two active claim ids. Record both ids in the final report.

### Task 1: Usage Normalizer And Ledger

**Files:**
- Create: `core/llm/usage_ledger.py`
- Modify: `core/llm/types.py`
- Modify: `core/llm/usage.py`
- Test: `tests/test_llm_usage_ledger.py`

**Interfaces:**
- Consumes: `UsageStats` from `core.llm.types`, `usage_stats_from_payload()` from `core.llm.usage`, `developer_sandbox.route_workspace_path()`.
- Produces:
  - `UsageSource = Literal["provider_usage", "estimated", "missing", "not_called"]`
  - `UsageLedgerEvent` dataclass
  - `UsageRollup` dataclass
  - `UsageSummary` dataclass
  - `record_usage_event(event: UsageLedgerEvent, project_root: Path | None = None) -> UsageLedgerEvent`
  - `build_usage_summary(scope: str = "global", session_id: str = "", agent_id: str = "", provider: str = "", model: str = "", project_root: Path | None = None) -> dict[str, Any]`
  - `usage_ledger_path(project_root: Path | None = None) -> Path`

- [ ] **Step 1: Write failing tests for reasoning token normalization and rollups**

Add this test coverage to `tests/test_llm_usage_ledger.py`:

```python
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.llm.usage import usage_stats_from_payload
from core.llm.usage_ledger import (
    UsageLedgerEvent,
    build_usage_summary,
    record_usage_event,
    usage_ledger_path,
)


def iso_at(days: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def test_usage_stats_reads_reasoning_output_tokens():
    stats = usage_stats_from_payload(
        {
            "prompt_tokens": 100,
            "completion_tokens": 40,
            "total_tokens": 140,
            "completion_tokens_details": {"reasoning_tokens": 17},
            "prompt_tokens_details": {"cached_tokens": 25},
        }
    )

    assert stats.input_tokens == 100
    assert stats.output_tokens == 40
    assert stats.total_tokens == 140
    assert stats.cached_input_tokens == 25
    assert stats.reasoning_output_tokens == 17


def test_usage_ledger_records_provider_usage_and_rolls_up(tmp_path, monkeypatch):
    monkeypatch.setattr("core.llm.usage_ledger.PROJECT_ROOT", tmp_path)

    record_usage_event(
        UsageLedgerEvent(
            recorded_at=iso_at(),
            source="provider_usage",
            scope_kind="chat_session",
            session_id="session-a",
            turn_id="turn-1",
            agent_id="agent-a",
            provider="openai",
            model="gpt-5",
            profile_id="primary",
            input_tokens=100,
            cached_input_tokens=40,
            cache_read_input_tokens=40,
            cache_creation_input_tokens=10,
            uncached_input_tokens=60,
            output_tokens=30,
            reasoning_output_tokens=7,
            total_tokens=130,
            context_window=128000,
            latency_ms=250,
            provider_usage_keys=["prompt_tokens", "completion_tokens", "total_tokens"],
        )
    )
    record_usage_event(
        UsageLedgerEvent(
            recorded_at=iso_at(),
            source="estimated",
            scope_kind="chat_session",
            session_id="session-a",
            turn_id="turn-2",
            provider="openai",
            model="gpt-5",
            input_tokens=20,
            output_tokens=5,
            total_tokens=25,
        )
    )

    summary = build_usage_summary(scope="session", session_id="session-a")

    assert summary["lastTokenUsage"]["source"] == "estimated"
    assert summary["lastTokenUsage"]["totalTokens"] == 25
    assert summary["sessionTokenUsage"]["inputTokens"] == 120
    assert summary["sessionTokenUsage"]["cachedInputTokens"] == 40
    assert summary["sessionTokenUsage"]["uncachedInputTokens"] == 80
    assert summary["sessionTokenUsage"]["outputTokens"] == 35
    assert summary["sessionTokenUsage"]["reasoningOutputTokens"] == 7
    assert summary["sessionTokenUsage"]["totalTokens"] == 155
    assert summary["sessionTokenUsage"]["observedCallCount"] == 1
    assert summary["sessionTokenUsage"]["estimatedCallCount"] == 1
    assert summary["globalTokenUsage"]["allTime"]["totalTokens"] == 155
    assert summary["modelContextWindow"] == 128000


def test_usage_ledger_skips_invalid_source_rows_in_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setattr("core.llm.usage_ledger.PROJECT_ROOT", tmp_path)
    path = usage_ledger_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record_usage_event(
        UsageLedgerEvent(
            recorded_at=iso_at(),
            source="provider_usage",
            scope_kind="unknown",
            input_tokens=1,
            output_tokens=2,
            total_tokens=3,
        )
    )
    with sqlite3.connect(str(path)) as conn:
        conn.execute(
            "INSERT INTO usage_events(event_id, recorded_at, source, scope_kind, input_tokens, output_tokens, total_tokens, provider_usage_keys_json, usage_schema_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("bad-source", iso_at(), "alien", "unknown", 999, 999, 1998, json.dumps([]), 1),
        )
        conn.commit()

    summary = build_usage_summary()

    assert summary["globalTokenUsage"]["allTime"]["totalTokens"] == 3
    assert summary["diagnostics"]["skippedRecordCount"] == 1


def test_usage_ledger_uses_developer_sandbox_routing(tmp_path, monkeypatch):
    monkeypatch.setattr("core.llm.usage_ledger.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("core.infrastructure.developer_sandbox.is_developer_mode_enabled", lambda **_kwargs: True)
    monkeypatch.setattr("core.infrastructure.developer_sandbox.sandbox_root", lambda *_args, **_kwargs: tmp_path / ".runtime" / "developer-mode" / "sandboxes" / "dev-1")

    path = usage_ledger_path(tmp_path)

    assert path.as_posix().endswith("/.runtime/developer-mode/sandboxes/dev-1/workspace/usage/usage_ledger.sqlite3")
```

Run:

```powershell
& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" -m pytest tests/test_llm_usage_ledger.py -q
```

Expected: FAIL because `core.llm.usage_ledger` and `reasoning_output_tokens` do not exist yet.

- [ ] **Step 2: Add `reasoning_output_tokens` to `UsageStats`**

Modify `core/llm/types.py`:

```python
@dataclass
class UsageStats:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    reasoning_output_tokens: int = 0
    provider_raw_usage: Dict[str, Any] = field(default_factory=dict)
    estimated_cost: float = 0.0
    latency_ms: int = 0
```

- [ ] **Step 3: Normalize reasoning token fields**

Modify `core/llm/usage.py`:

```python
def reasoning_output_tokens_from_usage(usage: Dict[str, Any] | Any) -> int:
    usage_dict = usage_to_dict(usage)
    if not usage_dict:
        return 0
    completion_details = usage_dict.get("completion_tokens_details")
    output_details = usage_dict.get("output_token_details") or usage_dict.get("output_tokens_details")
    usage_metadata = usage_dict.get("usage_metadata")
    return max(
        read_usage_int(
            usage_dict,
            "reasoning_output_tokens",
            "reasoning_tokens",
            "output_reasoning_tokens",
        ),
        read_usage_int(
            completion_details,
            "reasoning_tokens",
            "reasoning_output_tokens",
            "output_reasoning_tokens",
        ),
        read_usage_int(
            output_details,
            "reasoning_tokens",
            "reasoning_output_tokens",
            "output_reasoning_tokens",
        ),
        read_usage_int(
            usage_metadata,
            "reasoning_tokens",
            "reasoning_output_tokens",
            "output_reasoning_tokens",
        ),
        _read_nested_usage_int(
            usage_dict,
            "reasoning_output_tokens",
            "reasoning_tokens",
            "output_reasoning_tokens",
        ),
    )
```

Update `usage_stats_from_payload()`:

```python
reasoning_output_tokens = reasoning_output_tokens_from_usage(usage_dict)
return UsageStats(
    input_tokens=input_tokens,
    output_tokens=output_tokens,
    total_tokens=total_tokens,
    cached_input_tokens=min(cached_tokens, input_tokens) if input_tokens else cached_tokens,
    cache_creation_input_tokens=min(cache_creation_tokens, input_tokens) if input_tokens else cache_creation_tokens,
    reasoning_output_tokens=min(reasoning_output_tokens, output_tokens) if output_tokens else reasoning_output_tokens,
    provider_raw_usage=usage_dict,
    estimated_cost=0.0,
    latency_ms=max(0, int(latency_ms or 0)),
)
```

- [ ] **Step 4: Implement the SQLite ledger**

Create `core/llm/usage_ledger.py` with these concrete responsibilities:

```python
# -*- coding: utf-8 -*-
"""Vibelution-owned LLM usage ledger and Codex-style summary projection."""

from __future__ import annotations

import json
import secrets
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from core.infrastructure import developer_sandbox


PROJECT_ROOT = Path(__file__).resolve().parents[2]
USAGE_SCHEMA_VERSION = 1
UsageSource = Literal["provider_usage", "estimated", "missing", "not_called"]
VALID_SOURCES = {"provider_usage", "estimated", "missing", "not_called"}


@dataclass(frozen=True)
class UsageLedgerEvent:
    recorded_at: str = ""
    source: UsageSource = "missing"
    scope_kind: str = "unknown"
    event_id: str = ""
    session_id: str = ""
    conversation_id: str = ""
    turn_id: str = ""
    agent_id: str = ""
    team_id: str = ""
    provider: str = ""
    model: str = ""
    profile_id: str = ""
    transport: str = ""
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    uncached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0
    context_window: int = 0
    latency_ms: int = 0
    runtime_scene_id: str = ""
    provider_usage_keys: list[str] = field(default_factory=list)


def usage_ledger_path(project_root: Path | None = None) -> Path:
    return developer_sandbox.route_workspace_path(
        (project_root or PROJECT_ROOT),
        "usage",
        "usage",
        "usage_ledger.sqlite3",
        intent="state",
        seed=True,
    )
```

Implement helper behavior exactly:

- `record_usage_event()` clamps all numeric fields to non-negative ints.
- `record_usage_event()` sets `event_id` to `usage-{YYYYMMDDTHHMMSSZ}-{secrets.token_hex(6)}` if missing.
- `record_usage_event()` sets `recorded_at` to current UTC ISO timestamp if missing.
- `record_usage_event()` stores provider usage keys as JSON list of key names only.
- `record_usage_event()` uses `INSERT OR IGNORE` on `event_id`.
- `_connect()` sets `PRAGMA journal_mode=WAL`, `PRAGMA busy_timeout=5000`, and creates schema before insert/read.
- `_rollup_rows()` counts only valid source rows; invalid rows increment `skippedRecordCount`.
- `cacheHitRate` is `cachedInputTokens / inputTokens`, rounded to 4 decimals.
- `totalTokens` is `inputTokens + outputTokens` when the event total is missing.
- `lastTokenUsage` is the newest valid event in requested scope.
- Empty summary returns zero rollups and `lastTokenUsage.source == "not_called"`.

Schema:

```sql
CREATE TABLE IF NOT EXISTS usage_events (
  event_id TEXT PRIMARY KEY,
  recorded_at TEXT NOT NULL,
  source TEXT NOT NULL,
  scope_kind TEXT NOT NULL,
  session_id TEXT NOT NULL DEFAULT '',
  conversation_id TEXT NOT NULL DEFAULT '',
  turn_id TEXT NOT NULL DEFAULT '',
  agent_id TEXT NOT NULL DEFAULT '',
  team_id TEXT NOT NULL DEFAULT '',
  provider TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT '',
  profile_id TEXT NOT NULL DEFAULT '',
  transport TEXT NOT NULL DEFAULT '',
  input_tokens INTEGER NOT NULL DEFAULT 0,
  cached_input_tokens INTEGER NOT NULL DEFAULT 0,
  cache_read_input_tokens INTEGER NOT NULL DEFAULT 0,
  cache_creation_input_tokens INTEGER NOT NULL DEFAULT 0,
  uncached_input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  reasoning_output_tokens INTEGER NOT NULL DEFAULT 0,
  total_tokens INTEGER NOT NULL DEFAULT 0,
  context_window INTEGER NOT NULL DEFAULT 0,
  latency_ms INTEGER NOT NULL DEFAULT 0,
  runtime_scene_id TEXT NOT NULL DEFAULT '',
  provider_usage_keys_json TEXT NOT NULL DEFAULT '[]',
  usage_schema_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_usage_events_recorded_at ON usage_events(recorded_at);
CREATE INDEX IF NOT EXISTS idx_usage_events_session_id ON usage_events(session_id);
CREATE INDEX IF NOT EXISTS idx_usage_events_agent_id ON usage_events(agent_id);
CREATE INDEX IF NOT EXISTS idx_usage_events_provider_model ON usage_events(provider, model);
```

- [ ] **Step 5: Run ledger tests**

Run:

```powershell
& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" -m pytest tests/test_llm_usage_ledger.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

Run:

```powershell
git status --short --branch
git add core/llm/types.py core/llm/usage.py core/llm/usage_ledger.py tests/test_llm_usage_ledger.py
git commit -m "feat: add llm usage ledger"
```

Expected: one commit containing only Task 1 files.

### Task 2: Record Usage From The Unified LLM Client

**Files:**
- Modify: `core/llm/client.py`
- Test: `tests/test_llm_client_usage_ledger.py`

**Interfaces:**
- Consumes: `UsageStats`, `record_usage_event()`, `UsageLedgerEvent`.
- Produces: one ledger event per successful `LLMClient.invoke()` call and one ledger event per successful `LLMClient.stream_events()` completion.

- [ ] **Step 1: Write failing tests for invoke and stream recording**

Create `tests/test_llm_client_usage_ledger.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.llm.types import UsageStats
from core.llm.usage_ledger import build_usage_summary


def test_llm_client_invoke_records_one_provider_usage_event(tmp_path, monkeypatch):
    from core.llm import client as llm_client_module

    monkeypatch.setattr("core.llm.usage_ledger.PROJECT_ROOT", tmp_path)
    recorded_payload = {
        "choices": [{"message": {"role": "assistant", "content": "hello", "tool_calls": []}}],
        "usage": {
            "prompt_tokens": 90,
            "completion_tokens": 15,
            "total_tokens": 105,
            "prompt_tokens_details": {"cached_tokens": 45},
            "completion_tokens_details": {"reasoning_tokens": 6},
        },
    }

    client = _fake_client(monkeypatch, llm_client_module, recorded_payload)
    client.invoke(
        [{"role": "user", "content": "hi"}],
        metadata={"sessionId": "session-1", "turnId": "turn-1", "agentId": "agent-1", "mode": "chat"},
    )

    summary = build_usage_summary(scope="session", session_id="session-1", project_root=tmp_path)
    assert summary["lastTokenUsage"]["source"] == "provider_usage"
    assert summary["lastTokenUsage"]["cachedInputTokens"] == 45
    assert summary["lastTokenUsage"]["reasoningOutputTokens"] == 6
    assert summary["sessionTokenUsage"]["observedCallCount"] == 1
    assert summary["sessionTokenUsage"]["totalTokens"] == 105


def test_llm_client_stream_records_one_done_event(tmp_path, monkeypatch):
    from core.llm import client as llm_client_module

    monkeypatch.setattr("core.llm.usage_ledger.PROJECT_ROOT", tmp_path)
    client = _fake_client(monkeypatch, llm_client_module, None)
    chunks = [
        SimpleNamespace(type="text_delta", text="hel", tool_calls=[], usage=None, provider_payload={}),
        SimpleNamespace(type="text_delta", text="lo", tool_calls=[], usage=None, provider_payload={}),
        SimpleNamespace(
            type="done",
            text="",
            tool_calls=[],
            usage=UsageStats(input_tokens=30, output_tokens=9, total_tokens=39, cached_input_tokens=12),
            provider_payload={},
        ),
    ]
    monkeypatch.setattr(client, "_stream_events_from_backend", lambda *_args, **_kwargs: iter(chunks))

    list(client.stream_events([{"role": "user", "content": "hi"}], metadata={"sessionId": "session-2", "turnId": "turn-2"}))

    summary = build_usage_summary(scope="session", session_id="session-2", project_root=tmp_path)
    assert summary["sessionTokenUsage"]["observedCallCount"] == 1
    assert summary["sessionTokenUsage"]["totalTokens"] == 39


def test_llm_client_records_estimated_usage_when_provider_usage_missing(tmp_path, monkeypatch):
    from core.llm import client as llm_client_module

    monkeypatch.setattr("core.llm.usage_ledger.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(llm_client_module, "_estimate_messages_for_usage", lambda _messages: 24)
    monkeypatch.setattr(llm_client_module, "_estimate_text_for_usage", lambda _text: 8)
    response = {"choices": [{"message": {"role": "assistant", "content": "estimated", "tool_calls": []}}]}
    client = _fake_client(monkeypatch, llm_client_module, response)

    client.invoke([{"role": "user", "content": "missing usage"}], metadata={"sessionId": "session-3"})

    summary = build_usage_summary(scope="session", session_id="session-3", project_root=tmp_path)
    assert summary["lastTokenUsage"]["source"] == "estimated"
    assert summary["lastTokenUsage"]["inputTokens"] == 24
    assert summary["lastTokenUsage"]["outputTokens"] == 8
    assert summary["sessionTokenUsage"]["estimatedCallCount"] == 1


def _fake_client(monkeypatch, llm_client_module, response):
    client = object.__new__(llm_client_module.LLMClient)
    client.role = "primary"
    client.profile_id = "primary"
    client.profile = SimpleNamespace(model="gpt-5", prompt_cache=SimpleNamespace(mode="automatic"))
    client.provider = SimpleNamespace(kind="openai", base_url="")
    client.adapter = SimpleNamespace()
    client.bound_tools = []
    client.capabilities = SimpleNamespace(__dict__={})
    client.protocol_route = SimpleNamespace(log_summary=lambda: {"transport": "chat_completions"})
    client._resolved_spec = SimpleNamespace(context_window=128000)
    client._last_payload_protocol_summary = {"transport": "chat_completions"}
    monkeypatch.setattr(client, "_build_payload", lambda messages, tools=None, stream=False: {"messages": messages, "stream": stream})
    monkeypatch.setattr(client, "_invoke_backend_with_retry", lambda *_args, **_kwargs: response)
    return client
```

Run:

```powershell
& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" -m pytest tests/test_llm_client_usage_ledger.py -q
```

Expected: FAIL because the client does not record ledger rows yet.

- [ ] **Step 2: Add safe estimation helpers and event builder in `core/llm/client.py`**

Add helper functions near existing usage helpers:

```python
def _estimate_messages_for_usage(messages: List[Any]) -> int:
    try:
        from tools.token_manager import estimate_messages_tokens

        return max(0, int(estimate_messages_tokens(messages) or 0))
    except Exception:
        return 0


def _estimate_text_for_usage(text: Any) -> int:
    content = extract_text_content(text)
    if not content:
        return 0
    try:
        from tools.token_manager import estimate_tokens_precise

        return max(0, int(estimate_tokens_precise(content) or 0))
    except Exception:
        return max(1, len(content) // 4)
```

Add a private recorder:

```python
def _record_usage_ledger_event(
    *,
    usage: UsageStats,
    metadata: Optional[Dict[str, Any]],
    provider: str,
    model: str,
    profile_id: str,
    transport: str,
    role: str,
    context_window: int = 0,
    estimated_input_tokens: int = 0,
    estimated_output_tokens: int = 0,
) -> None:
    from core.llm.usage_ledger import UsageLedgerEvent, record_usage_event

    meta = metadata if isinstance(metadata, dict) else {}
    provider_usage = getattr(usage, "provider_raw_usage", {}) if usage is not None else {}
    input_tokens = max(0, int(getattr(usage, "input_tokens", 0) or 0))
    output_tokens = max(0, int(getattr(usage, "output_tokens", 0) or 0))
    total_tokens = max(0, int(getattr(usage, "total_tokens", 0) or input_tokens + output_tokens))
    if provider_usage and (input_tokens or output_tokens or total_tokens):
        source = "provider_usage"
    elif estimated_input_tokens or estimated_output_tokens:
        source = "estimated"
        input_tokens = max(input_tokens, estimated_input_tokens)
        output_tokens = max(output_tokens, estimated_output_tokens)
        total_tokens = input_tokens + output_tokens
    else:
        source = "missing"
    cached_input_tokens = min(max(0, int(getattr(usage, "cached_input_tokens", 0) or 0)), input_tokens) if input_tokens else 0
    cache_creation_tokens = min(max(0, int(getattr(usage, "cache_creation_input_tokens", 0) or 0)), input_tokens) if input_tokens else 0
    record_usage_event(
        UsageLedgerEvent(
            source=source,
            scope_kind=_usage_scope_kind(meta),
            session_id=str(meta.get("sessionId") or meta.get("session_id") or "").strip(),
            conversation_id=str(meta.get("conversationId") or meta.get("conversation_id") or "").strip(),
            turn_id=str(meta.get("turnId") or meta.get("turn_id") or "").strip(),
            agent_id=str(meta.get("agentId") or meta.get("agent_id") or "").strip(),
            team_id=str(meta.get("teamId") or meta.get("team_id") or "").strip(),
            provider=provider,
            model=model,
            profile_id=profile_id,
            transport=transport,
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            cache_read_input_tokens=cached_input_tokens,
            cache_creation_input_tokens=cache_creation_tokens,
            uncached_input_tokens=max(0, input_tokens - cached_input_tokens),
            output_tokens=output_tokens,
            reasoning_output_tokens=max(0, int(getattr(usage, "reasoning_output_tokens", 0) or 0)),
            total_tokens=total_tokens,
            context_window=max(0, int(context_window or 0)),
            latency_ms=max(0, int(getattr(usage, "latency_ms", 0) or 0)),
            runtime_scene_id=str(meta.get("runtimeSceneId") or meta.get("runtime_scene_id") or "").strip(),
            provider_usage_keys=sorted(str(key) for key in provider_usage.keys()) if isinstance(provider_usage, dict) else [],
        )
    )
```

Add `_usage_scope_kind(meta)`:

```python
def _usage_scope_kind(metadata: Dict[str, Any]) -> str:
    mode = str(metadata.get("mode") or metadata.get("runKind") or "").strip()
    if str(metadata.get("teamId") or metadata.get("team_id") or "").strip():
        return "team_workflow"
    if "evolution" in mode:
        return "evolution"
    if str(metadata.get("sessionId") or metadata.get("session_id") or "").strip():
        return "chat_session"
    if str(metadata.get("agentId") or metadata.get("agent_id") or "").strip():
        return "agent_round"
    return "unknown"
```

- [ ] **Step 3: Call the recorder once in non-streaming `invoke()`**

After `usage = self._usage_from_response(response, latency_ms)` and message extraction, compute estimates only when provider usage has no counts:

```python
estimated_input_tokens = 0
estimated_output_tokens = 0
if not (usage.input_tokens or usage.output_tokens or usage.total_tokens):
    estimated_input_tokens = _estimate_messages_for_usage(messages)
    estimated_output_tokens = _estimate_text_for_usage(message.get("content") or "")
_record_usage_ledger_event(
    usage=usage,
    metadata=metadata,
    provider=self.provider.kind,
    model=self.profile.model,
    profile_id=self.profile_id,
    transport=str(protocol_summary.get("transport") or ""),
    role=self.role,
    context_window=max(0, int(getattr(self._resolved_spec, "context_window", 0) or 0)),
    estimated_input_tokens=estimated_input_tokens,
    estimated_output_tokens=estimated_output_tokens,
)
```

Keep `_record_llm_scene_event()` unchanged except adding `reasoningOutputTokens` to its safe counters.

- [ ] **Step 4: Call the recorder once in streaming completion**

Inside `stream_events()` where `llm.stream.succeeded` is recorded, after `usage_observation.latency_ms = ...` and before returning:

```python
if not (
    usage_observation.input_tokens
    or usage_observation.output_tokens
    or usage_observation.total_tokens
):
    usage_observation.input_tokens = _estimate_messages_for_usage(messages)
    usage_observation.output_tokens = _estimate_text_for_usage(full_text)
    usage_observation.total_tokens = usage_observation.input_tokens + usage_observation.output_tokens
_record_usage_ledger_event(
    usage=usage_observation,
    metadata=metadata,
    provider=self.provider.kind,
    model=self.profile.model,
    profile_id=self.profile_id,
    transport=str(event_metadata.get("transport") or ""),
    role=self.role,
    context_window=max(0, int(getattr(self._resolved_spec, "context_window", 0) or 0)),
)
```

If `full_text` is not currently available in that scope, accumulate text deltas into a local `generated_text_parts: list[str]` next to `text_delta_count`.

- [ ] **Step 5: Ledger write failures must not fail user responses**

Wrap `_record_usage_ledger_event(...)` calls so ledger failures are logged as bounded runtime-scene warnings, but model responses still return:

```python
try:
    _record_usage_ledger_event(...)
except Exception as exc:
    _record_llm_scene_event(
        "usage",
        "llm.usage_ledger.write_failed",
        message="LLM usage ledger write failed.",
        outcome="failed",
        fields={"errorType": type(exc).__name__, "profileId": self.profile_id, "provider": self.provider.kind, "model": self.profile.model},
        lifecycle=False,
    )
```

- [ ] **Step 6: Run client and existing token tests**

Run:

```powershell
& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" -m pytest tests/test_llm_client_usage_ledger.py tests/test_llm_usage_ledger.py -q
& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" -m pytest tests/test_agent_protocol.py -k "usage or token" -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 2**

Run:

```powershell
git status --short --branch
git add core/llm/client.py tests/test_llm_client_usage_ledger.py
git commit -m "feat: record global llm usage events"
```

Expected: one commit containing only Task 2 files.

### Task 3: Read-Only Usage Summary API

**Files:**
- Create: `core/web/routes/usage.py`
- Modify: `core/web/router_registry.py`
- Test: `tests/test_web_usage_routes.py`

**Interfaces:**
- Consumes: `build_usage_summary()` from `core.llm.usage_ledger`.
- Produces: `GET /api/usage/summary?scope=global|session|agent|model&sessionId=&agentId=&provider=&model=`.

- [ ] **Step 1: Write failing API route tests**

Create `tests/test_web_usage_routes.py`:

```python
from __future__ import annotations

from fastapi.testclient import TestClient

from core.llm.usage_ledger import UsageLedgerEvent, record_usage_event
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token


def test_usage_summary_route_returns_codex_style_global_summary(tmp_path, monkeypatch):
    monkeypatch.setattr("core.llm.usage_ledger.PROJECT_ROOT", tmp_path)
    client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})
    record_usage_event(
        UsageLedgerEvent(
            source="provider_usage",
            scope_kind="chat_session",
            session_id="session-api",
            provider="openai",
            model="gpt-5",
            input_tokens=100,
            cached_input_tokens=25,
            cache_read_input_tokens=25,
            uncached_input_tokens=75,
            output_tokens=50,
            reasoning_output_tokens=10,
            total_tokens=150,
        ),
        project_root=tmp_path,
    )

    response = client.get("/api/usage/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["lastTokenUsage"]["totalTokens"] == 150
    assert payload["globalTokenUsage"]["allTime"]["inputTokens"] == 100
    assert payload["globalTokenUsage"]["allTime"]["cachedInputTokens"] == 25
    assert payload["globalTokenUsage"]["allTime"]["reasoningOutputTokens"] == 10
    assert payload["globalTokenUsage"]["allTime"]["cacheHitRate"] == 0.25
    assert payload["diagnostics"]["source"] == "usage_ledger"


def test_usage_summary_route_filters_by_session(tmp_path, monkeypatch):
    monkeypatch.setattr("core.llm.usage_ledger.PROJECT_ROOT", tmp_path)
    client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})
    record_usage_event(UsageLedgerEvent(source="provider_usage", session_id="a", input_tokens=10, output_tokens=1, total_tokens=11), project_root=tmp_path)
    record_usage_event(UsageLedgerEvent(source="provider_usage", session_id="b", input_tokens=20, output_tokens=2, total_tokens=22), project_root=tmp_path)

    response = client.get("/api/usage/summary?scope=session&sessionId=b")

    assert response.status_code == 200
    assert response.json()["sessionTokenUsage"]["totalTokens"] == 22


def test_usage_summary_route_rejects_missing_session_id():
    client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

    response = client.get("/api/usage/summary?scope=session")

    assert response.status_code == 400
    assert "sessionId" in response.json()["detail"]
```

Run:

```powershell
& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" -m pytest tests/test_web_usage_routes.py -q
```

Expected: FAIL because `/api/usage/summary` is not registered.

- [ ] **Step 2: Implement route**

Create `core/web/routes/usage.py`:

```python
"""Token usage summary routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from core.llm.usage_ledger import build_usage_summary


router = APIRouter(tags=["usage"])


@router.get("/usage/summary")
def usage_summary(
    scope: str = Query("global", pattern="^(global|session|agent|model)$"),
    sessionId: str = "",
    agentId: str = "",
    provider: str = "",
    model: str = "",
) -> dict:
    if scope == "session" and not str(sessionId or "").strip():
        raise HTTPException(status_code=400, detail="sessionId is required when scope=session")
    if scope == "agent" and not str(agentId or "").strip():
        raise HTTPException(status_code=400, detail="agentId is required when scope=agent")
    if scope == "model" and not (str(provider or "").strip() or str(model or "").strip()):
        raise HTTPException(status_code=400, detail="provider or model is required when scope=model")
    return build_usage_summary(
        scope=scope,
        session_id=sessionId,
        agent_id=agentId,
        provider=provider,
        model=model,
    )
```

Modify `core/web/router_registry.py`:

```python
from .routes.usage import router as usage_router
```

and include it near other read-only operational routes:

```python
app.include_router(usage_router, prefix="/api")
```

- [ ] **Step 3: Run API tests**

Run:

```powershell
& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" -m pytest tests/test_web_usage_routes.py tests/test_llm_usage_ledger.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit Task 3**

Run:

```powershell
git status --short --branch
git add core/web/routes/usage.py core/web/router_registry.py tests/test_web_usage_routes.py
git commit -m "feat: expose token usage summary api"
```

Expected: one commit containing only Task 3 files.

### Task 4: Frontend DTOs, `/usage` Route, And Utility Menu Link

**Files:**
- Modify: `web/src/api/types.ts`
- Modify: `web/src/api/queryKeys.ts`
- Create: `web/src/routes/UsageRoute.tsx`
- Create: `web/src/routes/UsageRoute.styles.ts`
- Create: `web/src/routes/UsageRoute.layout.test.ts`
- Modify: `web/src/app/router.tsx`
- Modify: `web/src/app/router.test.ts`
- Modify: `web/src/app/AppShellUtilityMenu.tsx`
- Modify: `web/src/i18n/shellDictionary.ts`
- Modify: `web/src/app/AppShell.layout.test.ts`

**Interfaces:**
- Consumes: `/api/usage/summary`.
- Produces: `/usage` route, `Token` utility menu entry, `UsageSummaryResponse` TypeScript DTO.

- [ ] **Step 1: Add DTOs and query key tests through route test expectations**

Modify `web/src/api/types.ts`:

```ts
export type UsageSource = "provider_usage" | "estimated" | "missing" | "not_called";

export type TokenUsageSample = {
  source: UsageSource;
  recordedAt: string;
  scopeKind: string;
  sessionId: string;
  turnId: string;
  agentId: string;
  provider: string;
  model: string;
  profileId: string;
  inputTokens: number;
  cachedInputTokens: number;
  cacheReadInputTokens: number;
  cacheCreationInputTokens: number;
  uncachedInputTokens: number;
  outputTokens: number;
  reasoningOutputTokens: number;
  totalTokens: number;
  cacheHitRate: number;
  contextWindow: number;
  latencyMs: number;
};

export type TokenUsageRollup = {
  inputTokens: number;
  cachedInputTokens: number;
  cacheReadInputTokens: number;
  cacheCreationInputTokens: number;
  uncachedInputTokens: number;
  outputTokens: number;
  reasoningOutputTokens: number;
  totalTokens: number;
  cacheHitRate: number;
  observedCallCount: number;
  estimatedCallCount: number;
  missingCallCount: number;
  notCalledCount: number;
};

export type TokenUsageBreakdownItem = {
  key: string;
  label: string;
  provider: string;
  model: string;
  usage: TokenUsageRollup;
};

export type UsageSummaryResponse = {
  lastTokenUsage: TokenUsageSample;
  sessionTokenUsage: TokenUsageRollup;
  globalTokenUsage: {
    today: TokenUsageRollup;
    last7Days: TokenUsageRollup;
    allTime: TokenUsageRollup;
  };
  modelContextWindow: number;
  updatedAt: string;
  diagnostics: {
    source: "usage_ledger";
    skippedRecordCount: number;
    ledgerPath: string;
  };
  breakdowns: {
    models: TokenUsageBreakdownItem[];
    providers: TokenUsageBreakdownItem[];
    sources: Array<{ source: UsageSource; usage: TokenUsageRollup }>;
  };
};
```

Modify `web/src/api/queryKeys.ts`:

```ts
usageSummary: (scope = "global", sessionId = "", agentId = "", provider = "", model = "") =>
  ["usage", "summary", scope, sessionId, agentId, provider, model] as const,
```

- [ ] **Step 2: Create route layout test first**

Create `web/src/routes/UsageRoute.layout.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import routeSource from "./UsageRoute.tsx?raw";
import stylesSource from "./UsageRoute.styles.ts?raw";
import styles from "./UsageRoute.styles";

describe("UsageRoute layout contract", () => {
  it("renders a compact operational token usage route from the usage summary API", () => {
    expect(routeSource).toContain('fetchJson<UsageSummaryResponse>("/api/usage/summary")');
    expect(routeSource).toContain("queryKeys.usageSummary");
    expect(routeSource).toContain("globalTokenUsage");
    expect(routeSource).toContain("lastTokenUsage");
    expect(routeSource).toContain("provider_usage");
    expect(routeSource).toContain("estimated");
    expect(routeSource).toContain("missing");
    expect(routeSource).toContain("reasoningOutputTokens");
    expect(routeSource).not.toContain("cost");
    expect(routeSource).not.toContain("billing");
  });

  it("keeps the usage page dense without hero or nested-card composition", () => {
    expect(styles.page).toBeTypeOf("string");
    expect(styles.summaryGrid).toBeTypeOf("string");
    expect(styles.metricBand).toBeTypeOf("string");
    expect(stylesSource).toContain("grid-cols-[repeat(auto-fit,minmax(12rem,1fr))]");
    expect(stylesSource).toContain("min-h-0");
    expect(stylesSource).not.toContain("rounded-[2rem]");
    expect(stylesSource).not.toContain("text-6xl");
    expect(stylesSource).not.toContain("from-purple");
  });
});
```

Run:

```powershell
npm --prefix web run test -- UsageRoute.layout.test.ts
```

Expected: FAIL because route files do not exist.

- [ ] **Step 3: Implement `UsageRoute.styles.ts`**

Create a typed Tailwind style map:

```ts
const styles = {
  page: "vui-route-usage min-w-0 min-h-0 grid content-start gap-3 px-4 py-3 text-[var(--fg-primary)]",
  header: "vui-route-usage min-w-0 flex flex-wrap items-end justify-between gap-2 border-b border-[var(--vui-border-subtle)] pb-2",
  titleStack: "vui-route-usage min-w-0 grid gap-0.5",
  kicker: "vui-route-usage text-[var(--vui-font-xs)] font-semibold uppercase tracking-normal text-[var(--fg-tertiary)]",
  title: "vui-route-usage text-[var(--vui-font-xl)] font-semibold leading-tight text-[var(--fg-primary)]",
  meta: "vui-route-usage text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  summaryGrid: "vui-route-usage grid min-w-0 gap-2 grid-cols-[repeat(auto-fit,minmax(12rem,1fr))]",
  metricBand: "vui-route-usage min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] p-3 shadow-[var(--vui-shadow-hairline)]",
  metricLabel: "vui-route-usage text-[var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-tertiary)]",
  metricValue: "vui-route-usage mt-1 text-[var(--vui-font-2xl)] font-semibold leading-none text-[var(--fg-primary)]",
  metricDetail: "vui-route-usage mt-1 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-secondary)]",
  sourceRow: "vui-route-usage flex min-w-0 flex-wrap items-center gap-1.5",
  sourceBadge: "vui-route-usage inline-flex h-6 w-fit items-center rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]",
  detailGrid: "vui-route-usage grid min-w-0 gap-2 grid-cols-[minmax(0,1.1fr)_minmax(18rem,0.9fr)]",
  tablePanel: "vui-route-usage min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] p-2 shadow-[var(--vui-shadow-hairline)]",
  tableHeader: "vui-route-usage grid min-w-0 grid-cols-[minmax(0,1fr)_repeat(4,minmax(4.5rem,max-content))] gap-2 border-b border-[var(--vui-border-subtle)] px-2 pb-1 text-[var(--vui-font-xs)] font-semibold text-[var(--fg-tertiary)]",
  tableRow: "vui-route-usage grid min-w-0 grid-cols-[minmax(0,1fr)_repeat(4,minmax(4.5rem,max-content))] gap-2 px-2 py-1.5 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-secondary)]",
  nameCell: "vui-route-usage min-w-0 truncate font-semibold text-[var(--fg-primary)]",
  numericCell: "vui-route-usage justify-self-end tabular-nums text-[var(--fg-secondary)]",
  statePanel: "vui-route-usage rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] p-3 text-[var(--vui-font-sm)] text-[var(--fg-secondary)]",
} as const;

export default styles;
```

- [ ] **Step 4: Implement `UsageRoute.tsx`**

Create a compact route with no billing/cost UI:

```tsx
import { useQuery } from "@tanstack/react-query";
import { Activity } from "lucide-react";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import type { TokenUsageRollup, UsageSource, UsageSummaryResponse } from "../api/types";
import styles from "./UsageRoute.styles";

function formatTokens(value: number): string {
  const count = Math.max(0, Math.round(Number(value || 0)));
  if (count >= 1_000_000) return `${Number((count / 1_000_000).toFixed(1))}M`;
  if (count >= 1_000) return `${Number((count / 1_000).toFixed(1))}K`;
  return `${count}`;
}

function sourceLabel(source: UsageSource): string {
  if (source === "provider_usage") return "provider";
  if (source === "estimated") return "estimated";
  if (source === "missing") return "missing";
  return "not called";
}

function MetricBand({ label, usage }: { label: string; usage: TokenUsageRollup }) {
  return (
    <section className={styles.metricBand} aria-label={label}>
      <div className={styles.metricLabel}>{label}</div>
      <div className={styles.metricValue}>{formatTokens(usage.totalTokens)}</div>
      <div className={styles.metricDetail}>
        In {formatTokens(usage.inputTokens)} / Cached {formatTokens(usage.cachedInputTokens)} / Out {formatTokens(usage.outputTokens)}
      </div>
    </section>
  );
}

export function UsageRoute() {
  const summaryQuery = useQuery({
    queryKey: queryKeys.usageSummary("global"),
    queryFn: () => fetchJson<UsageSummaryResponse>("/api/usage/summary"),
    refetchInterval: 15_000,
    refetchIntervalInBackground: false,
  });

  if (summaryQuery.isPending && !summaryQuery.data) {
    return <main className={styles.page}><section className={styles.statePanel}>正在读取 Token 用量。</section></main>;
  }
  if (summaryQuery.isError || !summaryQuery.data) {
    return <main className={styles.page}><section className={styles.statePanel}>Token 用量读取失败。</section></main>;
  }

  const summary = summaryQuery.data;
  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div className={styles.titleStack}>
          <span className={styles.kicker}>Usage</span>
          <h1 className={styles.title}>Token</h1>
          <span className={styles.meta}>全局 Token 用量，仅统计 Vibelution 自己的 LLM 调用。</span>
        </div>
        <div className={styles.sourceRow} title="provider 表示上游真实返回；estimated 表示本地估算；missing 表示上游未返回且无法估算。">
          <Activity size={16} />
          <span className={styles.sourceBadge}>{sourceLabel(summary.lastTokenUsage.source)}</span>
          <span className={styles.meta}>{summary.updatedAt}</span>
        </div>
      </header>
      <section className={styles.summaryGrid} aria-label="Token usage rollups">
        <MetricBand label="上次调用" usage={{ ...summary.sessionTokenUsage, ...summary.lastTokenUsage, observedCallCount: 0, estimatedCallCount: 0, missingCallCount: 0, notCalledCount: 0 }} />
        <MetricBand label="今日" usage={summary.globalTokenUsage.today} />
        <MetricBand label="最近 7 天" usage={summary.globalTokenUsage.last7Days} />
        <MetricBand label="全部时间" usage={summary.globalTokenUsage.allTime} />
      </section>
      <section className={styles.detailGrid}>
        <div className={styles.tablePanel}>
          <div className={styles.tableHeader}>
            <span>Model</span><span>In</span><span>Cached</span><span>Out</span><span>Total</span>
          </div>
          {summary.breakdowns.models.slice(0, 12).map((item) => (
            <div key={item.key} className={styles.tableRow}>
              <span className={styles.nameCell}>{item.label}</span>
              <span className={styles.numericCell}>{formatTokens(item.usage.inputTokens)}</span>
              <span className={styles.numericCell}>{formatTokens(item.usage.cachedInputTokens)}</span>
              <span className={styles.numericCell}>{formatTokens(item.usage.outputTokens)}</span>
              <span className={styles.numericCell}>{formatTokens(item.usage.totalTokens)}</span>
            </div>
          ))}
        </div>
        <div className={styles.tablePanel}>
          <div className={styles.tableHeader}>
            <span>Source</span><span>Calls</span><span>In</span><span>Out</span><span>Total</span>
          </div>
          {summary.breakdowns.sources.map((item) => (
            <div key={item.source} className={styles.tableRow}>
              <span className={styles.nameCell}>{sourceLabel(item.source)}</span>
              <span className={styles.numericCell}>{item.usage.observedCallCount + item.usage.estimatedCallCount + item.usage.missingCallCount}</span>
              <span className={styles.numericCell}>{formatTokens(item.usage.inputTokens)}</span>
              <span className={styles.numericCell}>{formatTokens(item.usage.outputTokens)}</span>
              <span className={styles.numericCell}>{formatTokens(item.usage.totalTokens)}</span>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
```

- [ ] **Step 5: Register `/usage` route**

Modify `web/src/app/router.tsx`:

```tsx
const UsageRoute = lazyRoute(() => import("../routes/UsageRoute").then((module) => ({ default: module.UsageRoute })));
```

Add child route beside `git` and `logs`:

```tsx
{ path: "usage", ...guardedLazyElement(<UsageRoute />) },
{ path: "git", ...guardedLazyElement(<GitRoute />) },
{ path: "logs", ...guardedLazyElement(<LogsRoute />) },
```

Modify `web/src/app/router.test.ts`:

```ts
it("guards the usage route with workbench loading fallback and error boundary", () => {
  const route = findWorkbenchRoute("usage");
  expectRouteErrorSurface(route, "workbench");
  expectLazyFallback(route, "正在打开工作台", "workbench");
});
```

- [ ] **Step 6: Add utility menu entry**

Modify `web/src/app/AppShellUtilityMenu.tsx` import:

```ts
import { Activity, ExternalLink, FolderTree, GitBranch, ScrollText, Search } from "lucide-react";
```

Add the same-grid entry between Launcher and Logs:

```tsx
<NavLink
  to="/usage"
  className={({ isActive }) => isActive ? `${styles.utilityButton} ${styles.utilityButtonActive}` : styles.utilityButton}
  role="menuitem"
  onClick={onClose}
  title={t("usageUtilityTitle")}
>
  <Activity size={16} />
  <span>{t("navUsage")}</span>
</NavLink>
```

Modify `web/src/i18n/shellDictionary.ts`:

```ts
navUsage: "Token",
usageUtilityTitle: "全局 Token 用量",
topUtilityMenuHint: "启动器、Token、日志、Git 和文件仍是独立入口，悬停后快速打开。",
```

English:

```ts
navUsage: "Token",
usageUtilityTitle: "Global token usage",
topUtilityMenuHint: "Launcher, Token, Logs, Git, and files remain separate shortcuts behind this hover menu.",
```

Modify `web/src/app/AppShell.layout.test.ts` in the utility menu test:

```ts
expect(utilityMenuSource).toContain('to="/usage"');
expect(utilityMenuSource.indexOf('to="/usage"')).toBeLessThan(utilityMenuSource.indexOf('to="/logs"'));
expect(utilityMenuSource).toContain('t("navUsage")');
expect(utilityMenuSource).toContain('t("usageUtilityTitle")');
expect(primaryNav).not.toContain('to="/usage"');
```

- [ ] **Step 7: Run frontend focused tests**

Run:

```powershell
npm --prefix web run test -- UsageRoute.layout.test.ts AppShell.layout.test.ts router.test.ts
```

Expected: PASS.

- [ ] **Step 8: Commit Task 4**

Run:

```powershell
git status --short --branch
git add web/src/api/types.ts web/src/api/queryKeys.ts web/src/routes/UsageRoute.tsx web/src/routes/UsageRoute.styles.ts web/src/routes/UsageRoute.layout.test.ts web/src/app/router.tsx web/src/app/router.test.ts web/src/app/AppShellUtilityMenu.tsx web/src/i18n/shellDictionary.ts web/src/app/AppShell.layout.test.ts
git commit -m "feat: add token usage workbench route"
```

Expected: one commit containing only Task 4 files.

### Task 5: Integration Validation, Visual Check, And Handoff

**Files:**
- No new files expected.
- May update project memory through the memory sync command after implementation if the current Agent owns the memory sync claim or can safely claim it.

**Interfaces:**
- Consumes: Tasks 1-4 commits.
- Produces: validation evidence, runtime refresh decision, version-impact recommendation, ready/blocked handoff.

- [ ] **Step 1: Run backend focused validation**

Run:

```powershell
& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" -m pytest tests/test_llm_usage_ledger.py tests/test_llm_client_usage_ledger.py tests/test_web_usage_routes.py -q
& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" -m pytest tests/test_agent_protocol.py -k "usage or token" -q
```

Expected: PASS.

- [ ] **Step 2: Run frontend focused validation and build**

Run:

```powershell
npm --prefix web run test -- UsageRoute.layout.test.ts AppShell.layout.test.ts router.test.ts
npm --prefix web run build
```

Expected: PASS. Existing chunk-size warnings may remain non-blocking if no error exit occurs.

- [ ] **Step 3: Run diff and status checks**

Run:

```powershell
git diff --check
git status --short --branch
```

Expected: no whitespace errors; only committed task branch commits remain.

- [ ] **Step 4: Browser visual verification**

After build passes and Launcher refresh is allowed, open `/usage` and verify:

- The top `工作台工具` menu contains `启动器`, `Token`, `日志`, `Git`, and `文件` in one grid.
- Clicking `Token` opens `/usage`.
- `/usage` shows 上次调用, 今日, 最近 7 天, 全部时间.
- Source labels distinguish provider, estimated, missing, and not called.
- Desktop and narrow viewport layouts do not overlap or horizontally scroll.

Recommended browser validation if the managed workbench is available:

```powershell
powershell -ExecutionPolicy Bypass -File "C:\Users\17533\Desktop\Vibelution\scripts\vibelution_launcher.ps1" -Action restart
```

If Launcher reports active work, do not force refresh unless the user gives the exact phrase `确认强制接管并刷新 Vibelution`.

- [ ] **Step 5: Project memory and version judgment**

Version impact recommendation: `minor`, because this adds a compatible new usage ledger, API, and workbench route.

Memory update proposal if no memory claim is taken:

```text
Lane: agent-runtime-core
Focus: Global Token usage ledger and workbench route
Update: Added a Vibelution-owned LLM usage ledger design/implementation for provider-observed, estimated, missing, and not-called Token accounting, plus a /usage workbench route reachable from the top utility menu.
```

- [ ] **Step 6: Release claims**

Release each active claim with the actual validation summary:

```powershell
& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py" "C:\Users\17533\Desktop\Vibelution" release --claim-id "<backend-claim-id>" --status completed --reason "Implemented and validated global Token usage ledger/API."
& "C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe" "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py" "C:\Users\17533\Desktop\Vibelution" release --claim-id "<frontend-claim-id>" --status completed --reason "Implemented and validated /usage route and utility menu Token entry."
```

Expected: both claims are released or completed.

## Self-Review Checklist

- Spec coverage: covered Vibelution-only scope, Codex-style last/session/global shape, provider/estimated/missing/not-called source distinction, cache fields, reasoning tokens, independent `/usage` route, and top utility menu entry parallel to Launcher/Logs/Git/Files.
- Placeholder scan: no banned placeholder or copy-by-reference instructions are used.
- Type consistency: backend snake_case fields are persisted in SQLite; API/TypeScript uses camelCase DTO fields; source enum values match across Python and TypeScript.
- Source-of-truth check: ledger is canonical; existing runtime/session token surfaces remain projections and are not upgraded to global truth.
- Developer-mode parity: ledger path is routed through `developer_sandbox.route_workspace_path(...)`.
- Logging decision: ledger write failures produce bounded runtime-scene warnings; successful per-call ledger writes are proved by ledger rows and do not emit noisy success logs.
- Test decision: new backend unit/API tests plus frontend route/menu/router tests and web build are required.
