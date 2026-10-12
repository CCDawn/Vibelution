"""Lock-scoping regression tests for the knowledge source inbox staging path.

Heavy staging I/O (original file writes, attachment copies, central snapshot
copies, staged document reads, PDF text extraction) runs outside the shared
team-knowledge write lock. These tests pin the two safety properties that the
lock-free staging must preserve: staging failures leave no half-registered
store state (and clean their temporary positions), and the between-locks
status re-check keeps concurrent reviews of one source single-winner.
"""

from __future__ import annotations

import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from core.infrastructure import developer_sandbox
from core.web.services import (
    agent_directory_service,
    chat_room_service,
    team_knowledge_service,
    team_service,
)


@pytest.fixture(autouse=True)
def isolate_developer_sandbox_config(tmp_path, monkeypatch):
    config_path = tmp_path / "developer-mode-off.toml"
    config_path.write_text("[launcher]\ncontrol_port = 8765\n", encoding="utf-8")
    project_root = tmp_path / "developer-mode-project"
    project_root.mkdir()
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(developer_sandbox, "CONFIG_PATH", config_path)
    monkeypatch.setattr(developer_sandbox, "PROJECT_ROOT", project_root)


@pytest.fixture
def knowledge_env(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", tmp_path)
    lead = agent_directory_service.create_agent_instance(
        display_name="Knowledge Lead",
        direct_session_id="session-knowledge-lead",
    )
    member = agent_directory_service.create_agent_instance(
        display_name="Knowledge Member",
        direct_session_id="session-knowledge-member",
    )
    team = team_service.create_team(
        name="Knowledge Staging Team",
        members=[
            {"agentId": lead["agentId"], "role": "lead"},
            {"agentId": member["agentId"], "role": "member"},
        ],
    )
    base = team_knowledge_service.create_knowledge_base(
        team["teamId"],
        name="Staging Safety",
        actor_agent_id=lead["agentId"],
    )
    return {"team": team, "base": base, "lead": lead, "member": member}


def _collect_pending_source(knowledge_env, *, label: str, local_file_paths=None) -> str:
    inbox_source = team_knowledge_service.collect_source_to_inbox(
        "team",
        knowledge_env["team"]["teamId"],
        source_type="manual_user_entry",
        source_ref={"note": f"Staging test source for {label}"},
        original_content=f"Captured source material for {label}.",
        original_filename=f"{label}.txt",
        title=f"Source for {label}",
        actor_agent_id=knowledge_env["member"]["agentId"],
        local_file_paths=local_file_paths,
    )
    return str(inbox_source["inboxSourceId"])


def test_collect_staging_failure_cleans_temporary_position_and_registers_nothing(
    knowledge_env, tmp_path, monkeypatch
):
    team_id = knowledge_env["team"]["teamId"]
    local_file = tmp_path / "staging-evidence.txt"
    local_file.write_text("Local evidence body that must never half-land in the inbox.", encoding="utf-8")

    def failing_copy2(*_args, **_kwargs):
        raise OSError("simulated staging copy failure")

    monkeypatch.setattr(shutil, "copy2", failing_copy2)

    with pytest.raises(OSError, match="simulated staging copy failure"):
        team_knowledge_service.collect_source_to_inbox(
            "team",
            team_id,
            source_type="manual_user_entry",
            source_ref={"note": "staging failure candidate"},
            original_content="Body written before the attachment copy fails.",
            original_filename="staging-failure.txt",
            title="Staging failure source",
            actor_agent_id=knowledge_env["member"]["agentId"],
            local_file_paths=[{"path": str(local_file), "title": "Evidence"}],
        )

    owner = team_knowledge_service._require_owner_context("team", team_id)
    sources_root = team_knowledge_service._owner_inbox_source_dir(owner, "probe").parent
    assert sources_root.exists()
    assert list(sources_root.iterdir()) == [], "the isolated staging directory must be cleaned up"
    stored = team_knowledge_service._read_jsonl(team_knowledge_service._owner_source_index_path(owner))
    assert stored == [], "no half-registered inbox source may survive a staging failure"


def test_promote_staging_failure_cleans_temporary_central_position_and_keeps_source_pending(
    knowledge_env, monkeypatch
):
    team_id = knowledge_env["team"]["teamId"]
    lead_id = knowledge_env["lead"]["agentId"]
    inbox_source_id = _collect_pending_source(knowledge_env, label="promote-failure")

    def failing_copy2(*_args, **_kwargs):
        raise OSError("simulated central snapshot copy failure")

    monkeypatch.setattr(shutil, "copy2", failing_copy2)

    with pytest.raises(OSError, match="simulated central snapshot copy failure"):
        team_knowledge_service.review_owner_inbox_source(
            "team",
            team_id,
            inbox_source_id,
            decision="accepted",
            reviewed_by_agent_id=lead_id,
        )

    inbox = team_knowledge_service.list_owner_source_inbox("team", team_id, agent_id=lead_id)
    assert inbox["sources"][0]["inboxSourceId"] == inbox_source_id
    assert inbox["sources"][0]["status"] == "pending", "a failed promotion must not resolve the source"
    assert team_knowledge_service.list_central_sources(agent_id=lead_id)["summary"]["centralSourceCount"] == 0

    accepted_root = team_knowledge_service._central_source_accepted_dir()
    leftovers = list(accepted_root.rglob("*")) if accepted_root.exists() else []
    assert not any(path.is_file() for path in leftovers), "no central snapshot file may half-land"
    assert not any(".staging-" in path.name for path in leftovers), "staging directories must be cleaned up"


def test_concurrent_reviews_of_one_source_resolve_exactly_once_with_status_recheck(
    knowledge_env, monkeypatch
):
    team_id = knowledge_env["team"]["teamId"]
    base_id = knowledge_env["base"]["knowledgeBaseId"]
    lead_id = knowledge_env["lead"]["agentId"]
    member_id = knowledge_env["member"]["agentId"]
    inbox_source_id = _collect_pending_source(knowledge_env, label="concurrent-review")

    original_normalize = team_knowledge_service._normalize_formal_knowledge_content
    normalize_calling_threads: list[int] = []

    def slow_normalize(value):
        # Widen the lock-free validation window so both reviews pass the
        # admission lock before either one commits, forcing the losing
        # request to be rejected by the between-locks status re-check.
        normalize_calling_threads.append(threading.get_ident())
        time.sleep(0.4)
        return original_normalize(value)

    monkeypatch.setattr(team_knowledge_service, "_normalize_formal_knowledge_content", slow_normalize)

    barrier = threading.Barrier(2)

    def review_concurrently(_index: int):
        barrier.wait(timeout=5)
        return team_knowledge_service.review_owner_inbox_source(
            "team",
            team_id,
            inbox_source_id,
            decision="accepted",
            reviewed_by_agent_id=lead_id,
            ingest_on_accept=True,
            knowledge_base_id=base_id,
            knowledge_title="Concurrent direct ingestion",
            knowledge_content="Only one concurrent review may resolve this source.",
        )

    outcomes: list[str] = []
    errors: list[Exception] = []

    def run_review(index: int):
        try:
            result = review_concurrently(index)
        except team_knowledge_service.TeamKnowledgeError as exc:
            errors.append(exc)
            outcomes.append("error")
            return
        assert result["source"]["status"] == "accepted"
        outcomes.append("ok")

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(run_review, range(2)))

    assert sorted(outcomes) == ["error", "ok"]
    assert len(errors) == 1
    assert "Only pending or needs_more_context inbox sources can be reviewed." in str(errors[0])
    assert len(set(normalize_calling_threads)) == 2, (
        "both reviews must clear the admission lock (seeing status=pending) before either "
        "one commits, so the loser is rejected by the between-locks status re-check"
    )

    inbox = team_knowledge_service.list_owner_source_inbox("team", team_id, agent_id=lead_id)
    assert inbox["sources"][0]["inboxSourceId"] == inbox_source_id
    assert inbox["sources"][0]["status"] == "accepted"
    assert inbox["summary"]["acceptedSourceCount"] == 1

    central = team_knowledge_service.list_central_sources(agent_id=lead_id)
    assert central["summary"]["centralSourceCount"] == 1

    items = team_knowledge_service.list_knowledge_items(base_id, agent_id=member_id)
    assert len(items["items"]) == 1, "direct ingestion must run exactly once for the winning review"

    owner = team_knowledge_service._require_owner_context("team", team_id)
    reviewed_audits = [
        entry
        for entry in team_knowledge_service._read_jsonl(team_knowledge_service._audit_path_for_owner(owner))
        if entry.get("action") == "knowledge.source_inbox.reviewed"
    ]
    assert len(reviewed_audits) == 1, "the losing review must not emit a review audit event"
