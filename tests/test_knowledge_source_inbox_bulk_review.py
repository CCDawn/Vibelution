"""Bulk review for the knowledge owner source inbox (b2).

Batch accept/reject follows the rating-suggestion bulk shape: one owner
permission check, per-item resolution through the single-item authority, and
per-item failure reporting. Re-running the same batch is idempotent.
"""

from __future__ import annotations

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
        display_name="Bulk Review Lead",
        direct_session_id="session-bulk-lead",
    )
    member = agent_directory_service.create_agent_instance(
        display_name="Bulk Review Member",
        direct_session_id="session-bulk-member",
    )
    team = team_service.create_team(
        name="Bulk Review Team",
        members=[
            {"agentId": lead["agentId"], "role": "lead"},
            {"agentId": member["agentId"], "role": "member"},
        ],
    )
    base = team_knowledge_service.create_knowledge_base(
        team["teamId"],
        name="Bulk Review Base",
        actor_agent_id=lead["agentId"],
    )
    return {"team": team, "base": base, "lead": lead, "member": member}


def _collect_pending_source(knowledge_env, label: str) -> str:
    inbox_source = team_knowledge_service.collect_source_to_inbox(
        "team",
        knowledge_env["team"]["teamId"],
        source_type="manual_user_entry",
        source_ref={"note": f"Bulk review source {label}"},
        original_content=f"Captured bulk review material for {label}.",
        original_filename=f"{label}.txt",
        title=f"Bulk source {label}",
        actor_agent_id=knowledge_env["member"]["agentId"],
    )
    return str(inbox_source["inboxSourceId"])


def test_bulk_accept_reviews_every_source_and_promotes_central(knowledge_env):
    ids = [_collect_pending_source(knowledge_env, f"accept-{index}") for index in range(3)]
    result = team_knowledge_service.review_owner_inbox_sources_bulk(
        "team",
        knowledge_env["team"]["teamId"],
        inbox_source_ids=ids,
        decision="accepted",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )
    assert result["summary"] == {
        "requestedCount": 3,
        "reviewedCount": 3,
        "skippedCount": 0,
    }
    central_ids = {item["centralSource"]["centralSourceId"] for item in result["reviewed"]}
    assert len(central_ids) == 3
    inbox = team_knowledge_service.list_owner_source_inbox(
        "team", knowledge_env["team"]["teamId"], agent_id=knowledge_env["lead"]["agentId"]
    )
    statuses = {
        item["inboxSourceId"]: item["status"]
        for item in inbox["sources"]
    }
    assert all(statuses[inbox_id] == "accepted" for inbox_id in ids)


def test_bulk_reject_marks_sources_rejected(knowledge_env):
    ids = [_collect_pending_source(knowledge_env, f"reject-{index}") for index in range(2)]
    result = team_knowledge_service.review_owner_inbox_sources_bulk(
        "team",
        knowledge_env["team"]["teamId"],
        inbox_source_ids=ids,
        decision="rejected",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
        resolution_note="重复截图",
    )
    assert result["summary"]["reviewedCount"] == 2
    inbox = team_knowledge_service.list_owner_source_inbox(
        "team", knowledge_env["team"]["teamId"], agent_id=knowledge_env["lead"]["agentId"]
    )
    statuses = {item["inboxSourceId"]: item["status"] for item in inbox["sources"]}
    assert all(statuses[inbox_id] == "rejected" for inbox_id in ids)


def test_bulk_review_is_idempotent_on_rerun(knowledge_env):
    inbox_id = _collect_pending_source(knowledge_env, "idempotent")
    first = team_knowledge_service.review_owner_inbox_sources_bulk(
        "team",
        knowledge_env["team"]["teamId"],
        inbox_source_ids=[inbox_id],
        decision="accepted",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )
    assert first["summary"]["reviewedCount"] == 1
    second = team_knowledge_service.review_owner_inbox_sources_bulk(
        "team",
        knowledge_env["team"]["teamId"],
        inbox_source_ids=[inbox_id],
        decision="accepted",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )
    # Same end state, no error: the reviewed source comes back as skipped.
    assert second["summary"] == {
        "requestedCount": 1,
        "reviewedCount": 0,
        "skippedCount": 1,
    }
    assert second["skipped"] == [{"inboxSourceId": inbox_id, "reason": "not_reviewable"}]


def test_bulk_review_reports_missing_sources_per_item(knowledge_env):
    inbox_id = _collect_pending_source(knowledge_env, "partial")
    result = team_knowledge_service.review_owner_inbox_sources_bulk(
        "team",
        knowledge_env["team"]["teamId"],
        inbox_source_ids=[inbox_id, "inbox-src-missing"],
        decision="rejected",
        reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
    )
    assert result["summary"] == {
        "requestedCount": 2,
        "reviewedCount": 1,
        "skippedCount": 1,
    }
    assert result["skipped"] == [{"inboxSourceId": "inbox-src-missing", "reason": "not_found"}]


def test_bulk_review_rejects_unknown_decisions_and_empty_batches(knowledge_env):
    with pytest.raises(team_knowledge_service.TeamKnowledgeError, match="accepted or rejected"):
        team_knowledge_service.review_owner_inbox_sources_bulk(
            "team",
            knowledge_env["team"]["teamId"],
            inbox_source_ids=["x"],
            decision="duplicate",
            reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
        )
    with pytest.raises(team_knowledge_service.TeamKnowledgeError, match="At least one"):
        team_knowledge_service.review_owner_inbox_sources_bulk(
            "team",
            knowledge_env["team"]["teamId"],
            inbox_source_ids=[],
            decision="accepted",
            reviewed_by_agent_id=knowledge_env["lead"]["agentId"],
        )


def test_bulk_review_requires_reviewer_permission(knowledge_env):
    inbox_id = _collect_pending_source(knowledge_env, "permission")
    with pytest.raises(team_knowledge_service.TeamKnowledgePermissionError):
        team_knowledge_service.review_owner_inbox_sources_bulk(
            "team",
            knowledge_env["team"]["teamId"],
            inbox_source_ids=[inbox_id],
            decision="accepted",
            reviewed_by_agent_id=knowledge_env["member"]["agentId"],
        )
