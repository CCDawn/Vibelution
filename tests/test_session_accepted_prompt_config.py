"""Admission-time prompt evidence, private references and live authorization."""

from __future__ import annotations

import copy
import hashlib
import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from core.web.services import session_service
from core.web.services.session import accepted_prompt_config as accepted, queued_turns, submit, worker
from tests.helpers.web_chat_state import _bind_seeded_submittable_agent, _reset_seeded_session_runtime, _seed_chat_state


@pytest.fixture
def prompt_environment(tmp_path, monkeypatch):
    state = {
        "body": "accepted prompt A",
        "agent": {"agentId": "agent-a", "status": "active", "agentCode": "A", "displayName": "Agent A",
                  "primaryMode": "chat", "promptTemplateId": "prompt-a",
                  "personaProfile": {"identity": "persona A"}, "taskProfile": {"mission": "task A"},
                  "toolPolicy": {"allowedTools": ["old_tool"]}, "metadata": {"permission": "old"}},
        "conversation": {"conversation_id": "session-a", "agent_id": "agent-a"},
    }
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "get_agent", lambda *_a, **_k: copy.deepcopy(state["agent"]))
    monkeypatch.setattr(accepted.developer_sandbox, "sandboxed_workspace_path", lambda root, *parts: tmp_path.joinpath(*parts))

    def build(template_id, *, agent_id, **_kwargs):
        body = state["body"]
        return {"agentId": agent_id, "promptTemplateId": template_id, "content": body,
                "contentHash": hashlib.sha256(body.encode()).hexdigest(), "reason": ""}

    monkeypatch.setattr(session_service.prompt_template_service, "build_agent_prompt_snapshot", build)
    return state


def _capture(state, *, submission_id="submission-a", source="admission"):
    return accepted.capture_accepted_prompt_config(session_service, "session-a", state["conversation"],
                                                   submission_id=submission_id, source=source)


def _load(reference, *, session_id="session-a", agent_id="agent-a", submission_id="submission-a"):
    return accepted.load_accepted_prompt_config(session_service, session_id, reference,
                                               agent_id=agent_id, submission_id=submission_id)


def test_new_admission_reads_edited_body_and_profiles_even_when_template_id_is_unchanged(prompt_environment):
    state = prompt_environment
    reference_a = _capture(state)
    state["body"] = "accepted prompt B"
    state["agent"]["personaProfile"] = {"identity": "persona B"}
    state["agent"]["taskProfile"] = {"mission": "task B"}
    reference_b = _capture(state, submission_id="submission-b")
    assert reference_a["contentHash"] != reference_b["contentHash"]
    old = _load(reference_a)
    new = _load(reference_b, submission_id="submission-b")
    assert old["promptSnapshot"]["content"] == "accepted prompt A"
    assert old["profile"]["personaProfile"] == {"identity": "persona A"}
    assert new["promptSnapshot"]["content"] == "accepted prompt B"
    assert new["profile"]["taskProfile"] == {"mission": "task B"}


def test_unchanged_prompt_profiles_share_cache_version_across_admissions(prompt_environment):
    first = _capture(prompt_environment)
    second = _capture(prompt_environment, submission_id="submission-b")
    assert first["contentHash"] == second["contentHash"]
    assert first["ref"] != second["ref"]


def test_private_evidence_is_excluded_from_artifacts_references_and_recursive_search(prompt_environment):
    from core.web.services import file_service
    from core.web.services.session import conversation_references, document_attachments, image_attachments, session_body_search
    from tools import search_tools

    reference = _capture(prompt_environment)
    path = accepted._path(session_service, "session-a", reference["ref"])
    workspace = path.parents[2]
    assert workspace.name == session_service._safe_session_workspace_token("session-a")
    assert file_service._is_excluded_dir(path.parents[1])
    assert search_tools._should_skip_path(path)
    for artifact_id in (path.name, f".runtime/.accepted_prompt_configs/{path.name}"):
        with pytest.raises(FileNotFoundError):
            document_attachments.resolve_session_document_artifact("session-a", artifact_id)
        with pytest.raises(FileNotFoundError):
            image_attachments.resolve_session_image_artifact("session-a", artifact_id)
        with pytest.raises(ValueError, match="not found"):
            conversation_references._resolve_file_reference("session-a", {"artifactId": artifact_id})
    assert session_body_search.search_session_bodies(query="accepted prompt A", session_ids=["session-a"],
        workspace_resolver=lambda _sid: workspace) == {}


