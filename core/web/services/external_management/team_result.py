"""Read one TeamIntents result from existing native authorities without reconciliation."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from core.chat.conversation_ledger import conversation_visible_messages_from_events
from core.chat.turn_journal import TERMINAL_EVENTS, TurnJournalEvent, _safe_session_workspace_token
from core.web.services.session import directory_runtime
from core.web.services.team_workflow import one_shot
from core.web.services.team_workflow.generic import service as workflows, store as workflow_store
from .state_snapshot import ExistingStateSnapshot
from .store import digest

_MAX_JOURNAL_BYTES = 16 * 1024 * 1024
_MAX_EVENTS = 30000
_MAX_TEXT = 12000
_SUCCESS = {"ready", "completed", "done", "success", "succeeded"}
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")


def _unavailable():
    return {"status": "unavailable", "text": "", "truncated": False, "untrustedContent": True}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate journal key")
        result[key] = value
    return result


def _journal(path):
    """Strictly parse exactly one bounded complete physical Journal snapshot."""
    def stamp(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    before = path.stat()
    if before.st_size > _MAX_JOURNAL_BYTES:
        raise ValueError("journal too large")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        raw = stream.read(_MAX_JOURNAL_BYTES + 1)
        finished = os.fstat(stream.fileno())
    after = path.stat()
    if (stamp(before) != stamp(after) or stamp(before)[:4] != stamp(opened)[:4]
            or stamp(opened)[:4] != stamp(finished)[:4] or stamp(finished)[:4] != stamp(after)[:4]
            or opened.st_ctime_ns != finished.st_ctime_ns):
        raise ValueError("journal changed")
    if not raw or len(raw) > _MAX_JOURNAL_BYTES or not raw.endswith(b"\n"):
        raise ValueError("incomplete journal")
    lines = raw.splitlines()
    if len(lines) > _MAX_EVENTS:
        raise ValueError("too many journal events")
    events, ids, sequence = [], set(), -1
    for line in lines:
        value = json.loads(line, object_pairs_hook=_unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid constant")))
        if (not isinstance(value, dict) or not isinstance(value.get("eventId"), str) or not value["eventId"]
                or type(value.get("sequence")) is not int or value["sequence"] <= sequence
                or not isinstance(value.get("sessionId"), str) or not isinstance(value.get("turnId"), str)
                or not isinstance(value.get("eventType"), str) or not value["eventType"]
                or not isinstance(value.get("payload"), dict) or type(value.get("visibleInModel")) is not bool
                or value["eventId"] in ids):
            raise ValueError("invalid journal event")
        event = TurnJournalEvent.from_dict(value)
        if event is None:
            raise ValueError("invalid journal event")
        events.append(event)
        ids.add(event.event_id)
        sequence = event.sequence
    return events, stamp(after)


def _lineage(events, attempt):
    """Bind the original dispatch and each startup resume in this snapshot."""
    session, effective, key = attempt["sessionId"], attempt["turnId"], attempt["key"]
    if any(event.session_id != session or event.event_type == "branch_rebase" for event in events):
        raise ValueError("journal identity or branch conflict")
    users = [e for e in events if e.event_type == "user_message"]
    origins = [e for e in users if e.correlation_id == key]
    if len(origins) != 1 or origins[0].payload.get("source") != "generic_team_workflow":
        raise ValueError("dispatch identity unavailable")
    origin = origins[0]
    if not origin.turn_id or origin.turn_id != attempt["originTurnId"]:
        raise ValueError("origin mismatch")
    chain, cursor = [origin.turn_id], origin
    for child_id in attempt["recoveryTurnIds"]:
        children = [e for e in users if e.correlation_id == "resume:" + chain[-1]]
        if len(children) != 1:
            raise ValueError("recovery mismatch")
        child = children[0]
        meta = child.payload.get("metadata")
        if (not isinstance(meta, dict) or child.sequence <= cursor.sequence or child.turn_id != child_id
                or not child_id or child_id in chain or child.payload.get("source") != "hot_restart_resume"
                or meta.get("kind") != "hot_restart_resume" or meta.get("recoverySource") != "startup_sweep"
                or meta.get("recoveredTurnId") != chain[-1]):
            raise ValueError("invalid recovery")
        if any(e.turn_id == chain[-1] and e.event_type in TERMINAL_EVENTS for e in events):
            raise ValueError("recovered terminal turn")
        chain.append(child_id)
        cursor = child
    if (chain[-1] != effective or len(chain) > 33
            or any(e.correlation_id == "resume:" + effective for e in users)
            or len(users) != len(chain) or {e.turn_id for e in users} != set(chain)):
        raise ValueError("ambiguous session lineage")
    terminals = [e for e in events if e.turn_id == effective and e.event_type in TERMINAL_EVENTS]
    if (len(terminals) != 1 or terminals[0].event_type != "turn_completed"
            or terminals[0].status.strip().lower() not in _SUCCESS or terminals[0].sequence <= cursor.sequence
            or any(str(terminals[0].payload.get(key) or "").strip().lower() not in _SUCCESS | {""}
                   for key in ("resultStatus", "finalStatus"))
            or any(e.turn_id == effective and e.sequence > terminals[0].sequence
                   and e.event_type in {"assistant_message", "assistant_item_committed"} for e in events)):
        raise ValueError("terminal unverified")
    return terminals[0], cursor.sequence


def _answer(events, attempt, terminal, user_sequence):
    prefix = [event for event in events if event.turn_id == attempt["turnId"]
              and user_sequence <= event.sequence < terminal.sequence]
    for event in prefix:
        metadata = event.payload.get("metadata")
        if event.event_type == "assistant_message" and isinstance(metadata, dict):
            if (metadata.get("turnId", event.turn_id) != event.turn_id
                    or metadata.get("eventId", event.event_id) != event.event_id
                    or str(metadata.get("kind") or "").lower() in {
                        "tool_result", "tool_call_started", "cli_task_result", "cli_task_sent", "cli_session_lifecycle"}):
                raise ValueError("assistant projection identity conflict")
    messages = conversation_visible_messages_from_events(prefix)
    allowed = {e.event_id for e in prefix if e.turn_id == attempt["turnId"] and e.sequence > user_sequence and e.visible_in_model
               and (e.event_type == "assistant_message" or (e.event_type == "assistant_item_committed"
                    and e.payload.get("kind") == "assistant_message" and e.payload.get("channel") == "answer"
                    and e.payload.get("phase") == "final_answer"))}
    candidates = [message for message in messages if message.get("role") == "assistant"
                  and isinstance(message.get("metadata"), dict)
                  and message["metadata"].get("turnId") == attempt["turnId"]
                  and message["metadata"].get("eventId") in allowed]
    if not candidates:
        return {"status": "empty", "text": "", "truncated": False, "untrustedContent": True}
    text = candidates[-1].get("content")
    if not isinstance(text, str):
        raise ValueError("invalid answer")
    text = text.strip()
    if not text:
        return {"status": "empty", "text": "", "truncated": False, "untrustedContent": True}
    return {"status": "available", "text": text[:_MAX_TEXT], "truncated": len(text) > _MAX_TEXT, "untrustedContent": True}


def read_team_result(intents, request_id: str, project_root: Path) -> dict:
    """Project the final answer of the caller's original TeamIntents request.

    Caller must supply TeamIntents constructed from the currently authorized grant.
    No Session detail, workflow artifacts, completion snapshot or mutation is used.
    """
    try:
        return _read_team_result(intents, request_id, Path(project_root).resolve())
    except Exception:  # noqa: BLE001 -- every missing/conflicting authority fails closed
        return _unavailable()


def _read_team_result(intents, request_id, root):
    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", request_id):
        raise ValueError("invalid request")
    if Path(intents.native.project_root).resolve() != root:
        raise ValueError("project mismatch")
    intents.native._owners()
    directory = intents.native.agents._owners()
    state = ExistingStateSnapshot(root, directory, pin_workspace=True)
    record_path = intents.store.path("team-requests", intents._key(request_id))
    record = state.read_json(record_path, strict=True, max_bytes=64 * 1024)
    if not isinstance(record, dict):
        raise ValueError("missing intent")
    intents._check(record, request_id)
    team_id = workflow_store.token(record["teamId"])
    if not record.get("flowFingerprint"):
        raise ValueError("unconfirmed flow")
    teams_path = state.path("teams", "teams.json")
    teams = state.read_json(teams_path, strict=True)
    matches = [team for team in teams["teams"] if isinstance(team, dict) and team.get("teamId") == team_id]
    if len(matches) != 1 or matches[0].get("status") == "archived" or matches[0].get("teamSource") != record["marker"]["teamSource"]:
        raise ValueError("team identity mismatch")
    run_id = record.get("runId") or "run-" + workflows.digest([record["flowId"], request_id])[:40]
    run_id = workflow_store.token(run_id)
    run_path = state.path("teams", team_id, "generic-workflows", "runs", run_id + ".json")
    raw = state.read_json(run_path, strict=True)
    run = workflows.public(raw)
    values = run.get("values")
    if not isinstance(values, dict) or set(values) != {"goal"} or digest(values["goal"]) != record["goalHash"]:
        raise ValueError("goal mismatch")
    one_shot._verify_run(run, record, request_id, values["goal"])
    if raw.get("_createFingerprint") != workflows.digest([record["flowId"], 1, values]):
        raise ValueError("admission mismatch")
    steps, attempts = run["flow"]["steps"], run["attempts"]
    if (run["status"] != "completed" or run["stopRequested"] or type(raw.get("current")) is not int or not steps or run["current"] != len(steps)
            or len(attempts) > workflows.MAX_ATTEMPTS or not attempts):
        raise ValueError("run not completed")
    step, attempt = steps[-1], attempts[-1]
    members = matches[0].get("members")
    if (step["id"] != one_shot._ROLES[-1][0] or step["kind"] != "agent"
            or attempt["nodeId"] != step["id"] or attempt["agentId"] != step["owner"]
            or not isinstance(members, list) or sum(isinstance(m, dict) and m.get("agentId") == step["owner"]
                                                    and m.get("status") != "archived" for m in members) != 1
            or attempt["status"] != "completed" or type(raw["attempts"][-1].get("number")) is not int or attempt["number"] < 1
            or attempt["number"] != sum(item["nodeId"] == step["id"] for item in attempts)
            or attempt["key"] != "gw-" + workflows.digest([str(run_path), run_id, step["id"], attempt["number"]])[:48]
            or any(not isinstance(attempt[k], str) or not _TOKEN.fullmatch(attempt[k]) for k in ("agentId", "sessionId", "turnId", "originTurnId"))):
        raise ValueError("attempt mismatch")
    store = directory_runtime.get_open_directory_store()
    if store is None or directory_runtime.directory_store_project_root() is None or Path(directory_runtime.directory_store_project_root()).resolve() != root:
        raise ValueError("session store unavailable")
    row = store.repository.get_session(attempt["sessionId"], include_archived=False)
    runtime = store.repository.get_session_runtime_state(attempt["sessionId"])
    from .workspace import _session_identity
    if not isinstance(row, dict) or not isinstance(runtime, dict) or _session_identity(row, runtime, attempt["sessionId"]) != attempt["agentId"]:
        raise ValueError("session owner mismatch")
    metadata = runtime.get("metadata")
    if (not isinstance(metadata, dict) or metadata.get("source") != "generic_team_workflow"
            or metadata.get("externalTaskId") != attempt["key"] or runtime.get("archived") is True
            or runtime.get("read_only") or runtime.get("readOnly")):
        raise ValueError("session task mismatch")
    journal_path = state.path("sessions", _safe_session_workspace_token(attempt["sessionId"]), "turn_journal.jsonl")
    events, stamp = _journal(journal_path)
    terminal, user_sequence = _lineage(events, attempt)
    answer = _answer(events, attempt, terminal, user_sequence)
    state.verify_workspace()
    if (state.read_json(record_path, strict=True, max_bytes=64 * 1024) != record or state.read_json(teams_path, strict=True) != teams
            or state.read_json(run_path, strict=True) != raw
            or store is not directory_runtime.get_open_directory_store()
            or Path(directory_runtime.directory_store_project_root()).resolve() != root
            or store.repository.get_session(attempt["sessionId"], include_archived=False) != row
            or store.repository.get_session_runtime_state(attempt["sessionId"]) != runtime
            or ExistingStateSnapshot._path_token(journal_path)[1:] != stamp):
        raise ValueError("authority changed")
    return answer
