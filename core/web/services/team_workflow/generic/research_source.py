"""Bounded references to formal research failures; the Ledger owns execution.

Observation never dispatches or copies source inputs, prompts or transcripts.
Replay uses only the native command admission path, with its readiness and CAS.
"""
from __future__ import annotations

import hashlib
import json
import re
import time

from core.research.workflow.contracts import ActorRef, CommandRequest, WorkflowCommandKind
from core.research.workflow.contracts.retry_taxonomy import DEFAULT_RETRY_TAXONOMY
from core.research.workflow.ledger import RunVersionConflictError
from core.web.services.team_workflow.research_runtime import formal_write_runtime
from core.web.services.team_workflow.research_runtime.archive_mode import challenge_archive_mode_enabled
from core.web.services.team_workflow.research_runtime.command_service import (
    NodeNotReadyError, WorkflowCommandError,
)

from . import store

_ACTIVE = frozenset({"starting", "dispatching", "running", "waiting_human"})
_MAX_SOURCE_ATTEMPTS = 120
_ACTOR = ActorRef("system", "harness-failure-recovery")


def is_source(record: dict) -> bool:
    steps = (record.get("flow") or {}).get("steps") or []
    return len(steps) == 1 and steps[0].get("kind") == "research"


def _source(record: dict) -> tuple[dict, dict]:
    if not is_source(record) or (record["flow"].get("fields") or []):
        raise store.WorkflowError("研究监督只支持无输入字段的单个研究来源步骤。")
    step = record["flow"]["steps"][0]
    source = step.get("researchSource") or {}
    if any(not isinstance(source.get(key), str) or not source[key].strip()
           for key in ("runId", "nodeId")) or not record.get("teamId"):
        raise store.WorkflowError("研究来源需要精确的 Team、runId 和 nodeId。")
    return step, source


def _object(raw: str | None) -> dict:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _code(attempt) -> str:
    code = _object(attempt.problem_json).get("code")
    return code if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,127}", code) else ""


def _identity(record: dict, key: str) -> str:
    return hashlib.sha256(json.dumps(
        [record["teamId"], record["id"], key], ensure_ascii=True,
        separators=(",", ":"),
    ).encode()).hexdigest()


def _retry_limit(run) -> int | None:
    # Launch policy is immutable; safety_limits is only an operator extension
    # delta. Legacy runs may carry the full limit in safety_limits instead.
    policy = _object(run.input_snapshot_json).get("budgetPolicy") or {}
    if not isinstance(policy, dict):
        return None
    limits = _object(run.safety_limits_json)
    values = []
    for source in (policy, limits):
        value = source.get("maxRetries", source.get("autoRetries"))
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        values.append(value)
    return max(values) if values else None


def _accepted(command, *, team_id: str, node_id: str, key: str) -> bool:
    return (command.team_id == team_id and command.node_id == node_id
            and command.command_kind == WorkflowCommandKind.RETRY_NODE.value
            and command.status in {"accepted", "completed"}
            and _object(command.request_json).get("payload") == {
                "reason": "harness-failure-recovery", "retryOfNodeRunId": key}
            and _object(command.requested_by_json) == _ACTOR.to_dict())