@pytest.mark.parametrize("binding", ["session", "agent", "submission"])
def test_reference_cannot_cross_identity_bindings(prompt_environment, binding):
    reference = _capture(prompt_environment)
    with pytest.raises(session_service.SessionValidationError, match="缺失或损坏"):
        _load(reference, **{f"{binding}_id": f"other-{binding}"})


@pytest.mark.parametrize("damage", ["missing", "corrupt", "oversize", "invalid_ref"])
def test_missing_or_corrupt_evidence_fails_closed_without_live_recapture(prompt_environment, monkeypatch, damage):
    reference = _capture(prompt_environment)
    path = accepted._path(session_service, "session-a", reference["ref"])
    if damage == "missing":
        path.unlink()
    elif damage == "corrupt":
        path.write_text('{"content":"tampered"}', encoding="utf-8")
    elif damage == "oversize":
        monkeypatch.setattr(accepted, "MAX_ACCEPTED_PROMPT_BYTES", 5)
    else:
        reference = {**reference, "ref": "../../other"}
    monkeypatch.setattr(session_service.prompt_template_service, "build_agent_prompt_snapshot",
                        lambda *_a, **_k: pytest.fail("invalid evidence must never refresh live"))
    with pytest.raises(session_service.SessionValidationError, match="缺失或损坏"):
        _load(reference)


@pytest.mark.parametrize("kind", ["ordinary", "companion"])
def test_only_prompt_profile_fields_are_pinned_and_live_revocations_survive(prompt_environment, kind):
    state = prompt_environment
    if kind == "companion":
        state["agent"]["metadata"]["companion"] = {"enabled": True, "bindingRevision": 1}
    bundle = _load(_capture(state))
    live = copy.deepcopy(state["agent"])
    live["toolPolicy"] = {"allowedTools": []}
    live["metadata"] = {"permission": "revoked", "companion": {"enabled": False, "bindingRevision": 2}}
    live["capabilities"] = []
    live["personaProfile"] = {"identity": "changed persona"}
    pinned = accepted.pin_agent_prompt_profile(live, bundle)
    assert pinned["personaProfile"] == {"identity": "persona A"}
    for field in ("toolPolicy", "metadata", "capabilities"):
        assert pinned[field] == live[field]
        assert field not in bundle["profile"]
    assert accepted.pin_agent_prompt_profile(None, bundle) is None
    assert "toolPolicy" not in json.dumps(bundle)


@pytest.fixture
def queued_environment(prompt_environment, monkeypatch):
    state = prompt_environment
    monkeypatch.setattr(session_service, "load_session_chat_state", lambda *_a: copy.deepcopy(state["conversation"]))
    monkeypatch.setattr(session_service, "save_session_chat_state", lambda _root, _sid, value: state.update(conversation=copy.deepcopy(value)))
    monkeypatch.setattr(session_service, "_session_submit_admit_lock", lambda *_a: nullcontext())
    monkeypatch.setattr(session_service, "_ensure_session_mutable", lambda *_a, **_k: None)
    monkeypatch.setattr(session_service, "_is_session_running", lambda *_a: False)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda *_a, **_k: None)
    monkeypatch.setattr(session_service, "_schedule_session_queued_turn_drain", lambda *_a: None)
    monkeypatch.setattr(queued_turns, "capture_model_parameters", lambda *_a, **_k: None)
    monkeypatch.setattr(queued_turns, "_record_queued_turn_steer_admission", lambda *_a: None)
    return state


def _enqueue():
    return queued_turns.enqueue_session_queued_turn("session-a", content="queued user message", attachments=[], references=[],
        mental_model_enabled=False, runtime_status_enabled=False, turn_mode="", write_intent=False,
        client_submission_id="submission-a")


