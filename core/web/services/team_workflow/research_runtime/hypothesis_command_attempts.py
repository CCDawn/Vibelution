"""Durable attempt ledger and in-process executor for long hypothesis commands.

SCI-049: the ``chain/commands`` POST used to run 60-150s of meeting
orchestration / LLM drafting on the HTTP worker thread while the UI could only
show a static "操作进行中" message.  The command window now returns an
``accepted`` envelope immediately for the three long paths
(``open_generation``/``retry_generation``, ``record_selection``,
``approve_summary``) and executes the real command on a small dedicated
thread pool; the HTTP caller polls the read-only attempt endpoint until the
attempt reaches a terminal status (the same "start -> handle -> poll" shape
Temporal workflows expose to clients).

Design boundaries, kept deliberately narrow:

- The command mutex stays exactly where it was: the background worker re-enters
  :func:`hypothesis_first_chain._execute_v2_command_impl`, which runs the full
  re-authorize + CAS + mutation sequence inside
  ``hypothesis_first_scope_lock``.  Nothing here executes a command body
  outside that lock, and no second authorization or ledger is invented.
- The attempt ledger is append-only JSONL (append + latest-wins by
  ``attemptId``, mirroring ``meeting_driver_work``) next to
  ``hypothesis_first_chain.jsonl``.  It stores one bounded identity plus the
  final response envelope; it is a delivery-status projection of the command,
  never a second command ledger.
- Crash semantics follow the digest crash-fence precedent, not auto re-drive:
  a human-confirmed command is never silently re-executed by a restart sweep.
  Startup recovery only *fences* attempts left ``queued``/``running`` by a
  dead process (foreign boot id or expired lease) as ``failed`` so the UI
  shows a retryable failure instead of a zombie ``accepted``.  The idempotency
  key replay of the owning services makes the operator's retry safe whether or
  not the interrupted attempt had committed side effects.
- Idempotent duplicate submits converge on the attempt row: while an attempt
  is live the same key re-submits return the same ``accepted`` envelope with
  the original ``commandAttemptId``; after success they replay the stored
  response envelope; after failure a new attempt is minted so the operator can
  retry with the same key (the owning services stay the replay authority).
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
ATTEMPT_CONTRACT = "hypothesis-first-command-attempt/v1"
ATTEMPT_RECORD_KIND = "hypothesis_first_command_attempt"

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
_ACTIVE_STATUSES = frozenset({STATUS_QUEUED, STATUS_RUNNING})
_TERMINAL_STATUSES = frozenset({STATUS_SUCCEEDED, STATUS_FAILED})

# Long commands are LLM-bounded (discussion close, digest draft, grounded
# authority materialization).  The lease is a crash fence well beyond those
# budgets, not a heartbeat window: a same-boot running attempt with a valid
# lease is assumed to be alive, everything else is fenceable.
COMMAND_ATTEMPT_LEASE_MS = 30 * 60_000

_COMMAND_MAX_WORKERS_DEFAULT = 2


def _command_max_workers() -> int:
    raw = str(
        os.environ.get("VIBELUTION_HF_COMMAND_MAX_WORKERS") or ""
    ).strip()
    if raw:
        try:
            override = int(float(raw))
        except ValueError:
            return _COMMAND_MAX_WORKERS_DEFAULT
        return max(1, min(4, override))
    return _COMMAND_MAX_WORKERS_DEFAULT


# Dedicated bounded pool: command bodies schedule meeting discussions on the
# governed meeting executor, so they must not compete for those workers.
_COMMAND_EXECUTOR = ThreadPoolExecutor(
    max_workers=_command_max_workers(),
    thread_name_prefix="hypothesis-command",
)

_LOCK = threading.RLock()
_WORKER_BOOT_ID = uuid.uuid4().hex
# In-flight submissions, mirroring meeting_runtime's dedup registry.
_ACTIVE_ATTEMPTS: set[str] = set()


def worker_boot_id() -> str:
    """Process-level boot id stamped onto attempts this process touches."""

    with _LOCK:
        return _WORKER_BOOT_ID


def reset_for_tests() -> str:
    """Test seam: drop in-memory state and rotate the boot id."""

    global _WORKER_BOOT_ID
    with _LOCK:
        _WORKER_BOOT_ID = uuid.uuid4().hex
        _ACTIVE_ATTEMPTS.clear()
        return _WORKER_BOOT_ID


class CommandAttemptError(RuntimeError):
    """Base error for the command attempt ledger."""


def _chain():
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_chain,
    )

    return hypothesis_first_chain


def attempts_path(team_id: str) -> Path:
    """Attempt ledger path sharing the chain's team workspace resolution."""

    chain = _chain()
    return chain._storage_path(team_id).with_name(
        "hypothesis_first_command_attempts.jsonl"
    )


