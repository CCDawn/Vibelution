"""Read-only supervision of one ordinary Session task's native retry lineage.

Only Journal references and bounded native diagnosis codes leave this module.
Regenerate has request deduplication but no expected-Turn/head CAS: replay is
always left to the user, including after a successful repair.
"""
from __future__ import annotations

import json
import re

from core.agent_plugins.virtual_human_life.storage import VirtualHumanLifeStore
from core.chat.conversation_branches import analyze_conversation_branches, resolve_active_user_node_id
from core.chat.turn_journal import (
    TERMINAL_EVENTS, build_journal_event_tree, model_visible_messages_from_events,
)
from core.web.services.session import journal_bridge
from core.web.services.session.turn_failure_classification import (
    derive_failure_disposition, normalize_disposition,
)
from core.infrastructure import developer_sandbox
from core.runtime_manager.work_run_store import ACTIVE_RUN_IDS_LIMIT

from . import store

_MAX_EVENTS = 30000
_MAX_ATTEMPTS = 120
_MAX_RESUMES = 32
_GUIDANCE = frozenset({"user_guidance", "user_interrupt_guidance"})
_SUCCESS = frozenset({"ready", "completed", "done", "success", "succeeded"})
_HUMAN = frozenset({"waiting_human", "needs_continue", "paused_limit", "paused"})
_UNSETTLED = frozenset({"queued", "running", "stopping"})
_BLOCKED_CODES = frozenset({
    "context_budget_exhausted", "context_length_error", "quota_error", "output_truncated",
    "auth_error", "authentication_error", "authenticationerror", "authorization_error",
    "permission_denied", "permission_error", "permissionerror", "credential_error",
    "credentials_missing", "invalid_api_key", "missing_api_key", "insufficient_quota",
    "approval_rejected", "approval_denied", "approval_required", "human_required",
    "approval_declined", "approval_cancelled", "approval_timeout",
    "user_interrupt", "user_stop", "cancelled", "canceled", "stopped", "stopped_by_user",
    "needs_continue", "paused_limit", "superseded",
})


def _service():
    from core.web.services import session_service

    return session_service


def is_source(record: dict) -> bool:
    steps = (record.get("flow") or {}).get("steps") or []
    return len(steps) == 1 and steps[0].get("kind") == "session"


def _source(record: dict) -> tuple[dict, dict]:
    if not is_source(record) or (record["flow"].get("fields") or []):
        raise store.WorkflowError("Session监督只支持无输入字段的单个原生来源。")
    step = record["flow"]["steps"][0]
    source = step.get("sessionSource") or {}
    if not record.get("teamId") or any(
        not isinstance(source.get(key), str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}", source[key])
        for key in ("sessionId", "turnId", "agentId")
    ):
        raise store.WorkflowError("Session来源需要精确的Team、Session、Turn和Agent引用。")
    return step, source


