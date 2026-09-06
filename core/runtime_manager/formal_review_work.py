"""Process-owned formal review activity, separate from research result receipts."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import os
from typing import Any, Mapping

import psutil

from .work_run_store import WorkRunStore

KIND = "formal_review"


def _store() -> WorkRunStore:
    return WorkRunStore()


def is_live(snapshot: Mapping[str, Any]) -> bool:
    """A dead/replaced backend cannot retain an active provider invocation."""
    try:
        return abs(psutil.Process(int(snapshot["ownerPid"])).create_time()
                   - float(snapshot["ownerCreateTime"])) < 0.01
    except (KeyError, TypeError, ValueError, psutil.NoSuchProcess):
        return False
    except psutil.AccessDenied:
        return True


def summary() -> dict[str, Any]:
    store = _store()
    active = [item for item in store.load_active_snapshots(KIND) if is_live(item)]
    return {"active": active[-1] if active else None,
            "activeItems": active, "latest": store.load_latest_snapshot(KIND)}


@contextmanager
def active_formal_review(receipt_context: Mapping[str, Any], *, purpose: str):
    invocation_id = str(receipt_context["invocationId"])
    binding = receipt_context.get("questionStageBinding") or {}
    run_id = "formal-review-" + hashlib.sha256(invocation_id.encode()).hexdigest()[:24]
    store = _store()
    now = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "runId": run_id, "runKind": KIND, "status": "running",
        "currentPhase": purpose, "startedAt": now, "updatedAt": now,
        "ownerPid": os.getpid(), "ownerCreateTime": psutil.Process().create_time(),
        "invocationId": invocation_id, "leases": ["evaluation"],
        **{key: str(binding.get(key) or "") for key in
           ("workflowRunId", "questionId", "sessionId", "turnId")},
    }
    store.persist_snapshot(KIND, snapshot, active_run_id=run_id)
    status = "failed"
    try:
        yield
        status = "completed"
    finally:
        ended = datetime.now(timezone.utc).isoformat()
        store.persist_snapshot(KIND, {**snapshot, "status": status,
                                     "updatedAt": ended, "finishedAt": ended})
