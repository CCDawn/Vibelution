"""Read-only proof from legacy Inbox delivery to native Journal Turn and run.

No task capability, admission, repair, wake, continuation or lease API is used.
runtime_root is an explicitly supplied native .runtime root; it is never inferred.
inbox_paths is trusted constructor input and only permits existing workspace paths.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import re

from .migration_inventory import InventoryError, declared_assistant_identities
from .legacy_handoff import AbsentInboxProof, ObservationPreview, _stable_parent
from .migration_io import MigrationIOError, check_path, path_identity, read_stable_file, strict_json, verify_snapshot
from core.web.services.personal_assistant_dispatches_service import _dispatch_task_status, _is_followup, _task_report

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
_HASH = re.compile(r"^[a-f0-9]{64}$")
_TERMINAL = {"turn_completed": "completed", "turn_failed": "failed", "turn_interrupted": "interrupted"}


def _token(value):
    return isinstance(value, str) and _TOKEN.fullmatch(value) is not None


def _alias(row, *keys, required=True):
    values = [row[key] for key in keys if row.get(key) not in (None, "")]
    if any(not _token(value) for value in values) or len(set(values)) > 1 or (required and not values):
        raise MigrationIOError("source_identity_invalid")
    return values[0] if values else ""


def _metadata(row):
    metadata = row.get("metadata", {})
    if not isinstance(metadata, dict):
        raise MigrationIOError("inbox_metadata_invalid")
    result = dict(metadata)
    encoded = metadata.get("agentToolMetadataJson")
    if encoded is not None:
        if not isinstance(encoded, str) or len(encoded) > 8192:
            raise MigrationIOError("inbox_metadata_invalid")
        custom = strict_json(encoded)
        if not isinstance(custom, dict):
            raise MigrationIOError("inbox_metadata_invalid")
        for key in ("replyToMessageId", "paFollowupOfMessageId", "paFollowupRound", "personalAssistantTask"):
            if key in custom:
                if key in result and result[key] != custom[key]:
                    raise MigrationIOError("inbox_metadata_conflict")
                result[key] = custom[key]
    for key in ("sourceSessionId", "targetSessionId"):
        if key in row:
            if key in result and row[key] != result[key]:
                raise MigrationIOError("inbox_routing_conflict")
            result[key] = row[key]
    return result


def _chain(path):
    check_path(path)
    return tuple((node, path_identity(node) if node == path else _stable_parent(node.lstat()))
                 for node in (*reversed(path.parents), path))


def correlate_legacy_dispatches(preview, *, workspace: Path, runtime_root: Path | None = None,
                                inbox_paths: dict[str, Path] | None = None, max_files=256,
                                max_file_bytes=8 * 1024 * 1024, max_total_bytes=64 * 1024 * 1024,
                                max_rows=10000, max_line_bytes=256 * 1024) -> dict:
    """Reopen preview authority and correlate existing facts, never replay dispatches.

    Missing consumption with a unique Journal acceptance retains nativeTurnId,
    but stays unresolved. nativeRunId requires an actual matching run snapshot.
    All source changes invalidate the batch. Reports contain no body or paths.
    """
    if (any(type(n) is not int or n < 1 for n in (max_files, max_file_bytes, max_total_bytes, max_rows, max_line_bytes))
            or max_files > 1024 or max_file_bytes > 16 * 1024 * 1024 or max_rows > 100000
            or max_total_bytes > 128 * 1024 * 1024 or max_line_bytes > 1024 * 1024):
        raise MigrationIOError("invalid_correlation_budget")
    observation = preview if isinstance(preview, ObservationPreview) else None
    if observation is not None:
        preview = observation.report
    workspace = Path(workspace)
    if not workspace.is_absolute() or ".." in workspace.parts:
        raise MigrationIOError("absolute_source_required")
    report = {"schemaVersion": 1, "stage": "legacy_correlation", "dispatches": [], "issues": [],
              "correlationComplete": False, "sourceQuiesced": False, "readyForCutover": False,
              "canRedispatch": False}
    requests = preview.get("dispatches", []) if isinstance(preview, dict) else []
    if not isinstance(requests, list) or len(requests) > max_rows:
        report["issues"].append({"code": "preview_dispatches_invalid"})
        return report
    for request in requests:
        if not isinstance(request, dict) or not all(_token(request.get(key)) for key in
                ("legacyMessageId", "sourceAgentId", "targetAgentId", "sourceSessionId", "targetSessionId")):
            report["issues"].append({"code": "preview_dispatch_identity_invalid"})
            continue
        report["dispatches"].append({key: request[key] for key in
            ("legacyMessageId", "sourceAgentId", "targetAgentId", "sourceSessionId", "targetSessionId")})
    for row in report["dispatches"]:
        row.update(nativeTaskId=None, nativeTurnId=None, nativeRunId=None, nativeTurnStatus=None,
                   nativeCorrelation="unresolved", reason="source_unverified", businessTaskStatus="unresolved",
                   canRedispatch=False)
    snapshots, chains, used_rows, total_bytes = {}, {}, 0, 0

    def read(path, *, expected_hash=None, cap=None):
        nonlocal total_bytes
        if path in snapshots:
            snapshot = snapshots[path]
        else:
            if len(snapshots) >= max_files:
                raise MigrationIOError("file_limit")
            remaining = max_total_bytes - total_bytes
            if remaining < 1:
                raise MigrationIOError("total_byte_limit")
            before = _chain(path)
            snapshot = read_stable_file(path, min(max_file_bytes if cap is None else cap, remaining))
            if _chain(path) != before:
                raise MigrationIOError("source_changed")
            snapshots[path], chains[path] = snapshot, before
            total_bytes += len(snapshot.raw)
        if expected_hash is not None and snapshot.sha256 != expected_hash:
            raise MigrationIOError("preview_source_changed")
        return snapshot

    def jsonl(snapshot):
        nonlocal used_rows
        if snapshot.raw and not snapshot.raw.endswith(b"\n"):
            raise MigrationIOError("truncated_source_jsonl")
        result = []
        for line in snapshot.raw.splitlines(keepends=True):
            used_rows += 1
            if used_rows > max_rows or len(line) > max_line_bytes:
                raise MigrationIOError("source_row_or_line_limit")
            row = strict_json(line)
            if not isinstance(row, dict):
                raise MigrationIOError("source_row_invalid")
            result.append(row)
        return result

    try:
        check_path(workspace)
        runtime_base = None
        if runtime_root is not None:
            runtime_base = Path(runtime_root)
            if not runtime_base.is_absolute() or ".." in runtime_base.parts:
                raise MigrationIOError("runtime_root_invalid")
            check_path(runtime_base)
        complete = (preview.get("stage") == "observation_preview" and preview.get("observationComplete") is True
                    if observation is not None and isinstance(preview, dict)
                    else isinstance(preview, dict) and preview.get("stage") == "handoff_preview" and preview.get("previewComplete") is True)
        if (not isinstance(preview, dict) or not complete or preview.get("issues") != []
                or not _token(preview.get("assistantAgentId"))):
            raise MigrationIOError("preview_incomplete_or_invalid")
        scope = preview.get("sourceScope")
        if (not isinstance(scope, dict) or not all(_token(scope.get(key)) for key in ("projectId", "instanceId"))
                or not isinstance(scope.get("workspace"), str) or Path(scope["workspace"]) != workspace):
            raise MigrationIOError("preview_scope_mismatch")
        digest = preview.get("registrySha256")
        if not isinstance(digest, str) or not _HASH.fullmatch(digest):
            raise MigrationIOError("preview_registry_fingerprint_invalid")
        registry = strict_json(read(workspace / "agents/agents.json", expected_hash=digest, cap=16 * 1024 * 1024).raw)
        agents = registry.get("agents") if isinstance(registry, dict) else None
        if not isinstance(agents, list) or len(agents) > max_files or any(not isinstance(row, dict) for row in agents):
            raise MigrationIOError("registry_identity_invalid")
        ids, sessions = set(), set()
        by_agent = {}
        for agent in agents:
            aid, sid = agent.get("agentId"), agent.get("directSessionId")
            if (not _token(aid) or not _token(sid) or aid in ids or sid in sessions
                    or agent.get("status") not in ("active", "archived")):
                raise MigrationIOError("registry_identity_invalid")
            ids.add(aid)
            sessions.add(sid)
            by_agent[aid] = agent
        selected = [row for row in declared_assistant_identities(agents) if row["agentId"] == preview["assistantAgentId"]]
        if (len(selected) != 1 or selected[0]["sessionId"] != preview.get("sourceSessionId")
                or selected[0]["agentConfigSha256"] != preview.get("agentConfigSha256")):
            raise MigrationIOError("preview_assistant_identity_mismatch")
        aid, source_sid = selected[0]["agentId"], selected[0]["sessionId"]
        absent_ids = set()
        if observation is not None:
            if (not isinstance(observation.absences, tuple) or len(observation.absences) > max_files
                    or preview.get("observationMessageIds") != [row["legacyMessageId"] for row in report["dispatches"]]):
                raise MigrationIOError("observation_scope_mismatch")
            protected = {aid, *(row["targetAgentId"] for row in report["dispatches"])}
            for absent in observation.absences:
                if (not isinstance(absent, AbsentInboxProof) or absent.agent_id not in ids
                        or absent.agent_id in absent_ids or absent.agent_id in protected
                        or by_agent[absent.agent_id].get("workspacePath", "") not in ("", f"workspace/agents/{absent.agent_id}")):
                    raise MigrationIOError("absent_inbox_scope_invalid")
                absent.verify(workspace)
                absent_ids.add(absent.agent_id)
        sources = preview.get("sources")
        if (not isinstance(sources, list) or len(sources) != len(agents) - len(absent_ids)
                or any(not isinstance(item, dict) or item.get("agentId") not in ids - absent_ids
                       or not isinstance(item.get("sha256"), str) or not _HASH.fullmatch(item["sha256"]) for item in sources)
                or len({item["agentId"] for item in sources}) != len(agents) - len(absent_ids)):
            raise MigrationIOError("preview_inbox_fingerprints_incomplete")
        if inbox_paths is not None and (not isinstance(inbox_paths, dict) or any(key not in ids for key in inbox_paths)):
            raise MigrationIOError("inbox_mapping_invalid")
        inboxes, message_counts = {}, Counter()
        for evidence in sources:
            target = evidence["agentId"]
            default = workspace / "agents" / target / "events/agent_inbox_messages.jsonl"
            path = (inbox_paths or {}).get(target, default)
            if (not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts
                    or not path.is_relative_to(workspace)):
                raise MigrationIOError("external_inbox_mapping_unsupported")
            agents_root = workspace / "agents"
            if path.is_relative_to(agents_root) and path.relative_to(agents_root).parts[0] != target:
                raise MigrationIOError("inbox_mapping_owner_mismatch")
            if target not in (inbox_paths or {}) and by_agent[target].get("workspacePath", "") not in ("", f"workspace/agents/{target}"):
                raise MigrationIOError("custom_inbox_mapping_required")
            items = jsonl(read(path, expected_hash=evidence["sha256"]))
            for item in items:
                mid = _alias(item, "messageId", "eventId")
                if item.get("targetAgentId") != target or item.get("status", "pending") not in ("pending", "consumed", "revoked"):
                    raise MigrationIOError("inbox_routing_invalid")
                item["metadata"] = _metadata(item)
                message_counts[mid] += 1
            inboxes[target] = items
        if any(count > 1 for count in message_counts.values()):
            raise MigrationIOError("duplicate_message_id")
        request_ids = [row["legacyMessageId"] for row in report["dispatches"]]
        if len(set(request_ids)) != len(request_ids):
            raise MigrationIOError("duplicate_preview_dispatch")
        journals = {}
        for result in report["dispatches"]:
            try:
                mid, target, sid = result["legacyMessageId"], result["targetAgentId"], result["targetSessionId"]
                if target not in by_agent or result["sourceAgentId"] != aid or result["sourceSessionId"] != source_sid:
                    raise MigrationIOError("dispatch_identity_mismatch")
                dispatches = [item for item in inboxes[target] if _alias(item, "messageId", "eventId") == mid]
                if len(dispatches) != 1:
                    raise MigrationIOError("dispatch_source_missing")
                dispatch = dispatches[0]
                if (dispatch.get("sourceAgentId") != aid or dispatch["metadata"].get("sourceSessionId") != source_sid
                        or dispatch["metadata"].get("targetSessionId") != sid
                        or dispatch.get("kind") == "agent_inbox_reply" or _is_followup(dispatch)):
                    raise MigrationIOError("dispatch_routing_mismatch")
                receipts, reports = [], []
                for item in inboxes[aid]:
                    meta = item["metadata"]
                    if meta.get("replyToMessageId") != mid:
                        continue
                    if (item.get("sourceAgentId") != target or meta.get("sourceSessionId") != sid
                            or meta.get("targetSessionId") != source_sid):
                        raise MigrationIOError("receipt_routing_mismatch")
                    receipts.append(item)
                    task = _task_report(item, dispatch)
                    if task:
                        reports.append(task)
                result["businessTaskStatus"] = _dispatch_task_status(dispatch.get("status", "pending"), reports)
                if sid not in journals:
                    events = jsonl(read(workspace / "sessions" / sid / "turn_journal.jsonl"))
                    event_ids, sequence = set(), 0
                    for event in events:
                        eid = _alias(event, "eventId", "event_id")
                        if (_alias(event, "sessionId", "session_id") != sid or eid in event_ids
                                or type(event.get("sequence")) is not int or event["sequence"] <= sequence
                                or ("schemaVersion" in event and (type(event["schemaVersion"]) is not int or event["schemaVersion"] not in (1, 2)))
                                or not isinstance(event.get("eventType"), str) or not isinstance(event.get("payload"), dict)):
                            raise MigrationIOError("journal_identity_invalid")
                        _alias(event, "turnId", "turn_id")
                        event_ids.add(eid)
                        sequence = event["sequence"]
                    journals[sid] = events
                events = journals[sid]
                proofs = [event for event in events if event["eventType"] == "user_message"
                          and isinstance(event["payload"].get("metadata"), dict)
                          and event["payload"]["metadata"].get("messageId") == mid]
                if len(proofs) != 1:
                    raise MigrationIOError("journal_dispatch_missing" if not proofs else "journal_dispatch_ambiguous")
                proof = proofs[0]
                turn, metadata = _alias(proof, "turnId", "turn_id"), proof["payload"]["metadata"]
                if (metadata.get("kind") != "agent_inbox_message" or any(metadata.get(key) != value for key, value in
                        (("sourceAgentId", aid), ("sourceSessionId", source_sid), ("targetAgentId", target), ("targetSessionId", sid)))
                        or metadata.get("turnId", turn) != turn):
                    raise MigrationIOError("journal_dispatch_routing_mismatch")
                turn_events = [event for event in events if _alias(event, "turnId", "turn_id") == turn]
                started = [event for event in turn_events if event["eventType"] == "turn_started"]
                if len(started) != 1 or started[0]["payload"].get("agentId") != target or started[0]["sequence"] >= proof["sequence"]:
                    raise MigrationIOError("journal_turn_owner_unproven")
                terminals = [event for event in turn_events if event["eventType"] in _TERMINAL]
                if len(terminals) > 1 or any(event["sequence"] <= proof["sequence"] for event in terminals):
                    raise MigrationIOError("journal_turn_terminal_conflict")
                consumed_sid, consumed_turn = dispatch.get("consumedBySessionId"), dispatch.get("consumedByTurnId")
                missing_consumption = not consumed_sid and not consumed_turn
                if not missing_consumption and (consumed_sid != sid or consumed_turn != turn or dispatch.get("status") != "consumed"):
                    raise MigrationIOError("consumed_identity_mismatch")
                for receipt in receipts:
                    source_turn = receipt["metadata"].get("sourceTurnId")
                    if source_turn not in (None, "", turn):
                        raise MigrationIOError("receipt_turn_mismatch")
                result.update(nativeTurnId=turn, nativeTurnStatus=_TERMINAL[terminals[0]["eventType"]] if terminals else "running",
                              nativeCorrelation="unresolved" if missing_consumption else "correlated",
                              reason="consume_receipt_missing" if missing_consumption else "matched")
                result["nativeRunReason"] = "runtime_root_not_supplied"
                if runtime_base is not None:
                    path = runtime_base / "runtime-manager/work_runs/chat_turn/runs" / (turn + ".json")
                    try:
                        path.lstat()
                    except FileNotFoundError:
                        result["nativeRunReason"] = "native_run_missing"
                    else:
                        run = strict_json(read(path).raw)
                        if (not isinstance(run, dict) or run.get("runKind") != "chat_turn" or run.get("runId") != turn
                                or run.get("sessionId") != sid or run.get("agentId") != target):
                            raise MigrationIOError("native_run_identity_mismatch")
                        result.update(nativeRunId=turn, nativeRunReason="matched")
            except (MigrationIOError, OSError) as error:
                code = str(error) if isinstance(error, MigrationIOError) else "source_unavailable"
                result.update(nativeTaskId=None, nativeTurnId=None, nativeRunId=None, nativeTurnStatus=None,
                              nativeCorrelation="unresolved", nativeRunReason=code, reason=code)
        for path, snapshot in snapshots.items():
            verify_snapshot(snapshot)
            if _chain(path) != chains[path]:
                raise MigrationIOError("source_changed")
        if observation is not None:
            for absent in observation.absences:
                absent.verify(workspace)
    except (MigrationIOError, ValueError, KeyError, TypeError, OSError) as error:
        code = str(error) if isinstance(error, (MigrationIOError, InventoryError)) else "correlation_source_invalid"
        report["issues"].append({"code": code})
        for result in report["dispatches"]:
            result.update(nativeTaskId=None, nativeTurnId=None, nativeRunId=None, nativeTurnStatus=None,
                          nativeCorrelation="unresolved", nativeRunReason="source_unverified", reason=code, businessTaskStatus="unresolved")
    report["correlationComplete"] = not report["issues"] and all(row["nativeCorrelation"] == "correlated" for row in report["dispatches"])
    return report
