from __future__ import annotations

import copy
import re
import secrets
import threading
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.web.services.session import agent_sessions


class _Sandbox:
    def __init__(self, root: Path) -> None:
        self.root = root

    def sandboxed_workspace_path(self, _project_root: Path, name: str) -> Path:
        path = self.root / "sandbox" / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def formal_workspace_path(self, _project_root: Path, name: str) -> Path:
        path = self.root / "formal" / name
        path.mkdir(parents=True, exist_ok=True)
        return path


class _Directory:
    def __init__(self, agents: list[dict]) -> None:
        self.agents = agents

    def list_agents(self, *, include_archived: bool, detail: str = "summary") -> list[dict]:
        return copy.deepcopy(self.agents)

    def get_agent(self, agent_id: str, *, include_archived: bool = False) -> dict | None:
        return next(
            (copy.deepcopy(row) for row in self.agents if row.get("agentId") == agent_id),
            None,
        )


class _Service:
    CHAT_STATE_VERSION = 1
    _SESSION_WORKSPACE_SAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")

    def __init__(self, root: Path, conversations: list[dict], agents: list[dict]) -> None:
        self.PROJECT_ROOT = root / "project"
        self.PROJECT_ROOT.mkdir(parents=True)
        self._CHAT_STATE_LOCK = threading.RLock()
        self.chat_state = {
            "version": 1,
            "active_conversation_id": "other-session",
            "updated_at": "2026-08-24T00:00:00Z",
            "conversations": copy.deepcopy(conversations),
        }
        self.agent_directory_service = _Directory(agents)
        self.developer_sandbox = _Sandbox(root)
        self.secrets = secrets

    def chat_state_transaction(self, _root: Path):
        return nullcontext()

    def load_chat_state(self, _root: Path) -> dict:
        return copy.deepcopy(self.chat_state)

    def save_chat_state(self, _root: Path, payload: dict, **_kwargs) -> None:
        self.chat_state = copy.deepcopy(payload)

    def _agent_session_workspace_roots(self) -> list[Path]:
        return agent_sessions._agent_session_workspace_roots()

    def _safe_session_workspace_token(self, session_id: str) -> str:
        return agent_sessions._safe_session_workspace_token(session_id)

    def _path_is_reparse_point(self, _path: Path) -> bool:
        return False

    def _agent_lookup_for_conversations(self) -> dict[str, dict]:
        return {
            row["agentId"]: row
            for row in self.agent_directory_service.agents
            if row.get("agentId")
        }

    def _normalize_conversation(self, row: dict, **_kwargs) -> dict:
        return row

    def _conversation_phase(self, _session_id: str, row: dict) -> str:
        return str(row.get("status") or row.get("state") or "ready").lower()

    def list_active_session_work_runs(self, *, reconcile: bool = False) -> list[dict]:
        return []

    def _set_session_running(self, *_args) -> None:
        return None

    def _clear_session_turn_control(self, *_args) -> None:
        return None

    def _clear_session_live_output(self, *_args) -> None:
        return None

    def _invalidate_session_agent_runtime_cache(self, *_args) -> None:
        return None

    def _invalidate_session_conversation_events_cache(self, *_args) -> None:
        return None

    def _invalidate_session_list_cache(self) -> None:
        return None

    def _record_agent_session_lifecycle_event(self, *_args, **_kwargs) -> None:
        return None

    def _now_timestamp(self) -> str:
        return "2026-08-24T00:00:01Z"

    def _new_conversation_id(self, existing: set[str]) -> str:
        index = 1
        while f"replacement-{index}" in existing:
            index += 1
        return f"replacement-{index}"

    def _make_empty_conversation(self, session_id: str, *, title: str, timestamp: str) -> dict:
        return {
            "conversation_id": session_id,
            "title": title,
            "created_at": timestamp,
            "updated_at": timestamp,
            "messages": [],
        }

    def _timestamp_sort_key(self, _value: str) -> int:
        return 0


def _conversation(session_id: str, *, agent_id: str = "", parent: str = "", team_id: str = "research-team", status: str = "ready") -> dict:
    return {
        "conversation_id": session_id,
        "agent_id": agent_id,
        "parent_session_id": parent,
        "team_id": team_id,
        "status": status,
        "messages": [{"role": "user", "content": "fixture"}],
    }