def _append_record(team_id: str, record: dict[str, Any]) -> None:
    # Deliberately NOT chain._append_jsonl: the chain helpers take the chain
    # module lock, which the scope lock holds for a whole command execution —
    # a poll read must never queue behind a 60-150s command. The durability
    # primitives carry only their own brief per-file OS lock.
    from core.web.services.team_workflow.storage_durability import append_jsonl_locked

    append_jsonl_locked(attempts_path(team_id), record)


def _read_records(team_id: str) -> list[dict[str, Any]]:
    from core.web.services.team_workflow.storage_durability import read_jsonl_tolerant

    return read_jsonl_tolerant(attempts_path(team_id))


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Identity: which wire actions run async
# ---------------------------------------------------------------------------

# actionId prefixes minted by the V2 projection for the long commands
# (``_command_action`` derives the default ``command.replace("_", "-")`` id
# plus the explicit ``approve-generation-summary`` / ``open-stage-one-
# generation`` / ``reselect-after-rejection`` overrides).  Drift-safe: the
# gate re-checks the authorized command under the scope lock and falls back
# to the synchronous execution when the inference misses.
_ASYNC_ACTION_ID_PREFIXES: tuple[tuple[str, str], ...] = (
    ("record-selection", "record_selection"),
    ("reselect-after-rejection", "record_selection"),
    ("open-stage-one-generation", "open_generation"),
    ("open-generation", "open_generation"),
    ("retry-generation", "retry_generation"),
    ("approve-generation-summary", "approve_summary"),
    ("approve-summary", "approve_summary"),
)

ASYNC_COMMANDS = frozenset(
    {"open_generation", "retry_generation", "record_selection", "approve_summary"}
)


def infer_async_command(action_id: str, command: str = "") -> str:
    """Return the async command this wire action resolves to, else ``""``.

    An explicit non-empty ``command`` (library callers) wins; wire requests
    carry no ``command`` field, so the projection's actionId prefixes decide.
    """

    normalized_command = str(command or "").strip()
    if normalized_command:
        return normalized_command if normalized_command in ASYNC_COMMANDS else ""
    normalized_action_id = str(action_id or "").strip()
    for prefix, inferred in _ASYNC_ACTION_ID_PREFIXES:
        if normalized_action_id == prefix or normalized_action_id.startswith(
            f"{prefix}:"
        ):
            return inferred
    return ""


# ---------------------------------------------------------------------------
# Attempt identity + reads
# ---------------------------------------------------------------------------


def _attempt_identity(
    *,
    team_id: str,
    question_id: str,
    action_id: str,
    idempotency_key: str,
    workflow_run_id: str,
) -> dict[str, str]:
    return {
        "teamId": str(team_id or "").strip(),
        "questionId": str(question_id or "").strip().upper(),
        "actionId": str(action_id or "").strip(),
        "idempotencyKey": str(idempotency_key or "").strip(),
        "workflowRunId": str(workflow_run_id or "").strip(),
    }


def _same_identity(record: Mapping[str, Any], identity: Mapping[str, str]) -> bool:
    if str(record.get("recordKind") or "") != ATTEMPT_RECORD_KIND:
        return False
    for field in ("teamId", "questionId", "actionId", "idempotencyKey"):
        if str(record.get(field) or "").strip() != str(identity[field]):
            return False
    stored_run_id = str(record.get("workflowRunId") or "").strip()
    return stored_run_id == str(identity["workflowRunId"])


