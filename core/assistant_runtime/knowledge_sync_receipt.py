"""Read a knowledge sync's historical proof without resuming its writer.

The caller must authenticate the registered project and bind these arguments to
the approved persistent intent.  This function does not establish authority,
claim a drained Job, or inspect the current target content.
"""
import hashlib
import re
from pathlib import Path

from .migration_io import migration_target_lock, pinned_target_directory, read_stable_file, strict_json, verify_snapshot


def read_drained_job_result(target_root, operation_id):
    """Read the main-owned receipt written only after the original Job drains."""
    if not isinstance(operation_id, str) or not re.fullmatch(r"(?:initial|ksync)-[a-f0-9]{40}", operation_id):
        return None
    try:
        directory = Path(target_root).parent / "initial-migration-results"
        path = directory / (hashlib.sha256(operation_id.encode("utf-8")).hexdigest() + ".json")
        if not directory.exists() and not directory.is_symlink():
            return None
        with pinned_target_directory(directory):
            if not path.exists() and not path.is_symlink():
                if not operation_id.startswith("ksync-"):
                    return None
                attempt_id = operation_id + ".attempt"
                attempt_path = directory / (hashlib.sha256(attempt_id.encode("utf-8")).hexdigest() + ".json")
                if not attempt_path.exists() and not attempt_path.is_symlink():
                    return None
                attempt = strict_json(read_stable_file(attempt_path, 16384).raw)
                if (type(attempt) is not dict or set(attempt) != {"schemaVersion", "request", "binding", "command", "reservationToken"}
                        or type(attempt["schemaVersion"]) is not int or attempt["schemaVersion"] != 1
                        or attempt["binding"] is not None or attempt["command"] is not None
                        or type(attempt["reservationToken"]) is not str or re.fullmatch(r"[a-f0-9]{64}", attempt["reservationToken"]) is None
                        or attempt["request"] != {"requestId": attempt_id, "projectId": "unknown", "operation": "start"}):
                    return "unknown"
                return "unknown"
            row = strict_json(read_stable_file(path, 16384).raw)
        if (not isinstance(row, dict) or set(row) != {"schemaVersion", "request", "binding", "command", "reservationToken"}
                or type(row["schemaVersion"]) is not int or row["schemaVersion"] != 1
                or row["binding"] is not None or row["command"] is not None
                or type(row["reservationToken"]) is not str or re.fullmatch(r"[a-f0-9]{64}", row["reservationToken"]) is None
                or type(row["request"]) is not dict or set(row["request"]) != {"requestId", "projectId", "operation"}
                or row["request"]["requestId"] != operation_id or row["request"]["operation"] != "start"
                or row["request"]["projectId"] not in {"completed", "partial"}):
            return "unknown"
        return row["request"]["projectId"]
    except Exception:
        return "unknown"


