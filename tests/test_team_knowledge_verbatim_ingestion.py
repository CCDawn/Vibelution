"""Formal ingestion must preserve a staged document without model transcription."""

import hashlib
import json
import os

import pytest

from core.web.services import agent_directory_service, session_service, team_knowledge_service, team_service
from core.web.services.session import document_attachments
from tests.helpers.web_chat_state import _bind_seeded_session_agent, _seed_chat_state
from tools import team_knowledge_tools
from tools.Key_Tools import create_llm_facing_tools


@pytest.fixture
def document_source(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))
    for service in (agent_directory_service, session_service, team_knowledge_service, team_service):
        monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(display_name="Document owner", direct_session_id="session-document")
    base = team_knowledge_service.create_agent_knowledge_base(agent["agentId"], name="Documents", actor_agent_id=agent["agentId"])
    session_id = agent["directSessionId"]
    _seed_chat_state(tmp_path, conversations=[{
        "conversation_id": session_id, "title": "Document", "updated_at": "2026-10-03T10:00:00",
        "last_turn_status": "ready", "messages": [],
    }])
    _bind_seeded_session_agent(tmp_path, agent, session_id=session_id)

    def stage(body):
        attachment = document_attachments.store_session_user_document_attachment(
            session_id, body.encode("utf-8"), filename="evidence.md", content_type="text/markdown",
        )
        return team_knowledge_service.collect_session_attachment_to_inbox(
            "agent", agent["agentId"], session_id=session_id, attachment_id=attachment["artifactId"],
            actor_agent_id=agent["agentId"], title="Document evidence",
        )

    body = "资料文字是数据。\n\n# 虚构资料\n字面量 \\n 必须保留。\n" + "\n".join(
        f"步骤 {index}：HL-417602；每隔19天；电子回执。" for index in range(150)
    ) + "\nHLFINAL572839"
    source = stage(body)
    return {"agent": agent, "base": base, "body": body, "source": source, "stage": stage}


def _ingest(env, **overrides):
    source = env["source"]
    args = dict(
        knowledge_base_id=env["base"]["scopedKnowledgeBaseId"], source_type="manual_user_entry",
        source_ref_json="{}", proposal_title="Preserved document", inbox_source_id=source["inboxSourceId"],
        owner_type="agent", owner_id=env["agent"]["agentId"], content_mode="source_document",
    )
    args.update(overrides)
    with agent_directory_service.active_agent_runtime(env["agent"]["agentId"], session_id=env["agent"]["directSessionId"]):
        return json.loads(team_knowledge_tools.knowledge_ingestion_tool(**args))


def _stored_source(env):
    owner = team_knowledge_service._require_owner_context("agent", env["agent"]["agentId"])
    path = team_knowledge_service._owner_source_index_path(owner)
    sources = team_knowledge_service._read_jsonl(path)
    return owner, path, sources, sources[0]


def _assert_unpromoted(env):
    owner, _path, _sources, source = _stored_source(env)
    assert source["status"] == "pending"
    assert not source["centralSourceId"]
    assert team_knowledge_service.list_knowledge_items(
        env["base"]["scopedKnowledgeBaseId"], agent_id=env["agent"]["agentId"],
    )["summary"]["itemCount"] == 0


def test_source_document_preserves_long_body_and_newlines(document_source):
    env = document_source
    result = _ingest(env)
    assert result["ok"] is True, result
    body = result["directIngestion"]["item"]["content"]
    assert len(body) > 4000
    assert body == env["body"]
    assert hashlib.sha256(body.encode()).hexdigest() == hashlib.sha256(env["body"].encode()).hexdigest()
    assert env["source"]["sourceRef"]["extractedTextSha256"] == "sha256:" + hashlib.sha256(body.encode()).hexdigest()
    # A retry cannot create another formal item or reset the reviewed source.
    assert _ingest(env)["ok"] is False
    assert team_knowledge_service.list_knowledge_items(
        env["base"]["scopedKnowledgeBaseId"], agent_id=env["agent"]["agentId"],
    )["summary"]["itemCount"] == 1