def _latest_by_attempt_id(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        if str(record.get("recordKind") or "") != ATTEMPT_RECORD_KIND:
            continue
        attempt_id = str(record.get("attemptId") or "").strip()
        if attempt_id:
            latest[attempt_id] = record
    return latest


def find_latest_attempt(team_id: str, identity: Mapping[str, str]) -> dict[str, Any] | None:
    """Latest-wins attempt for one command identity (key + scope)."""

    for record in reversed(_read_records(team_id)):
        if _same_identity(record, identity):
            return record
    return None


def _lease_valid(record: Mapping[str, Any], now_ms: int) -> bool:
    if str(record.get("workerBootId") or "").strip() != worker_boot_id():
        return False
    expires_at_ms = record.get("leaseExpiresAtMs")
    if isinstance(expires_at_ms, bool) or not isinstance(expires_at_ms, int):
        return True
    return expires_at_ms <= 0 or now_ms < expires_at_ms


def find_active_attempt_for_question(
    team_id: str,
    question_id: str,
) -> dict[str, Any] | None:
    """Any live (queued / valid-lease running) attempt for one question.

    Latest-wins per attemptId first: superseded transitions (e.g. a running
    record closed by a later failed record) must never read as active.
    """

    normalized_question_id = str(question_id or "").strip().upper()
    now_ms = int(time.time() * 1000)
    for record in _latest_by_attempt_id(_read_records(team_id)).values():
        if str(record.get("questionId") or "").strip().upper() != normalized_question_id:
            continue
        if str(record.get("status") or "") not in _ACTIVE_STATUSES:
            continue
        if _lease_valid(record, now_ms):
            return record
    return None


def get_attempt(team_id: str, attempt_id: str) -> dict[str, Any] | None:
    """Read-model projection of one attempt's latest durable state."""

    normalized_attempt_id = str(attempt_id or "").strip()
    if not normalized_attempt_id:
        return None
    record = _latest_by_attempt_id(_read_records(team_id)).get(normalized_attempt_id)
    if record is None:
        return None
    status = str(record.get("status") or "")
    payload: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "contract": ATTEMPT_CONTRACT,
        "teamId": str(record.get("teamId") or ""),
        "attemptId": normalized_attempt_id,
        "questionId": str(record.get("questionId") or ""),
        "workflowRunId": str(record.get("workflowRunId") or ""),
        "command": str(record.get("command") or ""),
        "actionId": str(record.get("actionId") or ""),
        "idempotencyKey": str(record.get("idempotencyKey") or ""),
        "acceptedStateVersion": str(record.get("acceptedStateVersion") or ""),
        "status": status,
        "createdAt": str(record.get("createdAt") or ""),
        "updatedAt": str(record.get("updatedAt") or ""),
    }
    if status == STATUS_SUCCEEDED:
        payload["result"] = dict(record.get("result") or {})
    if status == STATUS_FAILED:
        error = record.get("error")
        payload["error"] = dict(error) if isinstance(error, Mapping) else {}
    return payload


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def _base_record(identity: Mapping[str, str], *, command: str, attempt_id: str) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "recordKind": ATTEMPT_RECORD_KIND,
        "attemptId": attempt_id,
        "teamId": identity["teamId"],
        "questionId": identity["questionId"],
        "workflowRunId": identity["workflowRunId"],
        "command": str(command or "").strip(),
        "actionId": identity["actionId"],
        "idempotencyKey": identity["idempotencyKey"],
        "workerBootId": worker_boot_id(),
    }


def register_attempt(
    identity: Mapping[str, str],
    *,
    command: str,
    accepted_state_version: str,
) -> dict[str, Any]:
    """Persist the queued intent before the executor accepts the job."""

    now_ms = int(time.time() * 1000)
    record = _base_record(
        identity,
        command=command,
        attempt_id=f"hf2-attempt-{uuid.uuid4().hex[:20]}",
    )
    record.update(
        {
            "status": STATUS_QUEUED,
            "acceptedStateVersion": str(accepted_state_version or ""),
            "createdAt": _utc_now(),
            "updatedAt": _utc_now(),
            "createdAtMs": now_ms,
            "updatedAtMs": now_ms,
            "leaseExpiresAtMs": 0,
        }
    )
    _append_record(identity["teamId"], record)
    return record


