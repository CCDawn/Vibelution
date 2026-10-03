"""Session-list read-path memo caches.

Covers the two read caches added for ``query_sessions``:

- ``session_service._agent_directory_stub_hidden_team_member_ids`` memoizes the
  hidden-team-member id set per (teams.json, chat_rooms.json) stat signature;
- ``agent_directory_service._agent_workspace_event_path`` memoizes routed
  workspace event paths in a bounded LRU keyed by (active project root, raw
  workspace string, filename) plus the sandbox routing fingerprint.

Both caches must return values indistinguishable from the unmemoized path and
must invalidate whenever an underlying file changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from core.web.services import (
    agent_directory_service,
    agent_mode_binding_service,
    chat_room_service,
    project_agent_bus_service,
    session_service,
    team_service,
)
from core.web.services.agent_directory import ops_residual
from core.web.services.session import conversation_index


HIDDEN_TEAM_KWARGS = {"team_kind": "research", "team_source": "research_organization"}


@pytest.fixture(autouse=True)
def _use_tmp_project_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Pin every PROJECT_ROOT the read closure touches to one tmp project.

    PROJECT_ROOT alone is not a storage isolation boundary for the Agent
    directory (it may fall back to the operator data home), so the data home
    is pinned too. The memo caches are dropped around each test so no tmp
    path can leak across tests even without the key anchoring.
    """

    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_mode_binding_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    conversation_index._reset_agent_directory_stub_hidden_team_member_ids_cache_for_tests()
    ops_residual._reset_agent_workspace_event_path_cache_for_tests()
    yield
    conversation_index._reset_agent_directory_stub_hidden_team_member_ids_cache_for_tests()
    ops_residual._reset_agent_workspace_event_path_cache_for_tests()


