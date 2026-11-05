#!/usr/bin/env python3
"""Opt-in real-model acceptance of one isolated, cross-turn Agent cleanup.

Run from its task worktree. Source config is read only; native prompts, journals
and tool results stay in the private fixture. Export only the bounded summary.
No approval cards are accepted by this driver and no management write is replayed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import secrets
import sys
import time

SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT))
sys.dont_write_bytecode = True

from scripts import acceptance_local_assistant_development as base
from scripts.assistant_acceptance_support import AssistantAcceptanceFixture, tool_calls

require = base.require
AcceptanceFailure = base.AcceptanceFailure
TERMINAL_EVENTS = {"turn_completed", "turn_failed", "turn_interrupted"}
TOOLS = {"personal_assistant_action_tool", "personal_assistant_manage_tool"}
WRITES = {"agent_archive", "agent_purge", "authorization_upgrade"}
READS = {"index", "describe", "projects", "agents", "agent_list", "agent_get",
         "agent_purge_preview", "authorization_status", "management_receipt", "management_requests"}
MAX_TOOL_CALLS = 40
MAX_MANAGEMENT_CALLS = 10
CONFIRMATION = re.compile(
    r"要不要|是否(?:确认|继续|删除|清理|归档)|请(?:你)?(?:再(?:次)?)?确认|确认后(?:再|我)|"
    r"(?:需要|希望|想让)我[^。！!\n]{0,24}[吗么？?]|"
    r"要我(?:现在)?[^。！!\n]{0,24}[吗么？?]|"
    r"(?:shall I|should I|do you want|would you like)[^.\n]{0,60}(?:delete|purge|archive|continue|proceed)|"
    r"please confirm", re.IGNORECASE)


def _actions(events: list[dict]) -> list[dict]:
    rows = []
    for call in tool_calls(events):
        if call["callName"] in TOOLS:
            args = call["args"]
            rows.append({**call, "action": args.get("action", "index"),
                         "parameters": base.object_value(args.get("arguments_json") or args.get("parameters"))})
    return rows


def _check_scope(events: list[dict], project_id: str, agent_id: str, *, read_only: bool) -> None:
    # Native streaming emits a name-only start before the same call's complete
    # arguments. Count the native identity once and retain complete arguments
    # even if another placeholder follows; never interpret a placeholder as index.
    starts: dict[tuple[str, str, str], dict] = {}
    for event in events:
        if event.get("eventType") != "tool_call_started":
            continue
        payload = event.get("payload") or {}
        call = payload.get("toolCall") or payload
        call_id = str(event.get("toolCallId") or call.get("id") or call.get("toolCallId") or call.get("callId") or "")
        key = (str(event.get("sessionId") or ""), str(event.get("turnId") or ""), call_id)
        require(all(key), "management_tool_call_identity_missing")
        previous = starts.setdefault(key, {"name": "", "args": None})
        name = call.get("name") or call.get("toolName") or previous["name"]
        if name:
            require(not previous["name"] or previous["name"] == name, "management_tool_call_identity_changed")
            previous["name"] = name
        args = base.object_value(call.get("arguments") or call.get("args"))
        if isinstance(args.get("action"), str) and args["action"]:
            previous["args"] = args
    require(len(starts) <= MAX_TOOL_CALLS, "management_tool_call_budget_exceeded")
    complete_turn = any(event.get("eventType") == "turn_completed" for event in events)
    management = sum(call["name"] == "personal_assistant_manage_tool" for call in starts.values())
    require(management <= MAX_MANAGEMENT_CALLS, "management_write_budget_exceeded")
    for call in starts.values():
        if call["args"] is None:
            require(not complete_turn, "management_tool_arguments_incomplete")
            continue
        name, args = call["name"], call["args"]
        require(name in TOOLS, "unexpected_tool_outside_management_scene")
        action = args["action"]
        parameters = base.object_value(args.get("arguments_json") or args.get("parameters"))
        governed = name == "personal_assistant_manage_tool"
        require(action in (WRITES if governed else READS), "unexpected_management_action")
        require(not (read_only and governed), "read_only_turn_performed_management_write")
        require(parameters.get("project_id", project_id) == project_id, "management_project_scope_changed")
        require(parameters.get("agent_id", agent_id) == agent_id, "management_agent_scope_changed")
        if action == "authorization_upgrade":
            scopes = parameters.get("add_scopes")
            require(isinstance(scopes, list) and scopes and set(scopes) <= {"agents:purge", "agents:directory:read"},
                    "management_scope_upgrade_too_broad")
            require(isinstance(parameters.get("expected_scopes"), list), "management_expected_scopes_missing")
    # Completed results are bound to their real turn/call by the shared helper.
    # A pre-admission SCOPE_DENIED permits only the same request ID after upgrade.
    previous: dict[str, dict] = {}
    for row in _actions(events):
        if row["action"] not in {"agent_archive", "agent_purge"}:
            continue
        old = previous.get(row["action"])
        if old:
            require(old["result"].get("code") == "SCOPE_DENIED"
                    and old["parameters"].get("request_id") == row["parameters"].get("request_id"),
                    "management_write_replayed_or_request_id_changed")
        previous[row["action"]] = row


def _wait_turn(fixture: AssistantAcceptanceFixture, receipt: dict, deadline: float,
               agent_id: str, *, read_only: bool) -> list[dict]:
    turn_id = receipt.get("turnId")
    require(isinstance(turn_id, str) and turn_id, "assistant_turn_receipt_missing")
    while time.monotonic() < deadline:
        require(fixture.host_process is not None and fixture.host_process.poll() is None, "assistant_host_exited")
        fixture.assert_no_approvals()
        events = [event for event in fixture.assistant_events() if event.get("turnId") == turn_id]
        _check_scope(events, fixture.primary_project_id, agent_id, read_only=read_only)
        ends = [event for event in events if event.get("eventType") in TERMINAL_EVENTS]
        if ends:
            require(len(ends) == 1 and ends[0].get("eventType") == "turn_completed", "assistant_turn_not_completed")
            require(sum(event.get("eventType") == "user_message" for event in events) == 1
                    and sum(event.get("eventType") == "turn_started" for event in events) == 1,
                    "assistant_turn_admission_not_unique")
            answer = base.final_answer(events)
            require(isinstance(answer, str) and 0 < len(answer) <= 16000, "assistant_answer_missing_or_unbounded")
            require(CONFIRMATION.search(answer) is None, "redundant_oral_confirmation")
            return events
        time.sleep(1)
    raise AcceptanceFailure("management_dialogue_timeout")


def _legacy_registry(fixture: AssistantAcceptanceFixture, agent_id: str) -> Path:
    """Change only the fixture-created row, under its backend's data override."""
    backend = fixture.backends[fixture.primary_project_id]
    data = fixture.runtime_home / backend.instance_id / "data"
    require(base.inside(data, fixture.home), "legacy_fixture_data_not_isolated")
    with base.environment({**fixture.env, "VIBELUTION_DATA_HOME": str(data)}):
        from vibelution_storage import resolve_project_workspace_home
        path = resolve_project_workspace_home(backend.root) / "agents" / "agents.json"
    require(base.inside(path, data) and path.is_file() and not path.is_symlink(), "legacy_registry_not_isolated")
    state = base.read_json(path)
    agents = state.get("agents")
    require(isinstance(agents, list) and len(agents) <= 10000, "legacy_registry_invalid")
    rows = [row for row in agents if isinstance(row, dict) and row.get("agentId") == agent_id]
    require(len(rows) == 1 and rows[0].get("status") == "active", "legacy_fixture_agent_missing")
    row = rows[0]
    require(isinstance(row.get("metadata"), dict) and row["metadata"].get("acceptanceGeneration"),
            "legacy_fixture_agent_ownership_missing")
    row["roleKey"] = ""
    row["metadata"].update(conversationIndexKind="personal_agent", conversationIndexVisibility="user_visible")
    # No backend work or assistant turn has started against this ordinary row.
    # Its existing configRevision, creation marker and every other row remain intact.
    base.private_json(path, state)
    return path