def _load(repository, record: dict) -> tuple[dict, object, object]:
    from .service import MAX_ATTEMPTS

    step, source = _source(record)
    run = repository.get_run(source["runId"])
    if run is None or run.team_id != record["teamId"]:
        raise store.WorkflowError("研究来源不存在或不属于当前 Team。")
    all_attempts = repository.list_attempts(run.run_id)
    attempts = [item for item in all_attempts if item.node_id == source["nodeId"]]
    if not attempts:
        raise store.WorkflowError("研究来源节点没有真实 Ledger attempt。")
    latest = max(attempts, key=lambda item: item.attempt)
    by_id = {item.node_run_id: item for item in attempts}
    lineage = []
    current = latest
    seen = set()
    invalid_lineage = False
    while current is not None:
        if (len(lineage) >= _MAX_SOURCE_ATTEMPTS or current.node_run_id in seen or current.run_id != run.run_id
                or current.node_id != source["nodeId"]):
            invalid_lineage = True
            break
        seen.add(current.node_run_id)
        lineage.append(current)
        parent = current.retry_of_node_run_id
        if not parent:
            break
        ancestor = by_id.get(parent)
        if ancestor is None or ancestor.attempt >= current.attempt:
            invalid_lineage = True
            break
        current = ancestor
    lineage.reverse()
    # A disconnected attempt is not evidence for this source's retry chain.
    invalid_lineage |= len(lineage) != len(attempts)
    snapshot = {
        "status": "failed" if latest.status in {"failed", "blocked"} else "running",
        "eligible": False, "reason": "",
        "retryExhausted": False, "sourceAttemptKey": latest.node_run_id,
        "attempts": [{
            "nodeId": step["id"], "number": item.attempt, "agentId": "",
            "sessionId": "", "turnId": "", "key": item.node_run_id,
            "status": {"succeeded": "completed", "cancelled": "stopped",
                       "failed": "failed", "blocked": "failed",
                       "stale": "failed" if _code(item) else "stopped"}.get(item.status, "running"),
            "failureCode": _code(item), "failureOrigin": "native",
        } for item in lineage[-MAX_ATTEMPTS:]],
    }
    if invalid_lineage:
        snapshot["reason"] = "source_lineage_invalid"
        return snapshot, run, latest
    if run.status in {"cancelled", "archived"} or latest.status == "cancelled":
        snapshot.update(status="stopped", reason="source_stopped")
        return snapshot, run, latest
    if latest.status == "succeeded":
        snapshot.update(status="completed", reason="source_step_succeeded")
        return snapshot, run, latest
    if challenge_archive_mode_enabled():
        snapshot["reason"] = "source_archived"
        return snapshot, run, latest
    if run.status == "succeeded":
        snapshot["reason"] = "source_state_inconsistent"
        return snapshot, run, latest
    if (run.status == "waiting_human" or latest.actor_kind == "human"
            or repository.list_pending_human_tasks(run.run_id)):
        snapshot["reason"] = "source_human_required"
        return snapshot, run, latest
    if any(item.status in _ACTIVE for item in all_attempts) or repository.execute(
        "SELECT 1 FROM outbox_actions WHERE run_id = ? AND status IN ('pending','leased') LIMIT 1",
        (run.run_id,),
    ).fetchone():
        snapshot.update(status="running", reason="source_execution_unsettled")
        return snapshot, run, latest
    anchor = repository.get_anchor_by_node_run(latest.node_run_id)
    root_session = _object(anchor[13]).get("rootSession") if anchor else None
    if anchor and (anchor[12] in _ACTIVE or
                   (isinstance(root_session, dict) and root_session.get("status") in
                    {"queued", "running", "stopping", "paused"})):
        snapshot.update(status="running", reason="source_execution_unsettled")
        return snapshot, run, latest
    if latest.status not in {"failed", "blocked"} or run.status not in {"blocked", "failed"}:
        snapshot["reason"] = "source_not_failed"
        return snapshot, run, latest
    snapshot["status"] = "failed"
    if run.active_node_id not in {None, "", source["nodeId"]}:
        snapshot["reason"] = "source_advanced"
        return snapshot, run, latest
    code = _code(latest)
    codes = [code]
    if run_code := _object(run.blocked_problem_json).get("code"):
        codes.append(run_code)
    if not code or any(not isinstance(value, str) or not DEFAULT_RETRY_TAXONOMY.knows(value)
                       for value in codes):
        snapshot["reason"] = "source_problem_unsupported"
        return snapshot, run, latest
    if any(not DEFAULT_RETRY_TAXONOMY.may_auto_retry(value) for value in codes):
        snapshot["reason"] = "source_human_required"
        return snapshot, run, latest
    snapshot["eligible"] = True
    limit = _retry_limit(run)
    if limit is None:
        snapshot.update(eligible=False, reason="source_retry_budget_unavailable")
    else:
        # A retry is charged by its predecessor's outcome. Unknown historical
        # endings stay charged; never relabel them as infrastructure failures.
        charged = sum(DEFAULT_RETRY_TAXONOMY.node_lineage_retry_kind(_code(parent))
                      != "infrastructure_recovery" for parent in lineage[:-1])
        snapshot["retryExhausted"] = charged >= limit
    return snapshot, run, latest