def _service_fixture(tmp_path: Path, *, active: bool = False) -> _Service:
    agents = [
        {
            "agentId": "agent-search",
            "status": "active",
            "directSessionId": "session-search",
            "teamId": "research-team",
            "roleKey": "challenge_cup_search",
        },
        {
            "agentId": "agent-exec",
            "status": "active",
            "directSessionId": "session-exec",
            "teamId": "research-team",
            "roleKey": "challenge_cup_execution_steward",
        },
        {
            "agentId": "agent-other",
            "status": "active",
            "directSessionId": "session-other",
            "teamId": "other-team",
            "roleKey": "other_role",
        },
    ]
    conversations = [
        _conversation("session-search", agent_id="agent-search"),
        _conversation("child-search", agent_id="agent-search", parent="session-search"),
        _conversation("session-exec", agent_id="agent-exec", status="running" if active else "ready"),
        _conversation("session-other", agent_id="agent-other", team_id="other-team"),
        _conversation("other-session"),
    ]
    service = _Service(tmp_path, conversations, agents)
    for session_id in ("session-search", "child-search", "session-exec", "session-other"):
        workspace = tmp_path / "sandbox" / "sessions" / session_id
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "turn_journal.jsonl").write_text(
            f"{{\"sessionId\":\"{session_id}\"}}\n",
            encoding="utf-8",
        )
    return service


def test_team_agent_session_reset_stage_purge_restore_and_destroy(monkeypatch, tmp_path: Path) -> None:
    service = _service_fixture(tmp_path)
    monkeypatch.setattr(agent_sessions, "_service", lambda: service)

    stage = agent_sessions.stage_team_agent_session_reset(
        "research-team",
        ["agent-search", "agent-exec"],
        "reset-session-1",
    )
    assert stage["status"] == "staged"
    assert stage["sessionIds"] == ["session-search", "child-search", "session-exec"]
    assert {row["conversation_id"] for row in service.chat_state["conversations"]} == {
        "session-other",
        "other-session",
    }
    assert not (service._agent_session_workspace_roots()[0] / "session-search").exists()

    purged = agent_sessions.purge_team_agent_session_reset(
        "research-team", "reset-session-1", stage
    )
    assert purged["status"] == "purged"

    restored = agent_sessions.restore_team_agent_session_reset(
        "research-team", "reset-session-1", stage
    )
    assert restored["status"] == "restored"
    assert {row["conversation_id"] for row in service.chat_state["conversations"]} == {
        "session-search",
        "child-search",
        "session-exec",
        "session-other",
        "other-session",
    }
    assert (service._agent_session_workspace_roots()[0] / "session-search").exists()

    discarded = agent_sessions.discard_restored_team_agent_session_reset_staging(
        "research-team", "reset-session-1"
    )
    assert discarded["status"] == "discarded"
    assert all(not Path(root).exists() for root in stage["stagingRoots"])

    retried = agent_sessions.stage_team_agent_session_reset(
        "research-team", ["agent-search", "agent-exec"], "reset-session-1"
    )
    agent_sessions.restore_team_agent_session_reset("research-team", "reset-session-1", retried)
    agent_sessions.discard_restored_team_agent_session_reset_staging(
        "research-team", "reset-session-1"
    )

    second = agent_sessions.stage_team_agent_session_reset(
        "research-team", ["agent-search"], "reset-session-2"
    )
    agent_sessions.purge_team_agent_session_reset("research-team", "reset-session-2", second)
    destroyed = agent_sessions.destroy_team_agent_session_reset(
        "research-team", "reset-session-2", second
    )
    assert destroyed["status"] == "destroyed"
    assert all(not Path(root).exists() for root in second["stagingRoots"])
    assert "session-search" not in {
        row["conversation_id"] for row in service.chat_state["conversations"]
    }


def test_team_agent_session_reset_rejects_cross_team_and_incomplete_authority(monkeypatch, tmp_path: Path) -> None:
    service = _service_fixture(tmp_path)
    monkeypatch.setattr(agent_sessions, "_service", lambda: service)
    with pytest.raises(agent_sessions.TeamAgentSessionResetValidationError, match="mismatched team"):
        agent_sessions.stage_team_agent_session_reset(
            "research-team", ["agent-other"], "reset-session-cross-team"
        )

    service.agent_directory_service.agents[0]["directSessionId"] = "missing-session"
    with pytest.raises(agent_sessions.TeamAgentSessionResetValidationError, match="missing"):
        agent_sessions.stage_team_agent_session_reset(
            "research-team", ["agent-search"], "reset-session-missing"
        )