def _ownership(s, record: dict, source: dict, state: dict | None) -> None:
    roster = store.team(record["teamId"])
    if roster.get("status") == "archived" or source["agentId"] not in {
        item.get("agentId") for item in roster.get("members", [])
        if isinstance(item, dict) and item.get("status") != "archived"
    }:
        raise store.WorkflowError("Session负责人不是当前Team的有效成员。")
    # get_agent() repairs the registry; even load_state() may seed a developer
    # sandbox. Resolve the existing registry with seeding explicitly disabled.
    directory = s.agent_directory_service
    with directory.scoped_project_root(s.PROJECT_ROOT):
        path = directory._workspace_path("agents", "agents.json", intent="state", seed=False)
        payload = json.loads(path.read_text(encoding="utf-8"))
    agents = payload.get("agents") or []
    matches = [agent for agent in agents if isinstance(agent, dict)
               and agent.get("agentId") == source["agentId"]]
    if len(matches) != 1 or matches[0].get("status") == "archived":
        raise store.WorkflowError("Session来源Agent不存在或已归档。")
    agent = matches[0]
    metadata = agent.get("metadata") or {}
    plugin = VirtualHumanLifeStore(s.PROJECT_ROOT, plugin_root_resolver=lambda agent_id:
        developer_sandbox.route_workspace_path(s.PROJECT_ROOT, "agent_directory", "agents", agent_id,
            "plugins", "virtual-human-life", intent="state", seed=False))
    binding = plugin.read_json(source["agentId"], "binding.json")
    if (metadata.get("virtualHumanCompanion") is True or metadata.get("virtualHumanSelfWake") is True
            or metadata.get("lifeStewardForAgentId") or (binding or {}).get("enabled") is True):
        raise store.WorkflowError("普通Session监督不接管Companion会话。")
    if (not isinstance(state, dict) or state.get("archived") is True or state.get("status") == "archived"
            or state.get("read_only") or state.get("readOnly")):
        raise store.WorkflowError("Session来源不存在或已归档。")
    owners = [state[key] for key in ("agent_id", "agentId") if state.get(key)]
    if not owners or any(value != source["agentId"] for value in owners):
        raise store.WorkflowError("Session负责人已经变化。")
    for key in ("conversation_id", "conversationId", "id", "sessionId"):
        if state.get(key) and state[key] != source["sessionId"]:
            raise store.WorkflowError("Session来源身份不匹配。")


class _InvalidLineage(ValueError):
    pass


def _metadata(event) -> dict:
    value = event.payload.get("metadata")
    return value if isinstance(value, dict) else {}


def _is_user(event) -> bool:
    return event.event_type == "user_message" and _metadata(event).get("kind") not in _GUIDANCE


