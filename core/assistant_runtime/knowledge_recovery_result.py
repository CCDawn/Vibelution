"""Read main-owned original-ID recovery Job outcomes without dispatching work."""
import hashlib
import re
from pathlib import Path

from .migration_io import pinned_target_directory, read_stable_file, strict_json


def read_recovery_job_result(target_root, operation_id):
    if type(operation_id) is not str or re.fullmatch(r"krec-[a-f0-9]{40}", operation_id) is None:
        return None
    from .knowledge_not_started import read_verified_not_started
    if read_verified_not_started(target_root, operation_id):
        return "not_started"
    directory = Path(target_root).parent / "initial-migration-results"
    try:
        if not directory.exists() and not directory.is_symlink():
            return None
        with pinned_target_directory(directory):
            attempt_seen = False
            for request_id, permitted in ((operation_id + ".attempt", {"unknown"}), (operation_id, {"completed", "partial"})):
                path = directory / (hashlib.sha256(request_id.encode("utf-8")).hexdigest() + ".json")
                if not path.exists() and not path.is_symlink():
                    continue
                row = strict_json(read_stable_file(path, 16384).raw)
                if (type(row) is not dict or set(row) != {"schemaVersion", "request", "binding", "command", "reservationToken"}
                        or type(row["schemaVersion"]) is not int or row["schemaVersion"] != 1
                        or row["binding"] is not None or row["command"] is not None
                        or type(row["reservationToken"]) is not str or re.fullmatch(r"[a-f0-9]{64}", row["reservationToken"]) is None
                        or type(row["request"]) is not dict or set(row["request"]) != {"requestId", "projectId", "operation"}
                        or row["request"]["requestId"] != request_id or row["request"]["operation"] != "start"
                        or row["request"]["projectId"] not in permitted):
                    return "unknown"
                if request_id.endswith(".attempt"):
                    attempt_seen = True
                    continue
                return row["request"]["projectId"] if attempt_seen else "unknown"
        return "unknown" if attempt_seen else None
    except Exception:
        return "unknown"


def read_verified_recovery_job_result(target_root, operation_id):
    """A drained result is useful only while its original Job claim is intact."""
    outcome = read_recovery_job_result(target_root, operation_id)
    if outcome not in ("completed", "partial"):
        return outcome
    try:
        claim = strict_json(read_stable_file(Path(target_root) / "initial_migration_claims" / operation_id / "claim.json", 16384).raw)
        if (type(claim) is not dict or type(claim.get("schemaVersion")) is not int
                or claim != {"schemaVersion": 1, "operationId": operation_id, "category": "knowledge_recovery"}):
            return "unknown"
        return outcome
    except Exception:
        return "unknown"