def _append_transition(
    previous: Mapping[str, Any],
    *,
    status: str,
    result: dict[str, Any] | None = None,
    error: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    now_ms = int(time.time() * 1000)
    identity = _attempt_identity(
        team_id=str(previous.get("teamId") or ""),
        question_id=str(previous.get("questionId") or ""),
        action_id=str(previous.get("actionId") or ""),
        idempotency_key=str(previous.get("idempotencyKey") or ""),
        workflow_run_id=str(previous.get("workflowRunId") or ""),
    )
    record = _base_record(
        identity,
        command=str(previous.get("command") or ""),
        attempt_id=str(previous.get("attemptId") or ""),
    )
    record.update(
        {
            "status": status,
            "acceptedStateVersion": str(previous.get("acceptedStateVersion") or ""),
            "createdAt": str(previous.get("createdAt") or ""),
            "updatedAt": _utc_now(),
            "createdAtMs": int(previous.get("createdAtMs") or 0) or now_ms,
            "updatedAtMs": now_ms,
            "leaseExpiresAtMs": int(previous.get("leaseExpiresAtMs") or 0),
        }
    )
    if status == STATUS_RUNNING:
        record["workerBootId"] = worker_boot_id()
        record["leaseExpiresAtMs"] = now_ms + COMMAND_ATTEMPT_LEASE_MS
    if result is not None:
        record["result"] = dict(result)
    if error is not None:
        record["error"] = dict(error)
    _append_record(identity["teamId"], record)
    return record


def mark_attempt_running(previous: Mapping[str, Any]) -> dict[str, Any]:
    return _append_transition(previous, status=STATUS_RUNNING)


def finish_attempt(
    previous: Mapping[str, Any],
    *,
    status: str,
    result: dict[str, Any] | None = None,
    error: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if status not in _TERMINAL_STATUSES:
        raise CommandAttemptError(f"unsupported terminal attempt status: {status!r}")
    return _append_transition(previous, status=status, result=result, error=error)


def accepted_envelope(
    attempt: Mapping[str, Any],
    *,
    team_id: str,
    question_id: str,
    workflow_run_id: str,
) -> dict[str, Any]:
    """The fast HTTP response for an accepted long command."""

    return {
        "schemaVersion": 2,
        "teamId": str(team_id or ""),
        "questionId": str(question_id or ""),
        "workflowRunId": str(workflow_run_id or ""),
        "command": str(attempt.get("command") or ""),
        "actionId": str(attempt.get("actionId") or ""),
        "idempotencyKey": str(attempt.get("idempotencyKey") or ""),
        "acceptedStateVersion": str(attempt.get("acceptedStateVersion") or ""),
        "status": "accepted",
        "commandAttemptId": str(attempt.get("attemptId") or ""),
    }


def stored_response_envelope(attempt: Mapping[str, Any]) -> dict[str, Any]:
    """The stored terminal response, replayed verbatim for duplicate submits."""

    result = attempt.get("result")
    return dict(result) if isinstance(result, Mapping) else {}


def submit_execution(
    attempt: Mapping[str, Any],
    run: Callable[[], dict[str, Any]],
) -> None:
    """Queue the command body on the command executor exactly once.

    ``run`` must execute the full authorized command (the chain's
    ``_execute_v2_command_impl``), including its own scope-lock
    re-authorization.  A submit failure fences the attempt ``failed`` and
    re-raises so the HTTP caller surfaces a real error instead of a zombie
    ``accepted``.
    """

    attempt_id = str(attempt.get("attemptId") or "")
    with _LOCK:
        if attempt_id in _ACTIVE_ATTEMPTS:
            return
        _ACTIVE_ATTEMPTS.add(attempt_id)
    try:
        _COMMAND_EXECUTOR.submit(_run_attempt, attempt, run)
    except Exception as exc:
        with _LOCK:
            _ACTIVE_ATTEMPTS.discard(attempt_id)
        finish_attempt(
            attempt,
            status=STATUS_FAILED,
            error={
                "code": "command_attempt_submit_failed",
                "message": f"{type(exc).__name__}: {exc}"[:240],
                "statusCode": 503,
            },
        )
        raise


def _run_attempt(attempt: Mapping[str, Any], run: Callable[[], dict[str, Any]]) -> None:
    attempt_id = str(attempt.get("attemptId") or "")
    running = mark_attempt_running(attempt)
    _record_attempt_event(
        "hypothesis_command.attempt_started",
        outcome="started",
        fields={
            "teamId": str(attempt.get("teamId") or ""),
            "questionId": str(attempt.get("questionId") or ""),
            "command": str(attempt.get("command") or ""),
            "attemptId": attempt_id,
        },
    )
    try:
        response = run()
        if not isinstance(response, Mapping):
            response = {"result": response}
        finish_attempt(running, status=STATUS_SUCCEEDED, result=dict(response))
        _record_attempt_event(
            "hypothesis_command.attempt_succeeded",
            outcome="completed",
            fields={
                "teamId": str(attempt.get("teamId") or ""),
                "questionId": str(attempt.get("questionId") or ""),
                "command": str(attempt.get("command") or ""),
                "attemptId": attempt_id,
            },
        )
    except BaseException as exc:  # noqa: BLE001 - the attempt must reach a terminal state
        finish_attempt(
            running,
            status=STATUS_FAILED,
            error={
                "code": str(getattr(exc, "code", "") or type(exc).__name__)[:80],
                "message": f"{type(exc).__name__}: {exc}"[:240],
                "statusCode": int(getattr(exc, "status_code", 0) or 0) or 422,
            },
        )
        _record_attempt_event(
            "hypothesis_command.attempt_failed",
            outcome="failed",
            level="warning",
            fields={
                "teamId": str(attempt.get("teamId") or ""),
                "questionId": str(attempt.get("questionId") or ""),
                "command": str(attempt.get("command") or ""),
                "attemptId": attempt_id,
                "errorType": type(exc).__name__,
            },
        )
    finally:
        with _LOCK:
            _ACTIVE_ATTEMPTS.discard(attempt_id)


# ---------------------------------------------------------------------------
# Crash recovery
# ---------------------------------------------------------------------------


def _teams_workspace_root() -> Path:
    chain = _chain()
    # Any team id resolves to <teams-root>/<team-id>/research_workflow/...;
    # a probe id inherits the sandbox resolution without duplicating it.
    return chain._storage_path("command-attempt-recovery-probe").parent.parent.parent


def _team_ids_with_attempts() -> list[str]:
    root = _teams_workspace_root()
    if not root.exists():
        return []
    team_ids: list[str] = []
    for attempts_file in sorted(
        root.glob("*/research_workflow/hypothesis_first_command_attempts.jsonl")
    ):
        parts = attempts_file.parts
        # .../<root>/teams/<team-id>/research_workflow/<file>.jsonl
        if len(parts) >= 3 and parts[-3]:
            team_ids.append(parts[-3])
    return team_ids


def recover_interrupted_command_attempts(
    *,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Startup sweep: fence attempts orphaned by a dead process.

    Every latest attempt still ``queued``/``running`` whose worker boot id is
    foreign, or whose crash-fence lease has expired, is marked ``failed`` with
    the stable ``attempt_interrupted`` code so the UI shows a retryable
    failure instead of a zombie ``accepted``.  Same-boot attempts inside a
    valid lease are untouched (their worker thread is this process).  Never
    re-drives: a human-confirmed command is retried by the operator, whose
    idempotency key replay is the safe resume path.  Idempotent and never
    raises; one broken team is isolated into ``skipped``.
    """

    current_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    summary: dict[str, Any] = {
        "teams": 0,
        "attemptsScanned": 0,
        "fenced": 0,
        "skipped": 0,
    }
    try:
        team_ids = _team_ids_with_attempts()
    except Exception:  # noqa: BLE001 - startup sweep must never block boot
        return summary
    for team_id in team_ids:
        summary["teams"] += 1
        try:
            latest = _latest_by_attempt_id(_read_records(team_id))
        except Exception:  # noqa: BLE001 - one broken team cannot stop the sweep
            summary["skipped"] += 1
            continue
        for attempt_id, record in latest.items():
            summary["attemptsScanned"] += 1
            status = str(record.get("status") or "")
            if status not in _ACTIVE_STATUSES:
                summary["skipped"] += 1
                continue
            same_boot = (
                str(record.get("workerBootId") or "").strip() == worker_boot_id()
            )
            if same_boot:
                # This boot owns the record: a running lease proves a live
                # thread, and a same-boot queued record can only belong to a
                # register->submit window the sweep must never race.
                summary["skipped"] += 1
                continue
            if status == STATUS_RUNNING and _lease_valid(record, current_ms):
                # Defensive: _lease_valid is false for foreign boots, so this
                # branch only fires for lease-bearing records a future schema
                # might write without a boot id.
                summary["skipped"] += 1
                continue
            finish_attempt(
                record,
                status=STATUS_FAILED,
                error={
                    "code": "attempt_interrupted",
                    "message": "后端重启中断了该命令的后台执行；请重试。",
                    "statusCode": 503,
                },
            )
            summary["fenced"] += 1
    if summary["fenced"]:
        _record_attempt_event(
            "hypothesis_command.attempt_recovery_swept",
            outcome="completed",
            fields={
                "teams": int(summary["teams"]),
                "attemptsScanned": int(summary["attemptsScanned"]),
                "fenced": int(summary["fenced"]),
                "skipped": int(summary["skipped"]),
            },
        )
    return summary


def _record_attempt_event(
    event_code: str,
    *,
    outcome: str,
    fields: dict[str, Any],
    level: str = "info",
) -> None:
    """Bounded attempt observability; never breaks the command path."""

    try:
        from core.web.services.runtime_scene_service import (
            record_runtime_scene_event_quietly,
        )

        record_runtime_scene_event_quietly(
            "team_workflow_orchestration",
            "hypothesis_command_attempts",
            event_code,
            level=level,
            outcome=outcome,
            fields=fields,
        )
    except Exception:  # noqa: BLE001 - diagnostics must never alter outcomes
        return