def read_knowledge_sync_receipt(target_root, *, sync_id, baseline_id, source_scope, target_agent_id):
    from . import migration_knowledge as k
    from .migration_knowledge_sync import _archived_items, _receipt_mappings, _validate_partial_terminal

    unknown = {"syncId": sync_id, "state": "unknown", "readyForCutover": False}
    try:
        if (not isinstance(sync_id, str) or not k._TOKEN.fullmatch(sync_id)
                or not isinstance(baseline_id, str) or not k._TOKEN.fullmatch(baseline_id)
                or sync_id == baseline_id or not isinstance(target_agent_id, str)
                or not k._TOKEN.fullmatch(target_agent_id) or not isinstance(source_scope, dict)
                or set(source_scope) != {"projectId", "instanceId", "agentId"}
                or any(not isinstance(v, str) or not k._TOKEN.fullmatch(v) for v in source_scope.values())):
            return unknown
        root = Path(target_root)
        folder = root / "knowledge_migrations"
        plan_path = folder / "sync_operations" / (k._digest(sync_id) + ".plan.json")
        receipt_path = folder / "sync_operations" / (k._digest(sync_id) + ".complete.json")
        if not plan_path.exists() or not receipt_path.exists():
            return unknown
        with pinned_target_directory(folder), migration_target_lock(folder):
            baseline = k.verify_knowledge_completion(root, baseline_id)
            plan_snapshot = read_stable_file(plan_path, k._MAX_FILE)
            receipt_snapshot = read_stable_file(receipt_path, k._MAX_FILE)
            plan, receipt = strict_json(plan_snapshot.raw), strict_json(receipt_snapshot.raw)
            fields = {"schemaVersion", "syncId", "baselineMigrationId", "baselinePlanSha256", "sourceProofSha256",
                      "sourceScope", "targetAgentId", "sourceKnowledgeItemIds", "updates", "conflictKeys",
                      "pendingCount", "excludedCount", "archiveEntries"}
            if (not isinstance(plan, dict) or set(plan) != fields or type(plan["schemaVersion"]) is not int
                    or plan["schemaVersion"] not in (1, 2, 3) or plan["syncId"] != sync_id
                    or plan["baselineMigrationId"] != baseline_id or plan["baselinePlanSha256"] != baseline["planSha256"]
                    or plan["sourceScope"] != source_scope or baseline["sourceScope"] != source_scope
                    or plan["targetAgentId"] != target_agent_id or baseline["targetAgentId"] != target_agent_id
                    or not isinstance(plan["sourceProofSha256"], str) or not k._SHA256.fullmatch(plan["sourceProofSha256"])
                    or not isinstance(plan["sourceKnowledgeItemIds"], list) or len(plan["sourceKnowledgeItemIds"]) > 4096
                    or any(not isinstance(v, str) or not k._TOKEN.fullmatch(v) for v in plan["sourceKnowledgeItemIds"])
                    or plan["sourceKnowledgeItemIds"] != sorted(set(plan["sourceKnowledgeItemIds"]))
                    or not isinstance(plan["conflictKeys"], list) or len(plan["conflictKeys"]) > 4096
                    or any(not isinstance(v, str) or not k._SHA256.fullmatch(v) for v in plan["conflictKeys"])
                    or plan["conflictKeys"] != sorted(set(plan["conflictKeys"]))
                    or any(type(plan[key]) is not int or not 0 <= plan[key] <= 4096 for key in ("pendingCount", "excludedCount"))
                    or not isinstance(plan["updates"], list) or len(plan["updates"]) > 4096
                    or any(not isinstance(v, dict) or set(v) != {"sourceKnowledgeItemId", "parentKey"}
                           or v["sourceKnowledgeItemId"] not in plan["sourceKnowledgeItemIds"]
                           or not isinstance(v["parentKey"], str) or not k._SHA256.fullmatch(v["parentKey"])
                           for v in plan["updates"])
                    or len({v["sourceKnowledgeItemId"] for v in plan["updates"]}) != len(plan["updates"])
                    or not isinstance(plan["archiveEntries"], list)):
                return unknown
            archived = _archived_items(folder, plan)
            mappings, skipped = _receipt_mappings(plan, receipt)
            _validate_partial_terminal(folder, plan, mappings, skipped, receipt)
            states = []
            for item_id, mapping in zip(plan["sourceKnowledgeItemIds"], mappings):
                if not isinstance(mapping, dict) or mapping.get("sourceKnowledgeItemId") != item_id:
                    return unknown
                origin = {name: mapping.get(name) for name in ("sourceScope", "sourceKnowledgeBaseId", "sourceKnowledgeItemId")}
                snapshot = read_stable_file(folder / (k._digest(origin) + ".json"), k._MAX_FILE)
                state = strict_json(snapshot.raw)
                item = archived.get(item_id)
                if not item:
                    return unknown
                k._validate_state(state, k._item_binding(item, source_scope, plan["sourceProofSha256"], target_agent_id))
                if (state.get("phase") != "published" or state.get("migrationId") != sync_id
                        or state.get("mapping") != mapping or mapping.get("sourceScope") != source_scope
                        or state["binding"].get("targetAgentId") != target_agent_id
                        or state["binding"].get("sourceProofSha256") != plan["sourceProofSha256"]):
                    return unknown
                states.append(snapshot)
            for snapshot in (plan_snapshot, receipt_snapshot, *states):
                verify_snapshot(snapshot)
            pending = plan["pendingCount"] + len(skipped)
            conflicts = len(plan["conflictKeys"])
            return {"syncId": sync_id, "state": "partial" if pending or conflicts or plan["excludedCount"] else "completed",
                    "plannedAppliedCount": len(mappings), "conflictCount": conflicts,
                    "pendingCount": pending, "skippedCount": len(skipped),
                    "excludedCount": plan["excludedCount"], "readyForCutover": False}
    except Exception:
        return unknown