def _authorize_purge_before_host(fixture: AssistantAcceptanceFixture) -> dict:
    """Operator-authorized fixture setup through the original native SDK grant.

    Acquire the exact host-owner lock before touching its credential ledger;
    release it before start_host. This setup neither accepts approval cards nor
    changes the model-facing approval policy.
    """
    require(fixture.host_process is None and base.inside(fixture.profile, fixture.home),
            "authorization_setup_requires_unstarted_isolated_host")

    async def authorize() -> None:
        from core.assistant_runtime.dispatch import DispatchService

        project_id = fixture.primary_project_id
        dispatch = DispatchService(fixture.profile, {project_id: fixture.backends[project_id].root})
        before = await dispatch.management.authorization_status(project_id)
        scopes = before.get("scopes")
        require(isinstance(scopes, list) and "agents:purge" not in scopes,
                "authorization_setup_expected_fresh_subject")
        result = await dispatch.management.invoke(project_id, action="authorization_upgrade",
            request_id="management-acceptance-purge-setup",
            parameters={"expected_scopes": scopes, "add_scopes": ["agents:purge"]})
        proof = result.get("authorization") or {}
        require(result.get("status") == "completed" and result.get("verified") is True
                and proof.get("subjectId") == before.get("subjectId")
                and proof.get("addedScopes") == ["agents:purge"],
                "authorization_setup_native_receipt_unconfirmed")
        after = await dispatch.management.authorization_status(project_id)
        require(after.get("subjectId") == before.get("subjectId")
                and after.get("binding") == before.get("binding")
                and after.get("scopes") == sorted([*scopes, "agents:purge"]),
                "authorization_setup_subject_or_scopes_changed")

    with base.environment(fixture.env):
        import anyio
        from core.infrastructure.file_lock import cross_process_file_lock

        with cross_process_file_lock(fixture.profile / "host-owner", timeout=0):
            anyio.run(authorize)
    return {"status": "passed", "addedScopes": ["agents:purge"], "sameSubject": True,
            "hostWasStopped": True, "countsAsModelApproval": False}