def observe(record: dict) -> dict:
    """Read one consistent Ledger snapshot, returning references only."""
    return formal_write_runtime.get_write_store().read(lambda repo: _load(repo, record)[0])


def _fence(snapshot: dict, record: dict) -> str:
    attempts = record.get("attempts") or []
    if not attempts or snapshot["sourceAttemptKey"] != attempts[-1]["key"]:
        return "source_advanced"
    if snapshot["status"] != "failed":
        return snapshot["reason"] or "source_not_failed"
    return "" if snapshot["eligible"] else snapshot["reason"] or "source_problem_unsupported"


def fence(record: dict) -> str:
    """Prevent repair dispatch after the native source has moved on."""
    try:
        return _fence(observe(record), record)
    except store.WorkflowError:
        return "source_scope_unavailable"
    except Exception:
        return "source_observation_unavailable"


def replay(record: dict) -> str:
    """Submit at most one native retry for the supervised failure identity."""
    from .binding import authorization_reason

    if challenge_archive_mode_enabled():
        return "source_archived"
    if record.get("stopRequested"):
        return "source_stopped"
    policy = (record.get("flow") or {}).get("failureRecovery") or {}
    if not policy.get("bindingId"):
        return "recovery_authorization_unavailable"
    try:
        if reason := authorization_reason(record["teamId"], record):
            return reason
    except Exception:
        return "recovery_authorization_unavailable"
    if policy.get("replaySafety", "unknown") not in {"read_only", "idempotent"}:
        return "side_effects_unknown"
    attempts = record.get("attempts") or []
    if not attempts:
        return "source_advanced"
    key = record.get("_recoveryReplayAfter") or attempts[-1]["key"]
    identity = _identity(record, key)
    idempotency = "harness-failure-recovery:" + identity
    try:
        ledger = formal_write_runtime.get_write_store()
        snapshot, run, latest = ledger.read(lambda repo: _load(repo, record))
        existing = ledger.get_command_by_idempotency(run.run_id, idempotency)
        if existing is not None:
            if _accepted(existing, team_id=record["teamId"], node_id=latest.node_id, key=key):
                return ""
            return "source_replay_receipt_mismatch"
        if latest.node_run_id != key:
            return "source_advanced"
        if reason := _fence(snapshot, record):
            return reason
        if snapshot["retryExhausted"]:
            return snapshot["reason"] or "source_retry_budget_exhausted"
        request = CommandRequest(
            command_id="cmd-harness-recovery-" + identity[:32],
            run_id=run.run_id, team_id=record["teamId"],
            command=WorkflowCommandKind.RETRY_NODE, node_id=latest.node_id,
            expected_run_version=run.run_version, idempotency_key=idempotency,
            payload={"reason": "harness-failure-recovery", "retryOfNodeRunId": key},
            requested_by=_ACTOR, requested_at_ms=int(time.time() * 1000),
        )
        try:
            receipt = formal_write_runtime.get_command_service().submit(request)
        except Exception:
            # A response can be lost after native commit. Only its durable,
            # exact command receipt proves that this replay already succeeded.
            existing = ledger.get_command_by_idempotency(run.run_id, idempotency)
            if existing and _accepted(existing, team_id=record["teamId"], node_id=latest.node_id, key=key):
                return ""
            raise
        return "" if receipt.status in {"accepted", "completed"} else "source_replay_not_accepted"
    except NodeNotReadyError:
        return "source_node_not_ready"
    except RunVersionConflictError:
        return "source_advanced"
    except store.WorkflowError:
        return "source_scope_unavailable"
    except WorkflowCommandError:
        return "source_replay_not_allowed"
    except Exception:
        return "source_replay_unavailable"
