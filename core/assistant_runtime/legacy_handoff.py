"""Bounded observations of legacy dispatches; no native admission or migration.

Only declared default inboxes are read. Legacy IDs are evidence references,
never native task capabilities. Completeness describes this scan, not cutover.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from collections import Counter
from pathlib import Path

from core.assistant_runtime.migration_inventory import InventoryError, _TOKEN, declared_assistant_identities
from core.web.services.personal_assistant_dispatches_service import (
    _dispatch_task_status, _is_followup, _metadata, _task_report,
)


def _strict_json(raw: bytes | str):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate_key")
            result[key] = value
        return result
    def constant(_value):
        raise ValueError("nonfinite_json")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def _token(value):
    return isinstance(value, str) and _TOKEN.fullmatch(value) is not None


def _stat_identity(value):
    # Windows Python 3.12 path.stat exposes creation time as ctime whereas
    # fstat exposes metadata-change time; birthtime is consistent on both.
    stable_time = getattr(value, "st_birthtime_ns", value.st_ctime_ns)
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
            stable_time, value.st_mode, value.st_nlink)


def _identity(path):
    return _stat_identity(path.stat())


def _safe_path(path):
    # Check every ancestor, including roots supplied by the caller, before I/O.
    for node in (*reversed(path.parents), path):
        value = node.lstat()
        if stat.S_ISLNK(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400:
            raise InventoryError("linked_source")
        if node != path and not stat.S_ISDIR(value.st_mode):
            raise InventoryError("source_type_mismatch")
    return path


def preview_legacy_handoff(*, project_root: Path, workspace: Path, project_id: str,
                           instance_id: str, assistant_agent_id: str,
                           max_files: int = 256, max_file_bytes: int = 8 * 1024 * 1024,
                           max_total_bytes: int = 64 * 1024 * 1024,
                           max_rows: int = 10000, max_line_bytes: int = 256 * 1024) -> dict:
    """Read existing registry/inboxes only; missing/corrupt sources stay incomplete.

    Limits cover all JSONL files together (bytes/rows) and each file/line.
    Snapshot verification rereads at most the same bounded byte count. The
    registry is separately bounded to 16 MiB. PA identity adjudication reuses
    the inventory's pure rule, without a second inventory or source-tree scan.
    """
    if not all(isinstance(p, Path) and p.is_absolute() for p in (project_root, workspace)):
        raise InventoryError("absolute_source_roots_required")
    if not _token(assistant_agent_id):
        raise InventoryError("assistant_identity_unavailable")
    if any(type(n) is not int or n < 1 for n in
           (max_files, max_file_bytes, max_total_bytes, max_rows, max_line_bytes)):
        raise InventoryError("positive_preview_limits_required")
    report = {"schemaVersion": 1, "stage": "handoff_preview", "assistantAgentId": assistant_agent_id,
        "sourceQuiesced": False, "readyForCutover": False, "previewComplete": False,
        "registrySha256": None, "dispatches": [], "sources": [], "issues": [],
        "counts": {"files": 0, "bytes": 0, "rows": 0, "excludedFollowups": 0, "unresolvedReceipts": 0}}
    issues, counts = report["issues"], report["counts"]
    snapshots = []
    seen_issues = set()

    def issue(code, aid=None):
        key = (code, aid)
        if key in seen_issues:
            return
        seen_issues.add(key)
        if len(issues) >= 255:
            if not any(item["code"] == "issue_limit" for item in issues):
                issues.append({"code": "issue_limit"})
            return
        entry = {"code": code}
        if aid is not None:
            entry["agentId"] = aid
        issues.append(entry)

    def read(path, cap, *, remember=True, expected=None):
        _safe_path(path)
        before = _identity(path)
        if expected is not None and before != expected:
            raise InventoryError("source_changed")
        if not stat.S_ISREG(before[5]):
            raise InventoryError("source_type_mismatch")
        if before[6] != 1:
            raise InventoryError("linked_source")
        if before[2] > cap:
            raise InventoryError("file_byte_limit")
        with path.open("rb") as stream:
            if _stat_identity(os.fstat(stream.fileno())) != before:
                raise InventoryError("source_changed")
            _safe_path(path)
            raw = stream.read(cap + 1)
            if _stat_identity(os.fstat(stream.fileno())) != before:
                raise InventoryError("source_changed")
        _safe_path(path)
        if len(raw) > cap or len(raw) != before[2] or _identity(path) != before:
            raise InventoryError("source_changed")
        digest = hashlib.sha256(raw).hexdigest()
        if remember:
            snapshots.append((path, before, digest))
        return raw, digest

    try:
        _safe_path(project_root)
        _safe_path(workspace)
        registry = workspace / "agents/agents.json"
        raw, digest = read(registry, 16 * 1024 * 1024)
        payload = _strict_json(raw.decode("utf-8-sig"))
        rows = payload["agents"]
        if not isinstance(rows, list) or len(rows) > max_files or not all(isinstance(r, dict) for r in rows):
            raise InventoryError("registry_identity_invalid_or_file_limit")
        aids, sessions = set(), set()
        for row in rows:
            aid, sid = row.get("agentId"), row.get("directSessionId")
            if (not _token(aid) or not _token(sid) or aid in aids or sid in sessions
                    or row.get("status") not in ("active", "archived")):
                raise InventoryError("registry_identity_invalid")
            aids.add(aid)
            sessions.add(sid)
        selected = [r for r in declared_assistant_identities(rows) if r["agentId"] == assistant_agent_id]
        if len(selected) != 1:
            raise InventoryError("assistant_identity_unavailable")
        selected = selected[0]
        report.update(registrySha256=digest, sourceSessionId=selected["sessionId"],
                      agentConfigSha256=selected["agentConfigSha256"],
                      sourceScope={"projectId": project_id, "instanceId": instance_id,
                          "projectRoot": str(project_root.resolve()), "workspace": str(workspace.resolve())})
    except InventoryError as exc:
        issue(str(exc))
        return report
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        issue("registry_unavailable_or_invalid")
        return report

    inboxes = {}
    for row in rows:
        aid = row["agentId"]
        declared = row.get("workspacePath", "")
        if not isinstance(declared, str) or declared not in ("", f"workspace/agents/{aid}"):
            issue("custom_workspace_unsupported", aid)
            continue
        if counts["files"] >= max_files:
            issue("file_limit", aid)
            break
        counts["files"] += 1
        path = workspace / "agents" / aid / "events/agent_inbox_messages.jsonl"
        try:
            remaining = max_total_bytes - counts["bytes"]
            if remaining <= 0:
                raise InventoryError("total_byte_limit")
            try:
                raw, digest = read(path, min(max_file_bytes, remaining))
            except InventoryError as exc:
                if str(exc) == "file_byte_limit" and remaining < max_file_bytes:
                    raise InventoryError("total_byte_limit") from None
                raise
            counts["bytes"] += len(raw)
            report["sources"].append({"agentId": aid, "size": len(raw), "sha256": digest})
            if raw and not raw.endswith(b"\n"):
                issue("truncated_jsonl", aid)
            parsed = []
            for line in raw.splitlines(keepends=True):
                if counts["rows"] >= max_rows:
                    issue("row_limit", aid)
                    break
                counts["rows"] += 1
                if len(line) > max_line_bytes:
                    issue("line_limit", aid)
                    continue
                try:
                    item = _strict_json(line.decode("utf-8"))
                    if not isinstance(item, dict):
                        raise ValueError("row_not_object")
                    mid = item.get("messageId") or item.get("eventId")
                    if ("messageId" in item and "eventId" in item
                            and item["messageId"] != item["eventId"]):
                        raise ValueError("message_identity_conflict")
                    if (not all(_token(v) for v in (mid, item.get("targetAgentId")))
                            or not (item.get("sourceAgentId") == "" or _token(item.get("sourceAgentId")))):
                        raise ValueError("row_identity_invalid")
                    if item["targetAgentId"] != aid:
                        issue("inbox_target_conflict", aid)
                        continue
                    if item.get("status", "pending") not in ("pending", "consumed", "revoked"):
                        raise ValueError("row_status_invalid")
                    metadata = item.get("metadata", {})
                    if not isinstance(metadata, dict):
                        raise ValueError("metadata_not_object")
                    for container, keys in ((item, ("messageId", "eventId")),):
                        if any(key in container and not _token(container[key]) for key in keys):
                            raise ValueError("routing_identity_invalid")
                    for container in (item, metadata):
                        if any(key in container and not (container[key] == "" or _token(container[key]))
                               for key in ("sourceSessionId", "targetSessionId")):
                            raise ValueError("routing_identity_invalid")
                    if any(key in item and key in metadata and item[key] != metadata[key]
                           for key in ("sourceSessionId", "targetSessionId")):
                        raise ValueError("routing_identity_conflict")
                    encoded = metadata.get("agentToolMetadataJson")
                    if encoded is not None and (not isinstance(encoded, str) or len(encoded) > 8192
                            or not isinstance(_strict_json(encoded), dict)):
                        raise ValueError("invalid_protocol_metadata")
                    # The canonical inbox writer persists sourceSessionId at
                    # top level. Adapt only explicit, non-conflicting evidence
                    # for the existing pure report rule; never infer a Session.
                    if "sourceSessionId" in item and "sourceSessionId" not in metadata:
                        item = {**item, "metadata": {**metadata, "sourceSessionId": item["sourceSessionId"]}}
                    parsed.append(item)
                except (ValueError, TypeError, RecursionError):
                    issue("invalid_jsonl", aid)
            inboxes[aid] = parsed
        except InventoryError as exc:
            issue(str(exc), aid)
        except FileNotFoundError:
            issue("source_missing", aid)
        except OSError:
            issue("source_unreadable", aid)

    # All message IDs participate in ambiguity detection, even unrelated rows.
    ids = Counter()
    for entries in inboxes.values():
        for row in entries:
            mid = row.get("messageId") or row.get("eventId")
            if _token(mid):
                ids[mid] += 1
    ambiguous = {mid for mid, number in ids.items() if number > 1}
    if ambiguous:
        issue("duplicate_message_id")
    dispatches = []
    for aid, entries in inboxes.items():
        if aid == assistant_agent_id:
            continue
        for row in entries:
            if row.get("sourceAgentId") != assistant_agent_id or row.get("kind") == "agent_inbox_reply":
                continue
            if _is_followup(row):
                counts["excludedFollowups"] += 1
                continue
            mid = row.get("messageId") or row.get("eventId")
            metadata = _metadata(row)
            if (not _token(mid) or row.get("targetAgentId") != aid
                    or row.get("status", "pending") not in ("pending", "consumed", "revoked")):
                issue("dispatch_identity_invalid", aid)
                continue
            if (not _token(row.get("targetSessionId"))
                    or metadata.get("sourceSessionId") != selected["sessionId"]):
                issue("dispatch_session_unresolved", aid)
            dispatches.append((mid, row))

    matched = {mid: [] for mid, _ in dispatches}
    by_id = {mid: row for mid, row in dispatches if mid not in ambiguous}
    for receipt in inboxes.get(assistant_agent_id, []):
        if not receipt.get("sourceAgentId"):
            continue
        rid = receipt.get("messageId") or receipt.get("eventId")
        metadata = _metadata(receipt)
        reply = metadata.get("replyToMessageId")
        dispatch = by_id.get(reply) if _token(reply) else None
        valid = (_token(rid) and rid not in ambiguous and dispatch is not None
            and _token(dispatch.get("targetSessionId"))
            and _metadata(dispatch).get("sourceSessionId") == selected["sessionId"]
            and receipt.get("targetAgentId") == assistant_agent_id
            and receipt.get("sourceAgentId") == dispatch["targetAgentId"]
            and metadata.get("sourceSessionId") == dispatch["targetSessionId"]
            and (receipt.get("targetSessionId") or metadata.get("targetSessionId")) == selected["sessionId"])
        task = _task_report(receipt, dispatch) if valid else {}
        if task:
            matched[reply].append({"legacyMessageId": rid, "taskStatus": task["taskStatus"],
                                   "evidenceCount": len(task["evidenceRefs"])})
        else:
            counts["unresolvedReceipts"] += 1
    for mid, row in dispatches:
        receipts = matched[mid]
        # An incomplete scan cannot establish the absence of conflicting IDs
        # or later receipts. Keep all task conclusions unresolved in that case.
        status = _dispatch_task_status(row.get("status", "pending"), receipts) if not issues else "unresolved"
        report["dispatches"].append({"legacyMessageId": mid, "sourceAgentId": assistant_agent_id,
            "targetAgentId": row["targetAgentId"], "targetSessionId": row.get("targetSessionId") or None,
            "sourceSessionId": _metadata(row).get("sourceSessionId") or None, "deliveryStatus": row.get("status", "pending"),
            "taskStatus": status, "receipts": receipts if not issues else [],
            "nativeTaskId": None, "nativeCorrelation": "unresolved"})
    # Recheck the registry and every opened source after aggregation. No proof
    # of quiescence is implied, even if the bounded observation stayed stable.
    for path, before, digest in snapshots:
        try:
            _raw, current_digest = read(path, before[2], remember=False, expected=before)
            if current_digest != digest:
                raise InventoryError("source_changed")
        except (InventoryError, OSError):
            issue("source_changed")
    if issues:
        for item in report["dispatches"]:
            item.update(taskStatus="unresolved", receipts=[])
    report["previewComplete"] = not issues
    return report