def run_case(fixture: AssistantAcceptanceFixture, evidence: dict, timeout: float = 600) -> None:
    evidence["stage"] = "starting_backend"
    fixture.start_backend()
    evidence["stage"] = "creating_target"
    agent_id = fixture.create_agent("Management acceptance temporary target")
    evidence["stage"] = "preparing_legacy"
    registry = _legacy_registry(fixture, agent_id)
    evidence["stage"] = "authorizing_fixture_purge"
    evidence["authorizationSetup"] = _authorize_purge_before_host(fixture)
    evidence["stage"] = "starting_host"
    fixture.start_host()
    evidence["stage"] = "configuring_permission"
    identity = fixture.native("/api/assistant")
    permission = (identity.get("settings") or {}).get("managementPermission")
    require(isinstance(permission, dict) and type(permission.get("revision")) is int,
            "management_permission_revision_missing")
    configured = fixture.native("/api/assistant/management-permission", {
        "preset": "full_access", "expectedRevision": permission["revision"]})
    require(configured.get("preset") == "full_access", "full_access_configuration_not_verified")
    fixture.assert_no_approvals()
    evidence.update(legacyEmptyRole=True, managementPreset="full_access", targetCount=1,
                    targetIdSha256=hashlib.sha256(agent_id.encode()).hexdigest())
    deadline = time.monotonic() + timeout
    evidence["stage"] = "reading_eligibility"
    first = fixture.send(
        f"这是隔离验收。只清理项目project_id={fixture.primary_project_id}中的一个临时对象agent_id={agent_id}。"
        "我已授权把这个对象归档后永久删除，包含绑定会话、私有工作区及原生引用的不可恢复清理，"
        "归档和永久删除属于同一清理目标，后续不再口头确认，不扩大到其他对象或项目。"
        "先只读确认这个对象的归档资格并简短汇报；这一轮不要归档、删除或修改权限，等我说继续。"
        "能力和参数以当前工具目录为准，不用旧记忆判断，也不要让我代填工具参数。")
    initial = _wait_turn(fixture, first, deadline, agent_id, read_only=True)
    eligibility = [row for row in _actions(initial) if row["action"] == "agent_get"
        and row["parameters"].get("agent_id") == agent_id
        and (row["result"].get("agent") or {}).get("agentId") == agent_id
        and (row["result"].get("archiveEligibility") or {}).get("eligible") is True]
    require(bool(eligibility), "real_agent_get_eligible_not_observed")
    evidence["eligibility"] = {"status": "passed", "eligible": True,
                               "observedCallCount": len(eligibility)}
    require(next(row for row in base.read_json(registry)["agents"] if row.get("agentId") == agent_id)
            .get("status") == "active", "read_only_turn_changed_target")
    evidence["stage"] = "continuing_cleanup"
    second = fixture.send("继续")
    require(second.get("turnId") != first.get("turnId"), "continuation_turn_not_distinct")
    continued = _wait_turn(fixture, second, deadline, agent_id, read_only=False)
    calls = _actions(continued)
    proofs = {}
    for action, field in (("agent_archive", "agent"), ("agent_purge", "purge")):
        matches = [row for row in calls if row["action"] == action
                   and row["callName"] == "personal_assistant_manage_tool"
                   and row["parameters"].get("agent_id") == agent_id
                   and row["result"].get("status") == "completed" and row["result"].get("verified") is True
                   and (row["result"].get(field) or {}).get("agentId") == agent_id]
        # A model may reconcile an unknown via the original read-only receipt.
        for row in calls:
            if (row["action"] == "management_receipt" and row["parameters"].get("action") == action
                    and row["result"].get("status") == "completed" and row["result"].get("verified") is True
                    and (row["result"].get(field) or {}).get("agentId") == agent_id):
                originals = [call for call in calls if call["action"] == action
                    and call["parameters"].get("request_id") == row["parameters"].get("request_id")]
                if originals:
                    matches.append(row)
        require(bool(matches), "real_" + action + "_verified_receipt_missing")
        proofs[action] = matches[-1]
    purge = proofs["agent_purge"]["result"]["purge"]
    require(purge.get("status") == "purged" and type(purge.get("cleanupPending")) is bool,
            "native_purge_cleanup_state_missing")
    evidence["cleanupOperation"] = {"status": "passed", "archiveVerified": True, "purgeVerified": True,
                                   "cleanupPending": purge["cleanupPending"]}
    require(not purge["cleanupPending"], "native_purge_cleanup_pending")
    remaining = base.read_json(registry).get("agents")
    require(isinstance(remaining, list) and not any(row.get("agentId") == agent_id for row in remaining),
            "purged_target_still_in_native_registry")
    fixture.assert_no_approvals()
    evidence.update(status="passed", stage="completed", turnCount=2, pendingApprovalCount=0, redundantConfirmationCount=0,
                    targetAbsent=True, toolCallCount=len(tool_calls(initial + continued)),
                    managementCallCount=sum(row["callName"] == "personal_assistant_manage_tool"
                                            for row in _actions(initial + continued)))