def test_team_agent_session_reset_rejects_active_session(monkeypatch, tmp_path: Path) -> None:
    service = _service_fixture(tmp_path, active=True)
    monkeypatch.setattr(agent_sessions, "_service", lambda: service)
    with pytest.raises(agent_sessions.TeamAgentSessionResetBusyError, match="active work"):
        agent_sessions.stage_team_agent_session_reset(
            "research-team", ["agent-exec"], "reset-session-active"
        )
    assert {row["conversation_id"] for row in service.chat_state["conversations"]} == {
        "session-search",
        "child-search",
        "session-exec",
        "session-other",
        "other-session",
    }


def test_orphaned_purged_staging_can_only_be_destroyed_after_sessions_are_gone(monkeypatch, tmp_path: Path) -> None:
    service = _service_fixture(tmp_path)
    monkeypatch.setattr(agent_sessions, "_service", lambda: service)

    stage = agent_sessions.stage_team_agent_session_reset(
        "research-team", ["agent-search"], "reset-orphaned-1"
    )
    agent_sessions.purge_team_agent_session_reset("research-team", "reset-orphaned-1", stage)

    destroyed = agent_sessions.destroy_orphaned_purged_team_agent_session_reset_staging(
        "research-team", "reset-orphaned-1"
    )

    assert destroyed["status"] == "destroyed"
    assert destroyed["sessionCount"] == 2
    assert all(not Path(root).exists() for root in stage["stagingRoots"])

    retry = agent_sessions.stage_team_agent_session_reset(
        "research-team", ["agent-exec"], "reset-orphaned-live"
    )
    agent_sessions.purge_team_agent_session_reset("research-team", "reset-orphaned-live", retry)
    service.chat_state["conversations"].append(_conversation("session-exec", agent_id="agent-exec"))

    with pytest.raises(agent_sessions.TeamAgentSessionResetConflictError, match="sessions are live"):
        agent_sessions.destroy_orphaned_purged_team_agent_session_reset_staging(
            "research-team", "reset-orphaned-live"
        )


def test_team_agent_session_reset_destroy_removes_recreated_empty_direct_session(monkeypatch, tmp_path: Path) -> None:
    service = _service_fixture(tmp_path)
    monkeypatch.setattr(agent_sessions, "_service", lambda: service)

    stage = agent_sessions.stage_team_agent_session_reset(
        "research-team", ["agent-search"], "reset-recreated-direct"
    )
    agent_sessions.purge_team_agent_session_reset("research-team", "reset-recreated-direct", stage)
    service.chat_state["conversations"].append(
        {
            "conversation_id": "session-search",
            "agent_id": "agent-search",
            "messages": [],
        }
    )

    destroyed = agent_sessions.destroy_team_agent_session_reset(
        "research-team", "reset-recreated-direct", stage
    )

    assert destroyed["status"] == "destroyed"
    assert "session-search" not in {
        row["conversation_id"] for row in service.chat_state["conversations"]
    }


def test_team_agent_session_reset_destroy_rejects_recreated_direct_session_with_messages(monkeypatch, tmp_path: Path) -> None:
    service = _service_fixture(tmp_path)
    monkeypatch.setattr(agent_sessions, "_service", lambda: service)

    stage = agent_sessions.stage_team_agent_session_reset(
        "research-team", ["agent-search"], "reset-recreated-direct-message"
    )
    agent_sessions.purge_team_agent_session_reset(
        "research-team", "reset-recreated-direct-message", stage
    )
    service.chat_state["conversations"].append(
        {
            "conversation_id": "session-search",
            "agent_id": "agent-search",
            "messages": [{"role": "user", "content": "must not be deleted"}],
        }
    )

    with pytest.raises(agent_sessions.TeamAgentSessionResetConflictError, match="Active chat state"):
        agent_sessions.destroy_team_agent_session_reset(
            "research-team", "reset-recreated-direct-message", stage
        )