def test_queue_pause_resume_reorder_keep_acceptance_and_edit_recaptures(queued_environment):
    state = queued_environment
    row = _enqueue()
    first = row["acceptedPromptConfig"]
    state["body"] = "accepted prompt B"
    for kwargs in ({"status": "paused"}, {"status": "queued"}, {"position": 1}):
        rows = queued_turns.update_session_queued_turn("session-a", row["id"], **kwargs)
        assert rows[0]["acceptedPromptConfig"] == first
    rows = queued_turns.update_session_queued_turn("session-a", row["id"], content="explicit new message")
    assert _load(rows[0]["acceptedPromptConfig"])["promptSnapshot"]["content"] == "accepted prompt B"
    assert _load(first)["promptSnapshot"]["content"] == "accepted prompt A"
    public = json.dumps(queued_turns.list_session_queued_turns("session-a"))
    assert "accepted prompt" not in public and "persona A" not in public and "task A" not in public
    assert "path" not in rows[0]["acceptedPromptConfig"]


@pytest.mark.parametrize("invalid", ["oversized", "missing_body"])
def test_queue_refuses_unusable_prompt_before_accepting_row(queued_environment, monkeypatch, invalid):
    if invalid == "oversized":
        monkeypatch.setattr(accepted, "MAX_ACCEPTED_PROMPT_BYTES", 1)
    else:
        monkeypatch.setattr(session_service.prompt_template_service, "build_agent_prompt_snapshot", lambda *_a, **_k: {})
    with pytest.raises(session_service.SessionValidationError):
        _enqueue()
    assert queued_turns.list_session_queued_turns("session-a") == []


@pytest.mark.parametrize("damaged", [False, True])
def test_drain_holds_original_evidence_or_blocks_damage(queued_environment, monkeypatch, damaged):
    state = queued_environment
    row = _enqueue()
    reference = row["acceptedPromptConfig"]
    if damaged:
        accepted._path(session_service, "session-a", reference["ref"]).unlink()
    state["body"] = "accepted prompt B"
    seen = []

    def dispatch(_sid, _content, **kwargs):
        reference = kwargs["_accepted_prompt_config_ref"]
        seen.append(_load(reference, submission_id=kwargs["_accepted_prompt_submission_id"]))
        return {"accepted": True}

    monkeypatch.setattr(session_service, "submit_session_message", dispatch)
    assert queued_turns.drain_session_queued_turns("session-a") is True
    if damaged:
        rows = queued_turns.list_session_queued_turns("session-a")
        assert rows[0]["status"] == "blocked" and seen == []
    else:
        assert seen[0]["promptSnapshot"]["content"] == "accepted prompt A"
        assert queued_turns.list_session_queued_turns("session-a") == []


def test_legacy_queue_dispatch_marks_origin_instead_of_claiming_original_snapshot(queued_environment, monkeypatch):
    state = queued_environment
    _enqueue()
    state["conversation"]["queued_turns"][0].pop("acceptedPromptConfig")
    seen = []
    monkeypatch.setattr(session_service, "submit_session_message", lambda *_a, **kw: seen.append(kw))
    assert queued_turns.drain_session_queued_turns("session-a") is True
    assert seen[0]["_accepted_prompt_config_ref"] is None
    assert seen[0]["_accepted_prompt_config_source"] == "legacy_queue_drain"


def test_startup_resume_inherits_original_ref_and_corruption_does_not_become_legacy(prompt_environment, monkeypatch):
    reference = _capture(prompt_environment)
    event = SimpleNamespace(turn_id="old-turn", event_type=session_service.EVENT_USER_MESSAGE,
        payload={"metadata": {"acceptedPromptConfig": reference}})
    guidance = SimpleNamespace(turn_id="old-turn", event_type=session_service.EVENT_USER_MESSAGE,
        payload={"source": "steer", "metadata": {"kind": "user_guidance"}})
    monkeypatch.setattr(session_service, "_load_session_conversation_events_cached", lambda *_a: [event, guidance])
    assert accepted.recovered_prompt_config_reference(session_service, "session-a", "old-turn") == (reference, "submission-a")
    event.payload["metadata"]["acceptedPromptConfig"] = None
    invalid, _ = accepted.recovered_prompt_config_reference(session_service, "session-a", "old-turn")
    with pytest.raises(session_service.SessionValidationError):
        _load(invalid)
    event.payload["metadata"].clear()
    assert accepted.recovered_prompt_config_reference(session_service, "session-a", "old-turn") == (None, "")