def _lineage(events: list, source: dict) -> tuple[str, list[list[str]], bool]:
    """Return canonical root, selected business groups, and branch-advance fence.

    Alias is a logical-message grouping, not a causal retry graph. Recover the
    actual predecessor from the active prefix *before* each native marker;
    this also covers first-message regenerate, where the shared tree has no
    alias because its fork point is empty.
    """
    if not events or len(events) > _MAX_EVENTS:
        raise _InvalidLineage
    seen_ids = set()
    last_sequence = -1
    users, parents, kinds, terminals = {}, {}, {}, {}
    head_selections = []
    regenerate_count = 0
    for index, event in enumerate(events):
        if (event.session_id != source["sessionId"] or not event.event_id or event.event_id in seen_ids
                or event.sequence <= last_sequence or not isinstance(event.payload, dict)):
            raise _InvalidLineage
        seen_ids.add(event.event_id)
        last_sequence = event.sequence
        if event.event_type in TERMINAL_EVENTS:
            if event.turn_id in terminals:
                raise _InvalidLineage
            terminals[event.turn_id] = event
        if event.event_type == "branch_rebase":
            operation = event.payload.get("operation")
            if operation == "head_select":
                head_selections.append(event.sequence)
            elif operation == "regenerate":
                regenerate_count += 1
                if regenerate_count >= _MAX_ATTEMPTS:
                    raise _InvalidLineage
                if event.source != "session_branch_rebase" or index + 1 >= len(events):
                    raise _InvalidLineage
                prefix = events[:index]
                tree = build_journal_event_tree(prefix)
                active = [tree.events_by_id[key] for key in tree.chain_ids]
                fork = event.payload.get("fromEventId") or event.parent_event_id
                if fork:
                    cut = next((i + 1 for i, item in enumerate(active) if item.event_id == fork), -1)
                    if cut < 0:
                        raise _InvalidLineage
                else:
                    cut = 0
                removed = active[cut:]
                replaced = list(dict.fromkeys(item.turn_id for item in removed if item.turn_id))
                target = next((item for item in removed if _is_user(item)), None)
                child = events[index + 1]
                if (target is None or not replaced or replaced[0] != target.turn_id
                        or event.payload.get("replacedTurnIds") != replaced
                        or child.event_type != "user_message" or child.turn_id != event.turn_id
                        or child.source != "regenerate_session_message"
                        or child.payload.get("source") != "regenerated_user_message"
                        or child.turn_id in parents or child.turn_id == target.turn_id):
                    raise _InvalidLineage
                base = event.payload.get("baseMessageId")
                view = analyze_conversation_branches(prefix)
                logical_target = view.node_id_by_event.get(target.event_id, target.event_id)
                resolved = resolve_active_user_node_id(view, str(base or ""))
                api_ids = {
                    f"{source['sessionId']}-message-{i + 1}"
                    for i, message in enumerate(model_visible_messages_from_events(prefix))
                    if (message.get("metadata") or {}).get("eventId") == target.event_id
                }
                if base not in {target.event_id, logical_target, *api_ids} and resolved != logical_target:
                    raise _InvalidLineage
                # UI regenerate targets the real user request, while startup
                # resume emits system-authored user rows. The replaced attempt
                # ended at its verified resume descendant, not its open origin.
                predecessor = target.turn_id
                for _ in range(_MAX_RESUMES + 1):
                    resumed = next((key for key, value in parents.items()
                                    if value == predecessor and kinds.get(key) == "resume" and key in replaced), None)
                    if resumed is None:
                        break
                    predecessor = resumed
                else:
                    raise _InvalidLineage
                parents[child.turn_id], kinds[child.turn_id] = predecessor, "regenerate"
            elif operation != "edit":
                raise _InvalidLineage
        if not _is_user(event):
            continue
        if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}", event.turn_id)
                or event.turn_id in users):
            raise _InvalidLineage
        if _metadata(event).get("turnId", event.turn_id) != event.turn_id:
            raise _InvalidLineage
        if _metadata(event).get("kind") == "hot_restart_resume" or event.payload.get("source") == "hot_restart_resume":
            metadata = _metadata(event)
            parent = metadata.get("recoveredTurnId")
            if (not parent or parent not in users or parent in terminals or event.turn_id in parents
                    or event.payload.get("source") != "hot_restart_resume"
                    or metadata.get("kind") != "hot_restart_resume"
                    or metadata.get("recoverySource") != "startup_sweep"
                    or event.correlation_id != f"resume:{parent}"
                    or any(value == parent and kinds.get(key) == "resume" for key, value in parents.items())):
                raise _InvalidLineage
            parents[event.turn_id], kinds[event.turn_id] = parent, "resume"
        elif event.source == "regenerate_session_message" and kinds.get(event.turn_id) != "regenerate":
            raise _InvalidLineage
        users[event.turn_id] = event
    anchor = source["turnId"]
    if anchor not in users:
        raise _InvalidLineage

    def ancestors(turn):
        path, seen = [], set()
        while turn:
            if turn in seen or turn not in users or len(path) >= _MAX_ATTEMPTS * (_MAX_RESUMES + 1):
                raise _InvalidLineage
            path.append(turn)
            seen.add(turn)
            turn = parents.get(turn)
        return path[::-1]

    root = ancestors(anchor)[0]
    active_tree = build_journal_event_tree(events)
    current = next((active_tree.events_by_id[key] for key in reversed(active_tree.chain_ids)
                    if _is_user(active_tree.events_by_id[key])), None)
    if current is None:
        raise _InvalidLineage
    path = ancestors(current.turn_id)
    advanced = path[0] != root or anchor not in path or any(seq > users[anchor].sequence for seq in head_selections)
    if advanced:
        path = ancestors(anchor)
    groups = []
    for turn in path:
        if kinds.get(turn) == "resume" and groups:
            groups[-1].append(turn)
            if len(groups[-1]) > _MAX_RESUMES + 1:
                raise _InvalidLineage
        else:
            groups.append([turn])
    if len(groups) > _MAX_ATTEMPTS:
        raise _InvalidLineage
    return root, groups, advanced