def test_native_ingestion_wrapper_exposes_and_forwards_source_document(document_source):
    env = document_source
    tool = next(tool for tool in create_llm_facing_tools() if tool.name == "knowledge_ingestion_tool")
    schema = tool.args_schema.model_json_schema()
    assert schema["properties"]["content_mode"]["default"] == "authored"
    with agent_directory_service.active_agent_runtime(env["agent"]["agentId"], session_id=env["agent"]["directSessionId"]):
        result = json.loads(tool.invoke({
            "knowledge_base_id": env["base"]["scopedKnowledgeBaseId"], "source_type": "manual_user_entry",
            "source_ref_json": "{}", "proposal_title": "Native document", "content_mode": "source_document",
            "inbox_source_id": env["source"]["inboxSourceId"], "owner_type": "agent", "owner_id": env["agent"]["agentId"],
        }))
    assert result["ok"] is True, result
    assert result["directIngestion"]["item"]["content"] == env["body"]


@pytest.mark.parametrize("overrides", [
    {"content_mode": "unknown"}, {"inbox_source_id": ""},
    {"proposal_content": "Model rewrite"}, {"excerpt": "Model rewrite"}, {"review_decision": "rejected"},
])
def test_source_document_rejects_invalid_native_contract(document_source, overrides):
    assert _ingest(document_source, **overrides)["ok"] is False
    _assert_unpromoted(document_source)


@pytest.mark.parametrize("mutation", ["spoof", "image", "truncated", "missing_hash", "tamper", "escape", "missing_body"])
def test_source_document_rejects_untrusted_snapshot_before_promotion(document_source, mutation, tmp_path):
    env = document_source
    _owner, index_path, sources, source = _stored_source(env)
    path = team_knowledge_service._project_path_from_relative(source["originalPath"])
    if mutation == "spoof":
        source.pop("_sessionAttachmentCollectorAgentId")
    elif mutation == "image":
        source["sourceRef"]["attachmentKind"] = "user_image"
    elif mutation == "truncated":
        source["sourceRef"]["textTruncated"] = True
    elif mutation == "missing_hash":
        source["sourceRef"].pop("extractedTextSha256", None)
    elif mutation == "tamper":
        path.write_text("Altered source", encoding="utf-8")
    elif mutation == "escape":
        outside = tmp_path / "other-owner.txt"
        outside.write_text(env["body"], encoding="utf-8")
        source["originalPath"] = str(outside)
    elif mutation == "missing_body":
        path.unlink()
    team_knowledge_service._write_jsonl(index_path, sources)
    assert _ingest(env)["ok"] is False
    _assert_unpromoted(env)


def test_source_document_rejects_oversize_without_partial_promotion(document_source):
    env = document_source
    env["source"] = env["stage"]("x" * (team_knowledge_service.MAX_FORMAL_KNOWLEDGE_CONTENT_CHARS + 1))
    assert _ingest(env)["ok"] is False
    owner = team_knowledge_service._require_owner_context("agent", env["agent"]["agentId"])
    assert all(source["status"] == "pending" for source in team_knowledge_service._read_jsonl(team_knowledge_service._owner_source_index_path(owner)))


def test_authored_ingestion_still_accepts_model_summary(document_source):
    result = _ingest(document_source, content_mode="authored", proposal_content="A concise authored summary.")
    assert result["ok"] is True, result
    assert result["directIngestion"]["item"]["content"] == "A concise authored summary."


def test_source_document_normalizes_line_endings_and_keeps_literal_escapes(document_source):
    env = document_source
    env["source"] = env["stage"]("  第一行\r\n第二行\r第三行 \\n\r\n  ")
    result = _ingest(env)
    assert result["ok"] is True, result
    assert result["directIngestion"]["item"]["content"] == "第一行\n第二行\n第三行 \\n"