def _count_list_teams_compact_calls(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Wrap ``team_service.list_teams_compact`` with a call counter."""

    calls = [0]
    original = team_service.list_teams_compact

    def _counting(*args: Any, **kwargs: Any):
        calls[0] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(team_service, "list_teams_compact", _counting)
    return calls


def _seed_hidden_team(member_session_id: str = "session-hidden-1", display_name: str = "Alpha") -> str:
    agent = agent_directory_service.create_agent_instance(
        display_name=display_name,
        direct_session_id=member_session_id,
    )
    team_service.create_team(
        name="Research Team",
        members=[{"agentId": agent["agentId"], "role": "lead"}],
        **HIDDEN_TEAM_KWARGS,
    )
    return str(agent["agentId"])


# ---------------------------------------------------------------------------
# Fix 1: hidden-team-member id stat-signature cache
# ---------------------------------------------------------------------------


def test_hidden_team_member_ids_second_call_hits_cache_with_identical_value(tmp_path, monkeypatch):
    agent_id = _seed_hidden_team()

    first = session_service._agent_directory_stub_hidden_team_member_ids()
    # Warm a second time: the first call may itself rewrite the backing files
    # (compact repair saves), so the signature stored by call one can be
    # immediately stale. After two calls the stored signature is settled.
    second = session_service._agent_directory_stub_hidden_team_member_ids()
    assert first == second == {agent_id}
    assert conversation_index._AGENT_DIRECTORY_STUB_HIDDEN_TEAM_MEMBER_IDS_CACHE

    calls = _count_list_teams_compact_calls(monkeypatch)
    third = session_service._agent_directory_stub_hidden_team_member_ids()
    assert calls[0] == 0  # served from cache, no team/room I/O at all
    assert third == {agent_id}

    # The cached value is a copy: mutating a returned set must not pollute
    # later cache hits.
    third.add("agent-polluted")
    fourth = session_service._agent_directory_stub_hidden_team_member_ids()
    assert fourth == {agent_id}


def test_hidden_team_member_ids_cache_invalidates_on_teams_file_change(tmp_path, monkeypatch):
    agent_id = _seed_hidden_team("session-hidden-1", "Alpha")
    session_service._agent_directory_stub_hidden_team_member_ids()
    session_service._agent_directory_stub_hidden_team_member_ids()

    calls = _count_list_teams_compact_calls(monkeypatch)

    # A second hidden team rewrites teams.json (new membership) -> the
    # signature changes and the set must be recomputed, not served stale.
    # Seeding itself may consult list_teams_compact through unrelated team
    # knowledge paths, so the recompute is asserted as exactly one further
    # call beyond the post-seed baseline.
    other_agent_id = _seed_hidden_team("session-hidden-2", "Beta")
    baseline = calls[0]

    refreshed = session_service._agent_directory_stub_hidden_team_member_ids()
    assert calls[0] == baseline + 1  # cache miss: recomputed exactly once
    assert refreshed == {agent_id, other_agent_id}

    # And the refreshed value is cached again.
    assert session_service._agent_directory_stub_hidden_team_member_ids() == refreshed
    assert calls[0] == baseline + 1


def test_hidden_team_member_ids_reset_hook_clears_cache(tmp_path, monkeypatch):
    agent_id = _seed_hidden_team()
    session_service._agent_directory_stub_hidden_team_member_ids()
    assert conversation_index._AGENT_DIRECTORY_STUB_HIDDEN_TEAM_MEMBER_IDS_CACHE

    conversation_index._reset_agent_directory_stub_hidden_team_member_ids_cache_for_tests()
    assert conversation_index._AGENT_DIRECTORY_STUB_HIDDEN_TEAM_MEMBER_IDS_CACHE == {}

    # After the reset the next call recomputes from the source again.
    calls = _count_list_teams_compact_calls(monkeypatch)
    assert session_service._agent_directory_stub_hidden_team_member_ids() == {agent_id}
    assert calls[0] == 1


def test_hidden_team_member_ids_recomputes_after_chat_room_state_change(tmp_path, monkeypatch):
    """Room-state churn invalidates the memo and membership truth still wins.

    The chat-room state file is part of the compact projection closure (round
    reconciliation and linked-room metadata sync rewrite it), so the signature
    covers it: rewriting chat_rooms.json must drop the memo even though the
    hidden membership itself is carried by teams.json.
    """

    agent_id = _seed_hidden_team()
    session_service._agent_directory_stub_hidden_team_member_ids()
    session_service._agent_directory_stub_hidden_team_member_ids()

    # Rewrite the chat-room state file through the product write path.
    chat_room_service.create_chat_room(
        title="Unrelated Room",
        allow_empty_participants=True,
    )

    calls = _count_list_teams_compact_calls(monkeypatch)
    refreshed = session_service._agent_directory_stub_hidden_team_member_ids()
    assert calls[0] == 1  # room-state change invalidated the memo
    assert refreshed == {agent_id}

    # Team visibility is the source of truth: adding a hidden member now is
    # picked up on the next recompute even after room churn.
    other_agent_id = _seed_hidden_team("session-hidden-2", "Beta")
    updated = session_service._agent_directory_stub_hidden_team_member_ids()
    assert updated == {agent_id, other_agent_id}


def test_hidden_team_member_ids_signature_fails_open(monkeypatch):
    """A signature-collection failure must bypass the cache, not serve it."""

    session_service._agent_directory_stub_hidden_team_member_ids()
    assert conversation_index._AGENT_DIRECTORY_STUB_HIDDEN_TEAM_MEMBER_IDS_CACHE

    def _broken_signature() -> None:
        raise RuntimeError("signature probe broken")

    monkeypatch.setattr(
        conversation_index,
        "_agent_directory_stub_hidden_team_member_ids_signature",
        _broken_signature,
    )
    # Fail-open: compute without caching, no exception surfaces.
    value = session_service._agent_directory_stub_hidden_team_member_ids()
    assert isinstance(value, set)
    assert conversation_index._AGENT_DIRECTORY_STUB_HIDDEN_TEAM_MEMBER_IDS_CACHE  # untouched


# ---------------------------------------------------------------------------
# Fix 2: workspace event path LRU memo
# ---------------------------------------------------------------------------


def _agent_payload(workspace_path: str) -> dict[str, Any]:
    return {"agentId": "agent-demo", "workspacePath": workspace_path}


def test_agent_workspace_event_path_memo_hit_returns_identical_path(monkeypatch):
    agent = _agent_payload("workspace/agents/agent-demo")

    first = agent_directory_service._agent_workspace_event_path(agent, "agent_inbox_messages.jsonl")
    second = agent_directory_service._agent_workspace_event_path(agent, "agent_inbox_messages.jsonl")
    assert first == second
    assert ops_residual._AGENT_WORKSPACE_EVENT_PATH_CACHE

    def _broken_resolve(path_value: str) -> Path:
        raise AssertionError("memo hit must not re-resolve the project path")

    monkeypatch.setattr(agent_directory_service, "_resolve_project_path", _broken_resolve)
    third = agent_directory_service._agent_workspace_event_path(agent, "agent_inbox_messages.jsonl")
    assert third == first
    assert third.name == "agent_inbox_messages.jsonl"
    assert third.parent.name == "events"


def test_agent_workspace_event_path_keyed_by_raw_workspace_string():
    alpha = _agent_payload("workspace/agents/agent-alpha")
    beta = _agent_payload("workspace/agents/agent-beta")

    alpha_path = agent_directory_service._agent_workspace_event_path(alpha, "events.jsonl")
    beta_path = agent_directory_service._agent_workspace_event_path(beta, "events.jsonl")
    assert alpha_path != beta_path
    assert "agent-alpha" in str(alpha_path)
    assert "agent-beta" in str(beta_path)

    # Different filenames under one workspace are different keys too.
    other = agent_directory_service._agent_workspace_event_path(alpha, "group_context_events.jsonl")
    assert other != alpha_path
    assert other.name == "group_context_events.jsonl"


def test_agent_workspace_event_path_reset_hook_clears_cache(monkeypatch):
    agent = _agent_payload("workspace/agents/agent-demo")
    first = agent_directory_service._agent_workspace_event_path(agent, "events.jsonl")
    assert ops_residual._AGENT_WORKSPACE_EVENT_PATH_CACHE

    ops_residual._reset_agent_workspace_event_path_cache_for_tests()
    assert ops_residual._AGENT_WORKSPACE_EVENT_PATH_CACHE == {}

    resolved_calls: list[str] = []
    original_resolve = agent_directory_service._resolve_project_path

    def _counting_resolve(path_value: str) -> Path:
        resolved_calls.append(str(path_value))
        return original_resolve(path_value)

    monkeypatch.setattr(agent_directory_service, "_resolve_project_path", _counting_resolve)
    second = agent_directory_service._agent_workspace_event_path(agent, "events.jsonl")
    assert second == first
    assert len(resolved_calls) == 1  # recomputed after the reset


def test_agent_workspace_event_path_lru_is_bounded(monkeypatch):
    monkeypatch.setattr(
        ops_residual,
        "_AGENT_WORKSPACE_EVENT_PATH_CACHE_MAX_ENTRIES",
        2,
    )
    for index in range(4):
        agent = _agent_payload(f"workspace/agents/agent-{index}")
        agent_directory_service._agent_workspace_event_path(agent, "events.jsonl")
    assert len(ops_residual._AGENT_WORKSPACE_EVENT_PATH_CACHE) <= 2
