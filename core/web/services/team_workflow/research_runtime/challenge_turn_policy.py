"""Challenge Cup logical-task deadlines for durable Agent dispatch.

The Workflow Ledger outbox remains the clock authority.  This module only
interprets its persisted ``created_at_ms`` and ``last_problem_json`` fields;
it does not create another task, receipt, or state store.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any


def _env_positive_int_ms(env_name: str, default_ms: int) -> int:
    """Read one positive integer millisecond budget from the environment."""

    raw = str(os.environ.get(env_name) or "").strip()
    if not raw:
        return default_ms
    try:
        value = int(raw)
    except ValueError:
        return default_ms
    return value if value > 0 else default_ms


# ---------------------------------------------------------------------------
# Challenge Cup logical-task wall-clock policy.  Every value is milliseconds.
#
# Absolute logical-task deadline derivation priority (highest first):
#   1. the node's explicit deadline contract -- the task-bundle subtask
#      ``deadlineAt`` (UTC-aware, owned by task_bundle_lifecycle; only read
#      here) resolved by the dispatcher;
#   2. the bounded conservative default below when no contract exists.
# Formal Challenge Cup nodes legitimately run 6-15 minutes and a single long
# model call can hold 60-280s, so the default must absorb a full turn chain.
# Non-challenge paths keep no deadline at all (``remaining`` is None).
# ---------------------------------------------------------------------------
CHALLENGE_LOGICAL_TASK_TIMEOUT_MS = _env_positive_int_ms(
    "VIBELUTION_CHALLENGE_LOGICAL_TASK_TIMEOUT_MS",
    1_800_000,
)
# No-progress window: must outlast one in-flight long model call, i.e. the
# governed per-call fence (800s since 2026-09-03) plus margin.
# An actively executing turn refreshes progress via the session-side activity
# signal (turnCurrent), so this window only fires on a truly silent turn.
CHALLENGE_NO_PROGRESS_TIMEOUT_MS = _env_positive_int_ms(
    "VIBELUTION_CHALLENGE_NO_PROGRESS_TIMEOUT_MS",
    900_000,
)
# Per-wait poll window before the durable requeue re-evaluates progress.
CHALLENGE_TURN_WAIT_WINDOW_MS = 120_000

_CHALLENGE_TASK_DEADLINE_AT_MS: ContextVar[int | None] = ContextVar(
    "vibelution_challenge_task_deadline_at_ms",
    default=None,
)
_CHALLENGE_TASK_STARTED_AT_MS: ContextVar[int | None] = ContextVar(
    "vibelution_challenge_task_started_at_ms",
    default=None,
)
_CHALLENGE_TASK_RESUME_PROBLEM: ContextVar[dict[str, Any] | None] = ContextVar(
    "vibelution_challenge_task_resume_problem",
    default=None,
)


class ChallengeTaskDeadlineExceeded(RuntimeError):
    """The current Ledger-owned logical task exhausted its wall-clock budget."""

    def __init__(self, problem: Mapping[str, Any]) -> None:
        self.problem = dict(problem)
        super().__init__(json.dumps(self.problem, ensure_ascii=False, sort_keys=True))


@dataclass(frozen=True)
class ChallengeLiveTurnWaitDecision:
    started_at_ms: int
    waited_ms: int
    no_progress_ms: int
    last_progress_at_ms: int
    progress_fingerprint: str
    progress_advanced: bool
    stop_code: str = ""
    deadline_at_ms: int = 0
    deadline_source: str = ""

    @property
    def should_stop(self) -> bool:
        return bool(self.stop_code)


def _nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _previous_wait_problem(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        payload = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def live_turn_progress_fingerprint(snapshot: Mapping[str, Any] | None) -> str:
    """Hash bounded state facts; heartbeats and raw assistant text are excluded."""

    value = dict(snapshot or {})
    assistant_text = str(value.get("assistantText") or "")
    facts = {
        "terminal": bool(value.get("terminal")),
        "terminalStatus": str(value.get("terminalStatus") or "").strip().lower(),
        "completionSource": str(value.get("completionSource") or "").strip().lower(),
        "lastTurnStatus": str(value.get("lastTurnStatus") or "").strip().lower(),
        "messageCount": _nonnegative_int(value.get("messageCount")),
        "activeTurnId": str(value.get("activeTurnId") or "").strip(),
        "turnCurrent": bool(value.get("turnCurrent")),
        "assistantMessageFound": bool(value.get("assistantMessageFound")),
        "assistantTextChars": len(assistant_text),
        "assistantTextSha256": hashlib.sha256(assistant_text.encode("utf-8")).hexdigest()
        if assistant_text
        else "",
    }
    encoded = json.dumps(
        facts,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def resolve_challenge_task_deadline_at_ms(
    created_at_ms: int,
    *,
    contract_deadline_at_ms: int | None = None,
) -> int:
    """Resolve the absolute logical-task deadline (contract first, default second).

    Priority: an explicit positive ``contract_deadline_at_ms`` (persisted
    ``deadlineAt`` contract) wins even when it is earlier than the bounded
    default -- an expired contract must fail closed.  Without a contract the
    bounded conservative default window from ``created_at_ms`` applies.
    """

    normalized_created = _nonnegative_int(created_at_ms) or int(time.time() * 1000)
    contract_deadline = _nonnegative_int(contract_deadline_at_ms)
    if contract_deadline:
        return contract_deadline
    return normalized_created + CHALLENGE_LOGICAL_TASK_TIMEOUT_MS


def decide_live_turn_wait(
    *,
    now_ms: int,
    created_at_ms: int,
    previous_problem: Any = None,
    snapshot: Mapping[str, Any] | None = None,
    deadline_at_ms: int | None = None,
) -> ChallengeLiveTurnWaitDecision:
    """Evaluate one durable requeue without treating a heartbeat as progress.

    Session-side liveness (``turnCurrent`` -- the session worker is still
    executing this exact turn) counts as progress even when the bounded state
    fingerprint is unchanged: a single long streaming model call legitimately
    holds the snapshot steady for minutes.  Only a turn with no fingerprint
    change AND no in-flight signal can exhaust the no-progress window; the
    absolute contract/default deadline still bounds the whole wait.
    """

    normalized_now = _nonnegative_int(now_ms)
    normalized_created = _nonnegative_int(created_at_ms) or normalized_now
    normalized_created = min(normalized_created, normalized_now)
    waited_ms = max(0, normalized_now - normalized_created)

    previous = _previous_wait_problem(previous_problem)
    previous_fingerprint = (
        str(previous.get("progressFingerprint") or "").strip().lower()
        if str(previous.get("code") or "").strip() == "live_turn_wait"
        else ""
    )
    current_fingerprint = live_turn_progress_fingerprint(snapshot)
    previous_progress_at = _nonnegative_int(previous.get("lastProgressAtMs"))
    if not (normalized_created <= previous_progress_at <= normalized_now):
        previous_progress_at = normalized_created
    progress_advanced = bool(
        previous_fingerprint and previous_fingerprint != current_fingerprint
    )
    turn_in_flight = bool(snapshot.get("turnCurrent"))
    last_progress_at = (
        normalized_now if (progress_advanced or turn_in_flight) else previous_progress_at
    )
    no_progress_ms = max(0, normalized_now - last_progress_at)

    deadline_source = (
        "task_bundle_contract" if _nonnegative_int(deadline_at_ms) else "bounded_default"
    )
    resolved_deadline_at = resolve_challenge_task_deadline_at_ms(
        normalized_created,
        contract_deadline_at_ms=deadline_at_ms,
    )

    stop_code = ""
    if normalized_now >= resolved_deadline_at:
        stop_code = "live_turn_wait_timeout"
    elif no_progress_ms >= CHALLENGE_NO_PROGRESS_TIMEOUT_MS:
        stop_code = "live_turn_no_progress_timeout"
    return ChallengeLiveTurnWaitDecision(
        started_at_ms=normalized_created,
        waited_ms=waited_ms,
        no_progress_ms=no_progress_ms,
        last_progress_at_ms=last_progress_at,
        progress_fingerprint=current_fingerprint,
        progress_advanced=progress_advanced,
        stop_code=stop_code,
        deadline_at_ms=resolved_deadline_at,
        deadline_source=deadline_source,
    )


@contextmanager
def challenge_task_deadline_scope(
    created_at_ms: int,
    *,
    resume_problem: Any = None,
    deadline_at_ms: int | None = None,
) -> Iterator[None]:
    """Expose one Ledger-derived absolute deadline to nested completion code.

    ``deadline_at_ms`` carries the explicit contract resolution from the
    dispatcher.  A nested re-entry without an explicit contract (the canonical
    task clock inside the dispatcher scope) must never move the already
    resolved absolute deadline, so the outer deadline is kept as-is; only an
    explicit contract can establish a different one.
    """

    normalized_created = _nonnegative_int(created_at_ms)
    if not normalized_created:
        normalized_created = int(time.time() * 1000)
    resolved_deadline = resolve_challenge_task_deadline_at_ms(
        normalized_created,
        contract_deadline_at_ms=deadline_at_ms,
    )
    existing_deadline = _CHALLENGE_TASK_DEADLINE_AT_MS.get()
    if deadline_at_ms is None and existing_deadline is not None:
        resolved_deadline = int(existing_deadline)
    started_token = _CHALLENGE_TASK_STARTED_AT_MS.set(normalized_created)
    deadline_token = _CHALLENGE_TASK_DEADLINE_AT_MS.set(resolved_deadline)
    resume_token = _CHALLENGE_TASK_RESUME_PROBLEM.set(
        _previous_wait_problem(resume_problem) or None
    )
    try:
        yield
    finally:
        _CHALLENGE_TASK_RESUME_PROBLEM.reset(resume_token)
        _CHALLENGE_TASK_DEADLINE_AT_MS.reset(deadline_token)
        _CHALLENGE_TASK_STARTED_AT_MS.reset(started_token)


def current_challenge_task_started_at_ms() -> int | None:
    return _CHALLENGE_TASK_STARTED_AT_MS.get()


def current_challenge_task_deadline_at_ms() -> int | None:
    """Return the current absolute deadline without creating a new clock."""

    return _CHALLENGE_TASK_DEADLINE_AT_MS.get()


def current_challenge_task_resume_problem() -> dict[str, Any]:
    return dict(_CHALLENGE_TASK_RESUME_PROBLEM.get() or {})


def remaining_challenge_task_ms(*, now_ms: int | None = None) -> int | None:
    deadline_at_ms = _CHALLENGE_TASK_DEADLINE_AT_MS.get()
    if deadline_at_ms is None:
        return None
    effective_now = int(time.time() * 1000) if now_ms is None else _nonnegative_int(now_ms)
    return max(0, int(deadline_at_ms) - effective_now)


def challenge_deadline_waited_ms(*, now_ms: int | None = None) -> int:
    """Elapsed wall clock inside the current logical-task scope (0 if none)."""

    started_at_ms = _CHALLENGE_TASK_STARTED_AT_MS.get()
    if not started_at_ms:
        return 0
    effective_now = int(time.time() * 1000) if now_ms is None else _nonnegative_int(now_ms)
    return max(0, effective_now - int(started_at_ms))


def challenge_deadline_problem(
    *,
    waited_ms: int,
    turn_chain: list[str] | tuple[str, ...] = (),
    max_wait_ms: int | None = None,
) -> dict[str, Any]:
    started_at_ms = _CHALLENGE_TASK_STARTED_AT_MS.get()
    deadline_at_ms = _CHALLENGE_TASK_DEADLINE_AT_MS.get()
    derived_max_wait_ms = (
        int(deadline_at_ms) - int(started_at_ms)
        if started_at_ms and deadline_at_ms and deadline_at_ms >= started_at_ms
        else 0
    )
    effective_max_wait_ms = (
        _nonnegative_int(max_wait_ms)
        or derived_max_wait_ms
        or CHALLENGE_LOGICAL_TASK_TIMEOUT_MS
    )
    return {
        "code": "challenge_logical_task_deadline_exhausted",
        "waitedMs": max(0, int(waited_ms or 0)),
        "maxWaitMs": effective_max_wait_ms,
        "turnChain": [str(item or "").strip() for item in turn_chain if str(item or "").strip()],
    }