def test_guidance_without_an_original_submission_does_not_become_legacy(prompt_environment, monkeypatch):
    guidance = SimpleNamespace(turn_id="old-turn", event_type=session_service.EVENT_USER_MESSAGE,
        payload={"source": "steer", "metadata": {"kind": "user_interrupt_guidance"}})
    monkeypatch.setattr(session_service, "_load_session_conversation_events_cached", lambda *_a: [guidance])
    with pytest.raises(session_service.SessionValidationError, match="缺少原始受理记录"):
        accepted.recovered_prompt_config_reference(session_service, "session-a", "old-turn")


def test_worker_uses_accepted_body_and_profile_but_live_permissions(prompt_environment, monkeypatch, tmp_path):
    state = prompt_environment
    reference = _capture(state)
    state["body"] = "accepted prompt B"
    state["agent"]["personaProfile"] = {"identity": "persona B"}
    state["agent"]["toolPolicy"] = {"allowedTools": []}
    seen = {}
    monkeypatch.setattr(session_service, "_is_session_turn_current", lambda *_a: True)
    monkeypatch.setattr(session_service, "_get_session_turn_control", lambda *_a: SimpleNamespace(turn_id="turn-a"))
    monkeypatch.setattr(session_service, "_ensure_session_workspace", lambda *_a: tmp_path)
    monkeypatch.setattr(session_service, "_sync_agent_directory_project_root", lambda: None)
    monkeypatch.setattr(worker, "_abort_session_turn_for_stop", lambda **_k: False)
    monkeypatch.setattr(session_service, "_ensure_session_agent_prompt_snapshot", lambda *_a, **_k: pytest.fail("accepted turns cannot reread live prompt"))
    monkeypatch.setattr(session_service, "_render_agent_prompt_snapshot_block", lambda prompt: seen.update(prompt=prompt) or prompt["content"])
    monkeypatch.setattr(session_service, "_normalize_message_attachments", lambda *_a: [])
    monkeypatch.setattr(session_service, "_lightweight_chat_payload_decision", lambda *_a, **_k: (False, "test"))

    class ReachedContext(RuntimeError):
        pass

    def build_context(_agent_id, **kwargs):
        seen.update(kwargs)
        raise ReachedContext

    monkeypatch.setattr(session_service, "build_agent_context", build_context)
    with pytest.raises(ReachedContext):
        worker._run_session_turn_impl({"session_id": "session-a", "turn_id": "turn-a", "agent_id": "agent-a",
            "accepted_prompt_config_ref": reference, "accepted_prompt_submission_id": "submission-a"})
    assert seen["prompt"]["content"] == "accepted prompt A"
    assert seen["agent_snapshot"]["personaProfile"] == {"identity": "persona A"}
    assert seen["agent_snapshot"]["toolPolicy"] == {"allowedTools": []}
    assert seen["include_prompt_template_context"] is False


def test_real_submit_journals_only_private_reference_and_worker_context_keeps_old_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service.prompt_template_service, "PROJECT_ROOT", tmp_path)
    _seed_chat_state(tmp_path)
    agent = _bind_seeded_submittable_agent(tmp_path)
    scheduled = []
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled.append(context))
    try:
        result = submit.submit_session_message("session-live", "new accepted prompt test", client_submission_id="accepted-new", lightweight_response=True)
        assert result["accepted"] is True
        context = scheduled[0]
        reference = context["accepted_prompt_config_ref"]
        bundle = accepted.load_accepted_prompt_config(session_service, "session-live", reference,
            agent_id=agent["agentId"], submission_id="accepted-new")
        assert bundle["promptSnapshot"]["content"]
        assert context["message_metadata"]["acceptedPromptConfig"] == reference
        assert "promptSnapshot" not in json.dumps(context["message_metadata"])
        replay = submit.submit_session_message("session-live", "new accepted prompt test", client_submission_id="accepted-new", lightweight_response=True)
        assert replay["accepted"] is True and len(scheduled) == 1
        session_service.prompt_template_service.update_prompt_template(agent["promptTemplateId"],
            source_path="", content="new body B for the same template")
        _reset_seeded_session_runtime("session-live")
        second = submit.submit_session_message("session-live", "next accepted submission", client_submission_id="accepted-next", lightweight_response=True)
        assert second["accepted"] is True and len(scheduled) == 2
        new_reference = scheduled[1]["accepted_prompt_config_ref"]
        new_bundle = accepted.load_accepted_prompt_config(session_service, "session-live", new_reference,
            agent_id=agent["agentId"], submission_id="accepted-next")
        assert "new body B for the same template" in new_bundle["promptSnapshot"]["content"]
        old_bundle = accepted.load_accepted_prompt_config(session_service, "session-live", reference,
            agent_id=agent["agentId"], submission_id="accepted-new")
        assert old_bundle == bundle
    finally:
        _reset_seeded_session_runtime("session-live")