def _code(value) -> str:
    return value.lower() if isinstance(value, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,79}", value) else ""


def _failure(terminal) -> tuple[str, bool]:
    payload = terminal.payload
    codes = [_code(payload.get(key)) for key in ("problemCode", "failureCategory", "errorType")]
    code = next((value for value in codes if value), "")
    disposition = normalize_disposition(payload.get("failureDisposition")) or derive_failure_disposition(
        problem_code=payload.get("problemCode"), terminal_status=terminal.status)
    endings = [terminal.status, payload.get("finalStatus"), payload.get("resultStatus")]
    forbidden = (disposition == "budget_or_context" or any(value in _BLOCKED_CODES for value in codes)
                 or any(_code(value) in _BLOCKED_CODES | _HUMAN for value in endings))
    return code, forbidden


def _has_answer(events: list, terminal) -> bool:
    return any(event.turn_id == terminal.turn_id and event.sequence < terminal.sequence and event.visible_in_model and (
        (event.event_type == "assistant_message" and isinstance(event.payload.get("content"), str)
         and event.payload["content"].strip())
        or (event.event_type == "assistant_item_committed" and event.payload.get("kind") == "assistant_message"
            and event.payload.get("channel") == "answer" and event.payload.get("phase") == "final_answer"
            and isinstance(event.payload.get("text"), str) and event.payload["text"].strip())
    ) for event in events)


def _work_running(s, source: dict) -> bool:
    # Active-snapshot convenience APIs self-heal their shared index. Only use
    # the raw read APIs and inspect every active slot, not the latest 40 runs.
    work_runs = s._WORK_RUN_STORE
    index = work_runs.load_run_index("chat_turn")
    ids = index.get("activeRunIds") or [index.get("activeRunId")]
    if not isinstance(ids, list) or len(ids) > ACTIVE_RUN_IDS_LIMIT:
        raise store.WorkflowError("Session执行索引无法确认。")
    candidates = list(dict.fromkeys([source["turnId"], *[key for key in ids if isinstance(key, str) and key]]))
    for run_id in candidates:
        snapshot = work_runs.load_snapshot("chat_turn", run_id)
        if (snapshot and snapshot.get("sessionId") == source["sessionId"]
                and str(snapshot.get("status") or snapshot.get("currentPhase") or "").strip().lower()
                in _UNSETTLED | {"paused"}
                and not (snapshot.get("finishedAt") or snapshot.get("endedAt"))):
            return True
    return False


def _read(record: dict) -> tuple[dict, dict, list, bool, bool, dict]:
    step, source = _source(record)
    s = _service()
    state = s.load_session_chat_state(s.PROJECT_ROOT, source["sessionId"])
    _ownership(s, record, source, state)
    running = s._is_session_running(source["sessionId"]) or _work_running(s, source)
    events = journal_bridge.load_session_conversation_events_snapshot(source["sessionId"], project_root=s.PROJECT_ROOT)
    after = s.load_session_chat_state(s.PROJECT_ROOT, source["sessionId"])
    _ownership(s, record, source, after)
    later = journal_bridge.load_session_conversation_events_snapshot(source["sessionId"], project_root=s.PROJECT_ROOT)
    changed = state != after or [(e.event_id, e.sequence) for e in events] != [(e.event_id, e.sequence) for e in later]
    running = running or s._is_session_running(source["sessionId"]) or _work_running(s, source)
    return step, source, events, bool(changed or running), changed, after


def identity(record: dict) -> dict:
    _, source, events, _, changed, _ = _read(record)
    if changed:
        raise store.WorkflowError("Session来源已推进，请重新读取。")
    try:
        root, _, _ = _lineage(events, source)
    except _InvalidLineage as exc:
        raise store.WorkflowError("Session原生任务来源链无法确认。") from exc
    return {"kind": "session", "sessionId": source["sessionId"], "turnId": root, "agentId": source["agentId"]}