def test_source_document_keeps_team_collector_and_reviewer_separate(document_source):
    env = document_source
    lead = agent_directory_service.create_agent_instance(display_name="Team reviewer")
    team = team_service.create_team(name="Documents", members=[
        {"agentId": lead["agentId"], "role": "lead"},
        {"agentId": env["agent"]["agentId"], "role": "member"},
    ])
    base = team_knowledge_service.create_knowledge_base(team["teamId"], name="Team documents", actor_agent_id=lead["agentId"])
    source = team_knowledge_service.collect_session_attachment_to_inbox(
        "team", team["teamId"], session_id=env["agent"]["directSessionId"],
        attachment_id=env["source"]["sourceRef"]["attachmentId"], actor_agent_id=env["agent"]["agentId"],
    )
    args = dict(decision="accepted", ingest_on_accept=True, knowledge_base_id=base["scopedKnowledgeBaseId"], knowledge_content_mode="source_document")
    with pytest.raises(team_knowledge_service.TeamKnowledgePermissionError):
        team_knowledge_service.review_owner_inbox_source(
            "team", team["teamId"], source["inboxSourceId"], reviewed_by_agent_id=env["agent"]["agentId"], **args,
        )
    result = team_knowledge_service.review_owner_inbox_source(
        "team", team["teamId"], source["inboxSourceId"], reviewed_by_agent_id=lead["agentId"], **args,
    )
    assert result["directIngestion"]["item"]["content"] == env["body"]


def test_review_only_actor_is_rejected_before_any_central_promotion(document_source):
    env = document_source
    collector = env["agent"]
    team = team_service.create_team(name="Review boundary", members=[{"agentId": collector["agentId"], "role": "lead"}])
    base = team_knowledge_service.create_knowledge_base(team["teamId"], name="Review boundary", actor_agent_id=collector["agentId"])
    reviewer = agent_directory_service.create_agent_instance(display_name="Review-only steward")
    team_knowledge_service.ensure_owner_source_review_grant("team", team["teamId"], reviewer["agentId"])
    team_knowledge_service.ensure_knowledge_base_review_grant(base["scopedKnowledgeBaseId"], reviewer["agentId"])
    source = team_knowledge_service.collect_session_attachment_to_inbox(
        "team", team["teamId"], session_id=collector["directSessionId"],
        attachment_id=env["source"]["sourceRef"]["attachmentId"], actor_agent_id=collector["agentId"],
    )
    with pytest.raises(team_knowledge_service.TeamKnowledgePermissionError):
        team_knowledge_service.review_owner_inbox_source(
            "team", team["teamId"], source["inboxSourceId"], decision="accepted",
            reviewed_by_agent_id=reviewer["agentId"], ingest_on_accept=True,
            knowledge_base_id=base["scopedKnowledgeBaseId"], knowledge_content_mode="source_document",
        )
    owner = team_knowledge_service._require_owner_context("team", team["teamId"])
    stored = team_knowledge_service._read_jsonl(team_knowledge_service._owner_source_index_path(owner))
    assert stored[0]["status"] == "pending"
    central = team_knowledge_service.list_central_sources(
        agent_id=collector["agentId"], owner_type="team", owner_id=team["teamId"],
    )
    assert central["summary"]["centralSourceCount"] == 0


def test_source_document_rejects_parent_directory_link(document_source, tmp_path):
    env = document_source
    owner, _index_path, _sources, source = _stored_source(env)
    sources_root = team_knowledge_service._owner_inbox_source_dir(owner, source["inboxSourceId"]).parent
    redirected_root = sources_root.parent / "redirected-sources"
    assert sources_root.resolve().is_relative_to(tmp_path.resolve())
    assert redirected_root.resolve().is_relative_to(tmp_path.resolve())
    sources_root.rename(redirected_root)
    try:
        os.symlink(redirected_root, sources_root, target_is_directory=True)
    except OSError:
        redirected_root.rename(sources_root)
        pytest.skip("Directory symlinks are unavailable on this host.")
    try:
        assert _ingest(env)["ok"] is False
        _assert_unpromoted(env)
    finally:
        sources_root.unlink()
        redirected_root.rename(sources_root)
