"""Fail-closed authority and native-review tests without product runtime state."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import threading
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from core.runtime_manager.work_run_store import WorkRunStore
from core.web.services import self_evolution_local_integration as local


SHA = "a" * 40
BASE = "b" * 40


class NativeReview:
    def __init__(self):
        self.created = []
        self.submitted = []
        self.stopped = []
        self.metadata = {"source": local.REVIEW_SOURCE, "externalTaskId": "local-run", "runtimeRevision": SHA}
        self.events = [SimpleNamespace(event_type="user_message", turn_id="review-turn",
                                       correlation_id=f"{local.REVIEW_SOURCE}:local-run:{SHA}",
                                       payload={"source": local.REVIEW_SOURCE}),
                       SimpleNamespace(event_type="tool_result", turn_id="review-turn", session_id="review-session",
                                       source="session_ui_capture", status="done", tool_call_id="read-call",
                                       payload={"toolCall": {"name": "grep_search_tool", "status": "done",
                                                             "callId": "read-call", "result": "matched evidence", "error": ""}})]
        self.detail = {"id": "review-session", "agentId": "reviewer", "conversationIndexKind": "hidden"}
        self.completion = {
            "sessionId": "review-session", "turnId": "review-turn", "terminal": True,
            "terminalStatus": "completed", "completionSource": "turn_journal",
            "completionRecovered": False, "assistantTurnId": "review-turn",
            "assistantMessageFound": True,
            "assistantText": json.dumps({"verdict": "passed", "candidateCommit": SHA,
                                         "evidenceRefs": [f"git:{SHA}:src/example.py", "manifest:checked"]}),
        }

    def create_chat_session(self, **kwargs):
        self.created.append(kwargs)
        return deepcopy(self.detail)

    def submit_session_message(self, session_id, content, **kwargs):
        self.submitted.append({"session_id": session_id, "content": content, **kwargs})
        return {"startedTurnId": "review-turn"}

    def get_session_detail(self, session_id, **kwargs):
        return deepcopy(self.detail)

    def get_session_turn_completion_snapshot(self, session_id, turn_id):
        return deepcopy(self.completion)

    def load_session_chat_state(self, project_root, session_id):
        return {"metadata": deepcopy(self.metadata)}

    def load_session_conversation_events_snapshot(self, session_id):
        return deepcopy(self.events)

    def request_stop_session_turn(self, session_id, **kwargs):
        self.stopped.append({"sessionId": session_id, **kwargs})


@pytest.fixture
def harness(tmp_path, monkeypatch):
    now = [datetime(2026, 10, 18, tzinfo=timezone.utc)]
    bindings = {role: {"agentId": role, "role": role} for role in local._ROLES}
    agents = {role: {"agentId": role, "status": "active", "permissionPreset": "request_approval",
                     "resolvedToolPolicy": {"policyId": f"policy-{role}", "allowedTools": ["grep_search_tool"]},
                     "configRevision": 1}
              for role in local._ROLES}
    team = {"teamId": "existing-team", "status": "active", "members": [
        {"agentId": "executor"}, {"agentId": "reviewer"},
    ]}
    native = NativeReview()
    prepare_calls = []
    scoped_policy = {"policyId": "independent-review-policy", "allowedTools": ["grep_search_tool"]}
    scoped_policies = {}
    scoped_policy_calls = []

    def resolve_scoped_policy(agent_id, *, session_id, turn_id):
        scoped_policy_calls.append((agent_id, session_id, turn_id))
        return deepcopy(scoped_policies.get((session_id, turn_id), scoped_policy))

    def prepare(**kwargs):
        prepare_calls.append(kwargs)
        return {"headCommit": SHA, "variantId": "frozen-variant",
                "changedFiles": deepcopy(kwargs["changed_files"]),
                "validationManifestPath": str(tmp_path / "validation-manifest.json")}

    store = WorkRunStore(root=tmp_path / "runs")
    adapter = local.AuthorizedLocalIntegration(
        store=store, project_root=tmp_path, load_bindings=lambda: deepcopy(bindings),
        native=native, prepare_candidate=prepare, get_agent=lambda agent_id: deepcopy(agents.get(agent_id)),
        get_team=lambda team_id: deepcopy(team) if team_id == team["teamId"] else None,
        resolve_scoped_policy=resolve_scoped_policy,
        now=lambda: now[0], review_timeout_seconds=0,
    )
    operator = SimpleNamespace(operator_id="verified-operator", roles=("operator",))
    monkeypatch.setattr(local, "current_server_operator", lambda: operator)
    snapshot = {
        "runId": "local-run", "status": "running", "phase": "independent_review",
        "request": {"localIntegration": {"acknowledge": True, "allowedFiles": ["src/example.py"],
                                         "teamId": "existing-team", "validForSeconds": 600}},
        "candidate": {"summary": "Untrusted executor says everything passed.",
                      "headCommit": BASE, "baseCommit": BASE, "variantId": "dirty-variant",
                      "branch": "codex/candidate", "worktreePath": str(tmp_path / "candidate"),
                      "changedFiles": [{"path": "src/example.py", "changeType": "modified"}],
                      "verification": [{"status": "passed"}]},
    }

    def save():
        return store.persist_snapshot(local.RUN_KIND, snapshot, active_run_id="local-run")

    def authorize():
        snapshot["localIntegrationAuthorization"] = adapter.authorize(snapshot)
        save()
        return deepcopy(snapshot)

    return SimpleNamespace(adapter=adapter, store=store, snapshot=snapshot, native=native,
                           bindings=bindings, agents=agents, team=team, now=now,
                           scoped_policy=scoped_policy, scoped_policies=scoped_policies,
                           scoped_policy_calls=scoped_policy_calls,
                           prepare_calls=prepare_calls, save=save, authorize=authorize)


@pytest.mark.parametrize("patch", [
    {"acknowledge": False}, {"acknowledge": "true"}, {"validForSeconds": True},
    {"validForSeconds": "600"}, {"validForSeconds": 59}, {"validForSeconds": 3601},
    {"allowedFiles": [123]}, {"allowedFiles": ["src/*.py"]},
    {"allowedFiles": ["src/[a].py"]}, {"allowedFiles": ["src/../example.py"]},
    {"allowedFiles": ["src/./example.py"]}, {"allowedFiles": ["src/"]},
    {"allowedFiles": ["C:/outside.py"]}, {"allowedFiles": [".env"]},
    {"allowedFiles": ["config/config.py"]}, {"teamId": " "},
    {"operatorId": "forged"}, {"actorType": "user"},
])
def test_request_is_strict_and_exact(harness, patch):
    request = {**harness.snapshot["request"]["localIntegration"], **patch}
    with pytest.raises((ValidationError, RuntimeError)):
        local.normalize_request(request)


def test_authorization_uses_verified_operator_and_snapshot_only(harness):
    context = harness.authorize()
    grant = context["localIntegrationAuthorization"]
    assert grant["operatorId"] == "verified-operator"
    assert grant["runId"] == context["runId"]
    assert grant["revoked"] is False
    assert grant["expiresAt"] == (harness.now[0] + timedelta(seconds=600)).isoformat()
    assert len(grant["principals"]) == 3
    assert "actorType" not in grant
    assert harness.store.load_snapshot(local.RUN_KIND, "local-run")["localIntegrationAuthorization"] == grant
    assert harness.prepare_calls == []
    assert harness.native.created == []


def test_authorization_accepts_real_canonical_agents_with_read_only_reviewer(harness, tmp_path, monkeypatch):
    from core.web.services import agent_directory_service
    from tests.test_agent_config_workspace_service import _use_tmp_project_root

    _use_tmp_project_root(tmp_path, monkeypatch)
    ids = {}
    for role in local._ROLES:
        agent = agent_directory_service.create_agent_instance(display_name=f"Existing {role}")
        ids[role] = agent["agentId"]
        agent_directory_service.update_agent_instance(agent["agentId"], tool_policy={
            "allowedTools": ["grep_search_tool"], "preferredTools": ["grep_search_tool"]})
        harness.bindings[role]["agentId"] = agent["agentId"]
    harness.team["members"] = [{"agentId": ids[role]} for role in ("executor", "reviewer")]
    harness.adapter._get_agent = local._get_agent
    grant = harness.authorize()["localIntegrationAuthorization"]
    assert grant["principals"]["reviewer"]["agentId"] == ids["reviewer"]
    projected = local._get_agent(ids["reviewer"])
    assert projected["permissionPreset"] == "request_approval"
    with agent_directory_service.active_agent_runtime(ids["reviewer"], runtime_tool_grants=[]) as runtime:
        assert "apply_patch_tool" not in runtime["toolPolicy"]["allowedTools"]


@pytest.mark.parametrize("operator", [None, SimpleNamespace(operator_id="body-user", roles=()),
                                       SimpleNamespace(operator_id="", roles=("operator",))])
def test_body_identity_cannot_supply_authority(harness, monkeypatch, operator):
    monkeypatch.setattr(local, "current_server_operator", lambda: operator)
    harness.snapshot["operatorId"] = "forged-admin"
    with pytest.raises(PermissionError, match="command_forbidden"):
        harness.adapter.authorize(harness.snapshot)


def test_existing_directory_is_not_exact_file_authorization(harness):
    (harness.adapter.project_root / "src").mkdir()
    harness.snapshot["request"]["localIntegration"]["allowedFiles"] = ["src"]
    with pytest.raises(local.LocalIntegrationError, match="exact files"):
        harness.adapter.authorize(harness.snapshot)


@pytest.mark.parametrize("mutation", ["same_agent", "missing_agent", "missing_member", "archived_team"])
def test_authorization_requires_independent_existing_agents_and_team(harness, mutation):
    if mutation == "same_agent":
        harness.bindings["reviewer"]["agentId"] = "executor"
    elif mutation == "missing_agent":
        harness.agents.pop("reviewer")
    elif mutation == "missing_member":
        harness.team["members"] = [{"agentId": "executor"}]
    else:
        harness.team["status"] = "archived"
    with pytest.raises(local.LocalIntegrationError):
        harness.adapter.authorize(harness.snapshot)


def test_review_is_hidden_exact_sha_and_has_no_runtime_grants(harness):
    context = harness.authorize()
    reviewed = harness.adapter.review(context)
    assert reviewed["candidate"]["headCommit"] == SHA
    assert reviewed["candidate"]["baseCommit"] == BASE
    assert reviewed["independentReview"] == {
        "candidateCommit": SHA, "reviewerAgentId": "reviewer", "sessionId": "review-session",
        "turnId": "review-turn", "verdict": "passed",
        "evidenceRefs": [f"git:{SHA}:src/example.py", "manifest:checked"],
        "scopedPolicyDigest": harness.adapter._scoped_policy_digest("reviewer", "review-session", "review-turn"),
    }
    created = harness.native.created[0]
    assert created["agent_id"] == "reviewer"
    assert created["activate"] is False
    assert created["conversation_index_kind"] == "hidden"
    assert created["created_by"] == local.REVIEW_SOURCE
    assert created["session_metadata"]["source"] == local.REVIEW_SOURCE
    assert SHA in created["idempotency_key"]
    submission = harness.native.submitted[0]
    assert submission["client_submission_id"] == created["idempotency_key"]
    assert submission["message_source"] == local.REVIEW_SOURCE
    assert "Untrusted executor says" not in submission["content"]
    assert "runtime_tool_grants" not in submission
    assert "llm_bindings" not in created
    assert "independentReview" not in harness.store.load_snapshot(local.RUN_KIND, "local-run")


def test_review_retry_uses_same_native_idempotency_keys(harness):
    context = harness.authorize()
    assert harness.adapter.review(context) == harness.adapter.review(context)
    assert harness.native.created[0]["idempotency_key"] == harness.native.created[1]["idempotency_key"]
    assert harness.native.submitted[0]["client_submission_id"] == harness.native.submitted[1]["client_submission_id"]


def test_scoped_policy_resolver_forwards_exact_native_scope(monkeypatch):
    from core.web.services import agent_directory_service

    seen = []
    expected = {"policyId": "resolved", "allowedTools": []}

    def resolve(agent_id, *, session_id, turn_id):
        seen.append((agent_id, session_id, turn_id))
        return expected

    monkeypatch.setattr(agent_directory_service, "resolve_tool_policy_for_agent", resolve)
    assert local._resolve_scoped_policy("reviewer", session_id="review-session", turn_id="review-turn") == expected
    assert seen == [("reviewer", "review-session", "review-turn")]


@pytest.mark.parametrize("scope", ["session", "turn"])
def test_scoped_temporary_write_grant_prevents_review_approval(harness, scope):
    context = harness.authorize()
    harness.scoped_policies[("review-session", "" if scope == "session" else "review-turn")] = {
        "policyId": "temporary-policy", "allowedTools": ["grep_search_tool", "apply_patch_tool"],
        "temporaryAllowedTools": ["apply_patch_tool"],
    }
    with pytest.raises(local.LocalIntegrationError, match="non-read-only"):
        harness.adapter.review(context)
    assert harness.native.stopped
    assert bool(harness.native.submitted) is (scope == "turn")
    assert "independentReview" not in harness.store.load_snapshot(local.RUN_KIND, "local-run")


def test_session_policy_drift_is_rejected_immediately_before_submission(harness):
    context = harness.authorize()
    resolver = harness.adapter._resolve_scoped_policy
    seen = 0

    def change(agent_id, *, session_id, turn_id):
        nonlocal seen
        seen += 1
        result = resolver(agent_id, session_id=session_id, turn_id=turn_id)
        if seen >= 2:
            result["allowedTools"].append("read_file_tool")
        return result

    harness.adapter._resolve_scoped_policy = change
    with pytest.raises(local.LocalIntegrationError, match="before submission"):
        harness.adapter.review(context)
    assert harness.native.submitted == []


def test_scoped_policy_drift_during_completion_is_rejected(harness):
    context = harness.authorize()
    completion = harness.native.get_session_turn_completion_snapshot

    def change(session_id, turn_id):
        harness.scoped_policy["allowedTools"].append("read_file_tool")
        return completion(session_id, turn_id)

    harness.native.get_session_turn_completion_snapshot = change
    with pytest.raises(local.LocalIntegrationError, match="permissions changed"):
        harness.adapter.review(context)
    assert harness.native.stopped[-1]["expected_turn_id"] == "review-turn"


def test_scoped_policy_change_after_review_blocks_merge(harness):
    context = persist_review(harness)
    assert len(context["independentReview"]["scopedPolicyDigest"]) == 64
    harness.scoped_policy["allowedTools"].append("read_file_tool")
    with pytest.raises(local.LocalIntegrationError, match="permissions changed"):
        with harness.adapter.guard(context):
            pytest.fail("changed scoped policy entered merge")


def tool_event(kind, *, name="grep_search_tool", turn_id="review-turn"):
    payload = {"toolCall": {"name": name}}
    source = "session_ui_capture"
    if kind == "assistant_item_committed":
        payload = {"kind": "tool_call", "sessionId": "review-session", "turnId": turn_id,
                   "toolName": name, "callId": "review-call"}
        source = "canonical_turn_outcome"
    return SimpleNamespace(event_type=kind, turn_id=turn_id, source=source, payload=payload)


@pytest.mark.parametrize("kind", ["tool_call_started", "tool_result", "assistant_item_committed"])
@pytest.mark.parametrize("name", ["apply_patch_tool", "unknown_plugin_tool", "", None])
def test_full_journal_rejects_write_unknown_or_missing_tool_attempt(harness, kind, name):
    context = harness.authorize()
    # No grant is currently visible; the full canonical journal still proves
    # the attempted tool even when a past short-lived grant has expired.
    harness.native.events.append(tool_event(kind, name=name))
    with pytest.raises(local.LocalIntegrationError, match="unknown or non-read-only"):
        harness.adapter.review(context)
    assert harness.native.stopped


@pytest.mark.parametrize("kind", ["cli_task_sent", "cli_task_result", "cli_session_lifecycle"])
def test_review_cli_journal_events_cannot_pass(harness, kind):
    context = harness.authorize()
    harness.native.events.append(tool_event(kind))
    with pytest.raises(local.LocalIntegrationError, match="CLI task"):
        harness.adapter.review(context)


@pytest.mark.parametrize("field,value", [("turnId", "other-turn"), ("sessionId", "other-session"),
                                          ("callId", ""), ("kind", "assistant_message")])
def test_canonical_tool_attempt_requires_exact_identity(harness, field, value):
    context = harness.authorize()
    event = tool_event("assistant_item_committed")
    event.payload[field] = value
    harness.native.events.append(event)
    with pytest.raises(local.LocalIntegrationError, match="canonical turn identity"):
        harness.adapter.review(context)


def test_review_reads_all_exact_turn_tool_events_and_ignores_other_turns(harness):
    context = harness.authorize()
    harness.native.events.extend(tool_event("tool_result") for _ in range(300))
    harness.native.events.append(tool_event("assistant_item_committed"))
    harness.native.events.append(tool_event("tool_result", name="apply_patch_tool", turn_id="other-turn"))
    assert harness.adapter.review(context)["independentReview"]["verdict"] == "passed"
    harness.native.events.append(tool_event("tool_result", name="apply_patch_tool"))
    with pytest.raises(local.LocalIntegrationError, match="non-read-only"):
        harness.adapter.review(context)


def test_journal_attempt_added_during_completion_is_not_lost(harness):
    context = harness.authorize()
    completion = harness.native.get_session_turn_completion_snapshot

    def append_attempt(session_id, turn_id):
        harness.native.events.append(tool_event("tool_call_started", name="apply_patch_tool"))
        return completion(session_id, turn_id)

    harness.native.get_session_turn_completion_snapshot = append_attempt
    with pytest.raises(local.LocalIntegrationError, match="non-read-only"):
        harness.adapter.review(context)


def test_guard_rereads_journal_even_when_scoped_grant_has_expired(harness):
    context = persist_review(harness)
    harness.native.events.append(tool_event("tool_result", name="apply_patch_tool"))
    with pytest.raises(local.LocalIntegrationError, match="non-read-only"):
        with harness.adapter.guard(context):
            pytest.fail("historical write attempt entered merge")


def test_zero_tool_json_passed_is_not_independent_read_evidence(harness):
    context = harness.authorize()
    harness.native.events = [event for event in harness.native.events if event.event_type == "user_message"]
    with pytest.raises(local.LocalIntegrationError, match="successful native read-only"):
        harness.adapter.review(context)
    assert harness.native.stopped


@pytest.mark.parametrize("mutation", ["failed", "blocked", "running", "error", "timed_out", "exit_code",
                                      "semantic_failure", "failure_class", "wrong_source", "wrong_call", "wrong_session"])
def test_unsuccessful_or_unbound_tool_results_do_not_prove_a_read(harness, mutation):
    context = harness.authorize()
    result = harness.native.events[1]
    call = result.payload["toolCall"]
    if mutation in {"failed", "blocked", "running"}:
        result.status = mutation
        call["status"] = mutation
    elif mutation == "error":
        call["error"] = "could not read evidence"
    elif mutation == "timed_out":
        call["timedOut"] = True
    elif mutation == "exit_code":
        call["exitCode"] = 1
    elif mutation == "semantic_failure":
        call["semanticStatus"] = "failed"
    elif mutation == "failure_class":
        call["failureClass"] = "permission_denied"
    elif mutation == "wrong_source":
        result.source = "model_claim"
    elif mutation == "wrong_call":
        result.tool_call_id = "other-call"
    else:
        result.session_id = "other-session"
    with pytest.raises(local.LocalIntegrationError, match="successful native read-only"):
        harness.adapter.review(context)


def test_guard_rejects_disappeared_native_read_evidence(harness):
    context = persist_review(harness)
    harness.native.events = [event for event in harness.native.events if event.event_type == "user_message"]
    with pytest.raises(local.LocalIntegrationError, match="successful native read-only"):
        with harness.adapter.guard(context):
            pytest.fail("missing native read evidence entered merge")


@pytest.mark.parametrize("mutation", ["revoke", "expired", "policy", "binding", "team", "stopped", "restart", "scope"])
def test_live_authority_changes_fail_before_candidate_preparation(harness, mutation):
    context = harness.authorize()
    if mutation == "revoke":
        harness.snapshot["localIntegrationAuthorization"]["revoked"] = True
    elif mutation == "expired":
        harness.now[0] += timedelta(seconds=601)
    elif mutation == "policy":
        harness.agents["reviewer"]["resolvedToolPolicy"]["allowedTools"].append("write_file_tool")
    elif mutation == "binding":
        harness.bindings["reviewer"]["workspacePath"] = "changed"
    elif mutation == "team":
        harness.team["members"].pop()
    elif mutation == "stopped":
        harness.snapshot["status"] = "stopped"
    elif mutation == "restart":
        harness.snapshot["phase"] = "interrupted_for_restart"
    else:
        harness.snapshot["request"]["localIntegration"]["allowedFiles"] = ["src/other.py"]
    harness.save()
    with pytest.raises(local.LocalIntegrationError):
        harness.adapter.review(context)
    assert harness.prepare_calls == []
    assert harness.native.created == []


def test_candidate_outside_exact_authorized_files_is_rejected(harness):
    context = harness.authorize()
    harness.snapshot["candidate"]["changedFiles"].append({"path": "src/extra.py", "changeType": "added"})
    context = harness.save()
    with pytest.raises(local.LocalIntegrationError, match="exceed"):
        harness.adapter.review(context)
    assert harness.prepare_calls == []


@pytest.mark.parametrize("mutation", ["preset", "write_tool", "temporary_write", "allow_all", "missing_allowed", "fake_executable", "unknown"])
def test_reviewer_must_already_have_a_read_only_execution_ceiling(harness, mutation):
    agent = harness.agents["reviewer"]
    policy = agent["resolvedToolPolicy"]
    if mutation == "preset":
        agent["permissionPreset"] = "workspace_write"
    elif mutation == "write_tool":
        policy["allowedTools"].append("apply_patch_tool")
    elif mutation == "temporary_write":
        policy["temporaryAllowedTools"] = ["apply_patch_tool"]
    elif mutation == "allow_all":
        policy["allowAllTools"] = True
    elif mutation == "missing_allowed":
        policy.pop("allowedTools")
    elif mutation == "fake_executable":
        policy["allowedTools"].append("apply_patch_tool")
        policy["executableTools"] = []
    else:
        policy["allowedTools"].append("unknown_plugin_tool")
    with pytest.raises(local.LocalIntegrationError):
        harness.adapter.authorize(harness.snapshot)
    assert harness.native.created == []


def test_reviewer_policy_uses_deny_first_and_explicit_empty_semantics(harness):
    policy = harness.agents["reviewer"]["resolvedToolPolicy"]
    policy["allowedTools"].append("apply_patch_tool")
    policy["blockedTools"] = ["apply_patch_tool"]
    assert harness.adapter.authorize(harness.snapshot)["principals"]["reviewer"]["agentId"] == "reviewer"
    policy["allowedTools"] = []
    policy["blockedTools"] = []
    assert harness.adapter.authorize(harness.snapshot)["principals"]["reviewer"]["agentId"] == "reviewer"


@pytest.mark.parametrize("patch", [
    {"headCommit": "short-sha"}, {"validationManifestPath": ""}, {"variantId": ""},
    {"worktreePath": "another-worktree"}, {"branch": "main"}, {"baseCommit": SHA},
    {"changedFiles": [{"path": "src/extra.py", "changeType": "added"}]},
])
def test_candidate_preparation_cannot_rebind_frozen_scope(harness, patch):
    context = harness.authorize()
    prepare = harness.adapter._prepare
    harness.adapter._prepare = lambda **kwargs: {**prepare(**kwargs), **patch}
    with pytest.raises(local.LocalIntegrationError):
        harness.adapter.review(context)
    assert harness.native.created == []


@pytest.mark.parametrize("patch", [
    {"assistantTurnId": "other-turn"}, {"turnId": "other-turn"},
    {"sessionId": "other-session"}, {"completionSource": "assistant_marker"},
    {"completionSource": "last_turn_status"}, {"completionRecovered": True},
    {"terminalStatus": "failed"}, {"assistantMessageFound": False},
    {"assistantText": "Developer says passed"},
    {"assistantText": json.dumps({"verdict": "passed", "candidateCommit": BASE, "evidenceRefs": ["check"]})},
    {"assistantText": json.dumps({"verdict": "failed", "candidateCommit": SHA, "evidenceRefs": ["check"]})},
    {"assistantText": json.dumps({"verdict": "passed", "candidateCommit": SHA, "evidenceRefs": []})},
    {"assistantText": json.dumps({"verdict": "passed", "candidateCommit": SHA, "evidenceRefs": ["x" * 501]})},
])
def test_review_requires_canonical_exact_assistant_verdict(harness, patch):
    context = harness.authorize()
    harness.native.completion.update(patch)
    with pytest.raises(local.LocalIntegrationError):
        harness.adapter.review(context)
    assert harness.native.stopped
    assert harness.native.stopped[-1]["expected_turn_id"] == "review-turn"


def test_review_rejects_wrong_reviewer_session_identity(harness):
    context = harness.authorize()
    harness.native.detail["agentId"] = "executor"
    with pytest.raises(local.LocalIntegrationError, match="identity"):
        harness.adapter.review(context)
    assert harness.native.submitted == []
    assert harness.native.stopped


@pytest.mark.parametrize("mutation", ["source", "run", "sha", "correlation", "user_source", "missing_event"])
def test_review_cannot_reuse_unrelated_session_or_user_submission(harness, mutation):
    context = harness.authorize()
    if mutation == "source":
        harness.native.metadata["source"] = "raw"
    elif mutation == "run":
        harness.native.metadata["externalTaskId"] = "other-run"
    elif mutation == "sha":
        harness.native.metadata["runtimeRevision"] = BASE
    elif mutation == "correlation":
        harness.native.events[0].correlation_id = "user-submitted"
    elif mutation == "user_source":
        harness.native.events[0].payload["source"] = "raw"
    else:
        harness.native.events = []
    with pytest.raises(local.LocalIntegrationError):
        harness.adapter.review(context)
    assert harness.native.stopped


def test_review_timeout_stops_native_turn_and_never_approves(harness):
    context = harness.authorize()
    harness.native.completion["terminal"] = False
    with pytest.raises(local.LocalIntegrationError, match="timed out"):
        harness.adapter.review(context)
    assert harness.native.stopped[-1]["expected_turn_id"] == "review-turn"


def test_poll_rechecks_revocation_and_stops_native_turn(harness):
    context = harness.authorize()
    harness.native.completion["terminal"] = False
    harness.adapter._timeout = 10

    def revoke(_delay):
        with local.authorization_lock(harness.store, "local-run"):
            harness.snapshot["localIntegrationAuthorization"]["revoked"] = True
            harness.save()

    harness.adapter._sleep = revoke
    with pytest.raises(local.LocalIntegrationError, match="revoked"):
        harness.adapter.review(context)
    assert harness.native.stopped[-1]["expected_turn_id"] == "review-turn"


def persist_review(harness):
    context = harness.authorize()
    harness.snapshot.update(harness.adapter.review(context))
    harness.snapshot["phase"] = "integrating"
    return harness.save()


def test_merge_guard_rereads_native_authority(harness):
    context = persist_review(harness)
    with harness.adapter.guard(context):
        pass
    harness.native.completion["assistantText"] = json.dumps({
        "verdict": "failed", "candidateCommit": SHA, "evidenceRefs": ["late failure"],
    })
    entered = False
    with pytest.raises(local.LocalIntegrationError):
        with harness.adapter.guard(context):
            entered = True
    assert entered is False


@pytest.mark.parametrize("mutation", ["revoked", "candidate", "receipt", "forged_receipt", "policy", "expired"])
def test_merge_guard_rejects_stale_or_forged_persisted_evidence(harness, mutation):
    context = persist_review(harness)
    if mutation == "revoked":
        harness.snapshot["localIntegrationAuthorization"]["revoked"] = True
    elif mutation == "candidate":
        harness.snapshot["candidate"]["headCommit"] = BASE
    elif mutation == "receipt":
        harness.snapshot["independentReview"]["turnId"] = "forged-turn"
    elif mutation == "forged_receipt":
        harness.snapshot["independentReview"]["turnId"] = "forged-turn"
        context = deepcopy(harness.snapshot)
    elif mutation == "policy":
        harness.agents["executor"]["permissionPreset"] = "full_access"
    else:
        harness.now[0] += timedelta(seconds=601)
    harness.save()
    with pytest.raises(local.LocalIntegrationError):
        with harness.adapter.guard(context):
            pytest.fail("stale authorization entered merge")


def test_guard_serializes_completed_revocation_before_merge(harness):
    context = persist_review(harness)
    with local.authorization_lock(harness.store, "local-run"):
        harness.snapshot["localIntegrationAuthorization"]["revoked"] = True
        harness.save()
    with pytest.raises(local.LocalIntegrationError, match="revoked"):
        with harness.adapter.guard(context):
            pytest.fail("completed revocation must prevent merge")


def test_revoke_waits_until_atomic_merge_guard_releases(harness):
    context = persist_review(harness)
    revoke_started = threading.Event()
    revoke_finished = threading.Event()
    errors = []

    def revoke():
        revoke_started.set()
        try:
            with local.authorization_lock(harness.store, "local-run"):
                harness.snapshot["localIntegrationAuthorization"]["revoked"] = True
                harness.save()
                revoke_finished.set()
        except Exception as exc:
            errors.append(exc)

    with harness.adapter.guard(context):
        worker = threading.Thread(target=revoke)
        worker.start()
        assert revoke_started.wait(2)
        assert not revoke_finished.wait(0.1)
    worker.join(3)
    assert not worker.is_alive()
    assert errors == []
    assert revoke_finished.is_set()
    with pytest.raises(local.LocalIntegrationError, match="revoked"):
        with harness.adapter.guard(context):
            pytest.fail("revoked grant must not enter a second merge")


def test_authorization_lock_creates_only_lock_sidecar(harness):
    run_dir = harness.store.runs_dir(local.RUN_KIND)
    with local.authorization_lock(harness.store, "local-run"):
        assert list(run_dir.glob("*.json")) == []
    assert [path.name for path in run_dir.iterdir()] == ["local-run.local-integration-authorization.lock"]
