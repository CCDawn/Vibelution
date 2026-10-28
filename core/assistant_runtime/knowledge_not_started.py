"""Validate a main-owned proof that an incremental Job had no write permit."""
import hashlib
import re
from pathlib import Path

from .migration_io import pinned_target_directory, read_stable_file, strict_json


def read_verified_not_started(target_root, operation_id):
    if type(operation_id) is not str or re.fullmatch(r"(?:ksync|krec)-[a-f0-9]{40}", operation_id) is None:
        return False
    root = Path(target_root)
    directory = root.parent / "initial-migration-results"
    try:
        with pinned_target_directory(directory):
            for request_id, state in ((operation_id + ".attempt", "unknown"), (operation_id, "not_started")):
                path = directory / (hashlib.sha256(request_id.encode("utf-8")).hexdigest() + ".json")
                row = strict_json(read_stable_file(path, 16384).raw)
                if (type(row) is not dict or set(row) != {"schemaVersion", "request", "binding", "command", "reservationToken"}
                        or type(row["schemaVersion"]) is not int or row["schemaVersion"] != 1
                        or row["binding"] is not None or row["command"] is not None
                        or type(row["reservationToken"]) is not str or re.fullmatch(r"[a-f0-9]{64}", row["reservationToken"]) is None
                        or row["request"] != {"requestId": request_id, "projectId": state, "operation": "start"}):
                    return False
        from scripts.assistant_migration_activate import _initial_receipts_or_claim
        category = "knowledge_sync" if operation_id.startswith("ksync-") else "knowledge_recovery"
        if _initial_receipts_or_claim(root, operation_id, category):
            return False
        if category == "knowledge_sync":
            from . import migration_knowledge as k
            from .migration_io import check_path
            folder = root / "knowledge_migrations"
            stem = k._digest(operation_id)
            artifacts = (folder / "sync_items" / stem,
                folder / "sync_operations" / (stem + ".plan.json.lock"),
                folder / "sync_operations" / (stem + ".complete.json.lock"))
            if any(path.exists() or path.is_symlink() for path in artifacts):
                return False
            if folder.exists() or folder.is_symlink():
                check_path(folder)
                states = list(folder.glob("*.json"))
                if len(states) > 4096:
                    return False
                for path in states:
                    state = strict_json(read_stable_file(path, k._MAX_FILE).raw)
                    if not isinstance(state, dict) or not isinstance(state.get("binding"), dict):
                        return False
                    k._validate_state(state, state["binding"])
                    if state.get("migrationId") == operation_id:
                        return False
        return True
    except Exception:
        return False