def observe(record: dict) -> dict:
    step, source, events, running, changed, state = _read(record)
    snapshot = {"status": "running", "eligible": False, "reason": "", "retryExhausted": False,
                "sourceAttemptKey": source["turnId"], "attempts": []}
    try:
        _, groups, advanced = _lineage(events, source)
    except _InvalidLineage:
        snapshot["reason"] = "source_lineage_invalid"
        return snapshot
    terminal_by_turn = {event.turn_id: event for event in events if event.event_type in TERMINAL_EVENTS}
    forbidden = False
    completion_unverified = False
    for number, group in enumerate(groups, 1):
        effective = group[-1]
        terminal = terminal_by_turn.get(effective)
        status, code = "running", ""
        if terminal is not None:
            if terminal.event_type == "turn_failed":
                status = "failed"
                code, forbidden = _failure(terminal)
            elif terminal.event_type == "turn_interrupted":
                status = "stopped"
            elif terminal.status in _SUCCESS and _has_answer(events, terminal):
                status = "completed"
            else:
                completion_unverified = True
        snapshot["attempts"].append({
            "nodeId": step["id"], "number": number, "agentId": source["agentId"],
            "sessionId": source["sessionId"], "turnId": effective, "originTurnId": group[0],
            "recoveryTurnIds": group[1:], "key": group[0], "status": status,
            "failureCode": code, "failureOrigin": "native",
        })
    last = snapshot["attempts"][-1]
    snapshot.update(status=last["status"], sourceAttemptKey=last["key"])
    persisted_status = str(state.get("last_turn_status") or state.get("lastTurnStatus") or "").strip().lower()
    if advanced or changed:
        snapshot.update(status="running", eligible=False, reason="source_advanced")
    elif running or persisted_status in _UNSETTLED:
        snapshot.update(status="running", reason="source_execution_unsettled")
    elif persisted_status in _HUMAN:
        snapshot["reason"] = "source_human_required"
    elif last["status"] == "stopped" or record.get("stopRequested"):
        snapshot.update(status="stopped", reason="source_stopped")
    elif last["status"] == "completed":
        snapshot["reason"] = "source_step_succeeded"
    elif last["status"] != "failed":
        snapshot["reason"] = "source_completion_unverified" if completion_unverified else "source_execution_unsettled"
    elif forbidden:
        snapshot["reason"] = "source_human_required"
    elif not last["failureCode"]:
        snapshot["reason"] = "source_problem_unsupported"
    else:
        policy = (record.get("flow") or {}).get("failureRecovery") or {}
        limit = policy.get("maxAttempts")
        if type(limit) is not int or not 1 <= limit <= 3:
            snapshot["reason"] = "source_retry_budget_unavailable"
        else:
            failed = 0
            for attempt in reversed(snapshot["attempts"]):
                if attempt["status"] != "failed":
                    break
                failed += 1
            snapshot.update(eligible=True, retryExhausted=failed >= limit)
    return snapshot


def fence(record: dict) -> str:
    try:
        snapshot = observe(record)
        if snapshot["reason"] == "source_lineage_invalid":
            return snapshot["reason"]
        previous = record.get("attempts") or []
        current = snapshot["attempts"]
        if snapshot["reason"] == "source_advanced" or not previous or not current or any(
            previous[-1].get(key) != current[-1].get(key) for key in ("key", "turnId", "originTurnId")
        ):
            return "source_advanced"
        return "" if snapshot["status"] == "failed" and snapshot["eligible"] else snapshot["reason"] or "source_not_failed"
    except store.WorkflowError:
        return "source_scope_unavailable"
    except Exception:
        return "source_observation_unavailable"


def replay(record: dict) -> str:
    """No native mutation: even user acknowledgement cannot add missing CAS."""
    return "source_replay_requires_user"