def test_private_evidence_inherits_existing_session_purge_and_restore(tmp_path, monkeypatch):
    from tests.test_agent_archive_session_lifecycle import _create_agent_with_child_session
    from core.web.services import agent_directory_service

    direct, _child = _create_agent_with_child_session(tmp_path, monkeypatch)
    session_id, agent_id = direct["id"], direct["agentId"]
    conversation = session_service.load_session_chat_state(tmp_path, session_id)
    reference = accepted.capture_accepted_prompt_config(session_service, session_id, conversation, submission_id="purge-evidence")
    path = accepted._path(session_service, session_id, reference["ref"])
    assert path.is_file()
    agent_directory_service.archive_agent_instance(agent_id, repair_mode_bindings=False)
    staged = session_service.stage_agent_session_purge(agent_id, direct_session_id=session_id)
    assert not path.exists()
    with pytest.raises(session_service.SessionValidationError):
        accepted.load_accepted_prompt_config(session_service, session_id, reference, agent_id=agent_id, submission_id="purge-evidence")
    session_service.restore_staged_agent_session_purge(staged["restoreToken"])
    restored = accepted.load_accepted_prompt_config(session_service, session_id, reference, agent_id=agent_id, submission_id="purge-evidence")
    assert restored["submissionId"] == "purge-evidence"
    staged = session_service.stage_agent_session_purge(agent_id, direct_session_id=session_id)
    summary = session_service.commit_staged_agent_session_purge(staged["restoreToken"])
    assert not summary["cleanupPending"] and not path.exists()


def test_restart_after_guidance_and_prompt_edit_keeps_original_admitted_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service.prompt_template_service, "PROJECT_ROOT", tmp_path)
    _seed_chat_state(tmp_path)
    agent = _bind_seeded_submittable_agent(tmp_path)
    scheduled = []
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled.append(context))
    try:
        submit.submit_session_message("session-live", "original request A", client_submission_id="original-A", lightweight_response=True)
        original = scheduled[0]
        reference = original["accepted_prompt_config_ref"]
        before = accepted.load_accepted_prompt_config(session_service, "session-live", reference,
            agent_id=agent["agentId"], submission_id="original-A")
        submit.submit_session_guidance("session-live", "same-turn guidance", mode="safe")
        events = session_service._load_session_conversation_events_cached("session-live")
        latest_user = next(event for event in reversed(events) if event.event_type == session_service.EVENT_USER_MESSAGE)
        assert latest_user.turn_id == original["turn_id"]
        assert latest_user.payload["metadata"]["kind"] == "user_guidance"
        session_service.prompt_template_service.update_prompt_template(agent["promptTemplateId"],
            source_path="", content="edited prompt B after guidance")
        _reset_seeded_session_runtime("session-live")
        submit.submit_session_message("session-live", "original request A", client_submission_id="resume-A",
            message_source="hot_restart_resume", turn_mode="hot_restart_resume", lightweight_response=True,
            message_metadata={"kind": "hot_restart_resume", "recoveredTurnId": original["turn_id"]})
        assert len(scheduled) == 2
        resumed = scheduled[1]
        assert resumed["accepted_prompt_config_ref"] == reference
        assert resumed["accepted_prompt_submission_id"] == "original-A"
        after = accepted.load_accepted_prompt_config(session_service, "session-live", resumed["accepted_prompt_config_ref"],
            agent_id=agent["agentId"], submission_id=resumed["accepted_prompt_submission_id"])
        assert after == before
        assert "edited prompt B after guidance" not in after["promptSnapshot"]["content"]
    finally:
        _reset_seeded_session_runtime("session-live")
