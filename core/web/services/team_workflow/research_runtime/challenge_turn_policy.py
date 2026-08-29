"""Challenge Cup logical-task deadlines for durable Agent dispatch.

The Workflow Ledger outbox remains the clock authority.  This module only
interprets its persisted ``created_at_ms`` and ``last_problem_json`` fields;
it does not create another task, receipt, or state store.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator


CHALLENGE_TURN_WAIT_WINDOW_MS = 120_000
CHALLENGE_NO_PROGRESS_TIMEOUT_MS = 180_000
CHALLENGE_LOGICAL_TASK_TIMEOUT_MS = 300_000

_CHALLENGE_TASK_DEADLINE_AT_MS: ContextVar[int | None] = ContextVar(
    "vibelution_challenge_task_deadline_at_ms",
    default=None,
)
_CHALLENGE_TASK_STARTED_AT_MS: ContextVar[int | None] = ContextVar(
    "vibelution_challenge_task_started_at_ms",
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


def decide_live_turn_wait(
    *,
    now_ms: int,
    created_at_ms: int,
    previous_problem: Any = None,
    snapshot: Mapping[str, Any] | None = None,
) -> ChallengeLiveTurnWaitDecision:
    """Evaluate one durable requeue without treating a heartbeat as progress."""

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
    last_progress_at = normalized_now if progress_advanced else previous_progress_at
    no_progress_ms = max(0, normalized_now - last_progress_at)

    stop_code = ""
    if waited_ms >= CHALLENGE_LOGICAL_TASK_TIMEOUT_MS:
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
    )


@contextmanager
def challenge_task_deadline_scope(created_at_ms: int) -> Iterator[None]:
    """Expose one Ledger-derived absolute deadline to nested completion code."""

    normalized_created = _nonnegative_int(created_at_ms)
    if not normalized_created:
        normalized_created = int(time.time() * 1000)
    started_token = _CHALLENGE_TASK_STARTED_AT_MS.set(normalized_created)
    deadline_token = _CHALLENGE_TASK_DEADLINE_AT_MS.set(
        normalized_created + CHALLENGE_LOGICAL_TASK_TIMEOUT_MS
    )
    try:
        yield
    finally:
        _CHALLENGE_TASK_DEADLINE_AT_MS.reset(deadline_token)
        _CHALLENGE_TASK_STARTED_AT_MS.reset(started_token)


def current_challenge_task_started_at_ms() -> int | None:
    return _CHALLENGE_TASK_STARTED_AT_MS.get()


def remaining_challenge_task_ms(*, now_ms: int | None = None) -> int | None:
    deadline_at_ms = _CHALLENGE_TASK_DEADLINE_AT_MS.get()
    if deadline_at_ms is None:
        return None
    effective_now = int(time.time() * 1000) if now_ms is None else _nonnegative_int(now_ms)
    return max(0, int(deadline_at_ms) - effective_now)


def challenge_deadline_problem(
    *,
    waited_ms: int,
    turn_chain: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "code": "challenge_logical_task_deadline_exhausted",
        "waitedMs": max(0, int(waited_ms or 0)),
        "maxWaitMs": CHALLENGE_LOGICAL_TASK_TIMEOUT_MS,
        "turnChain": [str(item or "").strip() for item in turn_chain if str(item or "").strip()],
    }