def run(args: argparse.Namespace) -> dict:
    source = args.project_root.resolve()
    require(source == SOURCE_ROOT and (source / ".git").is_file()
            and base.git(source, "branch", "--show-current").strip().startswith("codex/"),
            "driver_must_use_its_source_task_worktree")
    require(math.isfinite(args.timeout) and 1 <= args.timeout <= 1800, "invalid_acceptance_timeout")
    evidence = {"schemaVersion": 1, "scenario": "assistant-management", "status": "running",
                "startedAt": datetime.now(timezone.utc).isoformat()}
    fixture = AssistantAcceptanceFixture(args.runtime_home, args.source_config, args.model_id,
                                         source=source, readiness_timeout=min(args.timeout, 120))
    try:
        with fixture:
            run_case(fixture, evidence, args.timeout)
    except AcceptanceFailure as exc:
        evidence.update(status="failed", failureCode=str(exc))
    except Exception as exc:
        evidence.update(status="failed", failureCode="unexpected_" + type(exc).__name__)
    evidence["cleanup"] = fixture.cleanup
    evidence["configuration"] = fixture.configuration_evidence()
    if not all(fixture.cleanup.values()):
        evidence.update(status="failed", failureCode="runtime_cleanup_unconfirmed")
    evidence["completedAt"] = datetime.now(timezone.utc).isoformat()
    require(len(json.dumps(evidence, ensure_ascii=False)) <= 8192, "summary_limit_exceeded")
    if fixture.record.get("runtimeOwned"):
        base.private_json(fixture.home / "management-summary.json", evidence)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-home", type=Path, required=True)
    parser.add_argument("--source-config", type=Path, required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--project-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()
    try:
        summary = run(args)
    except AcceptanceFailure as exc:
        summary = {"status": "failed", "failureCode": str(exc)}
    except Exception as exc:
        summary = {"status": "failed", "failureCode": "unexpected_" + type(exc).__name__}
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
