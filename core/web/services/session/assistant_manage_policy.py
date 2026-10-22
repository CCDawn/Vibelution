"""Risk-tiered delegation policy for the personal assistant manage tool.

The assistant manage tool prompts for every call today. This module splits its
closed action set into two server-owned tiers:

- Low-risk actions (additive or reversible session lifecycle work) support a
  **time-boxed action window**: one approval lets the assistant execute the
  same action class directly for a bounded number of hours.
- High-risk actions (restart, configuration writes, deletes, external grants,
  workflow orchestration) always require per-call approval.

The tier table is a frozen server constant; clients only render it. Windows
are process-local and deliberately do not survive restarts, matching the
existing in-memory session grant semantics.
"""

from __future__ import annotations

from typing import Any, Mapping
import json
import time
from threading import RLock


ASSISTANT_MANAGE_TOOL_NAME = "personal_assistant_manage_tool"

# The closed manage action set; mirrors tools/personal_assistant_tools.py.
ASSISTANT_MANAGE_ACTIONS = frozenset(
    {
        "agent_create", "agent_update", "agent_archive", "session_create",
        "session_update", "session_stop", "session_delete", "knowledge_acl_grant",
        "restart", "workflow_recovery_bind", "workflow_recovery_revoke", "workflow_start",
    }
)

# Low-risk tier: additive or reversible session lifecycle work only. Anything
# not listed here defaults to the high-risk tier (conservative by design).
ASSISTANT_MANAGE_LOW_RISK_ACTIONS = frozenset(
    {
        "session_create",
        "session_stop",
        "session_update",
    }
)

ASSISTANT_MANAGE_HIGH_RISK_ACTIONS = frozenset(
    ASSISTANT_MANAGE_ACTIONS - ASSISTANT_MANAGE_LOW_RISK_ACTIONS
)

# One approval buys a bounded direct-execution window for the same low-risk
# action class. Four hours covers a working session without outliving it.
DEFAULT_ACTION_WINDOW_SECONDS = 4 * 3600

_MAX_ACTIVE_WINDOWS = 64

_LOCK = RLock()
# (agent_id, action) -> monotonic expiry timestamp
_WINDOWS: dict[tuple[str, str], float] = {}


def _extract_manage_action(tool_args: Mapping[str, Any] | None) -> str:
    """Return the manage action encoded in tool args, or "" when absent/unknown."""

    if not isinstance(tool_args, Mapping):
        return ""
    action = str(tool_args.get("action") or "").strip()
    return action if action in ASSISTANT_MANAGE_ACTIONS else ""


def assistant_action_window_remaining(
    *,
    agent_id: str,
    tool_name: str,
    tool_args: Mapping[str, Any] | None = None,
) -> float:
    """Remaining seconds of an active low-risk action window, else 0.0.

    Non-manage tools and high-risk actions never bypass approval through this
    path; the caller falls through to the ordinary per-call approval flow.
    """

    if str(tool_name or "").strip() != ASSISTANT_MANAGE_TOOL_NAME:
        return 0.0
    action = _extract_manage_action(tool_args)
    if not action:
        return 0.0
    now = time.monotonic()
    with _LOCK:
        expires_at = _WINDOWS.get((str(agent_id or "").strip(), action), 0.0)
    return max(0.0, expires_at - now)


def grant_assistant_action_window(
    *,
    agent_id: str,
    action: str,
    duration_seconds: float = DEFAULT_ACTION_WINDOW_SECONDS,
) -> float:
    """Open (or extend) the action window for one low-risk action class.

    Returns the granted remaining seconds. Raises ``ValueError`` for unknown
    or high-risk actions so an over-broad caller cannot widen the tier table.
    """

    normalized_action = str(action or "").strip()
    if normalized_action not in ASSISTANT_MANAGE_LOW_RISK_ACTIONS:
        raise ValueError(f"action is not eligible for an action window: {normalized_action or '<empty>'}")
    duration = float(duration_seconds)
    if duration <= 0:
        raise ValueError("action window duration must be positive")
    now = time.monotonic()
    with _LOCK:
        # Drop expired entries so the store stays bounded before pruning.
        for key in [key for key, expires_at in _WINDOWS.items() if expires_at <= now]:
            _WINDOWS.pop(key, None)
        key = (str(agent_id or "").strip(), normalized_action)
        current = _WINDOWS.get(key, 0.0)
        expires_at = max(current, now + duration)
        _WINDOWS[key] = expires_at
        while len(_WINDOWS) > _MAX_ACTIVE_WINDOWS:
            oldest_key = min(_WINDOWS, key=lambda item: _WINDOWS[item])
            _WINDOWS.pop(oldest_key, None)
        return max(0.0, expires_at - now)


def active_assistant_action_windows(agent_id: str) -> dict[str, float]:
    """Remaining seconds per low-risk action with an active window, for display."""

    normalized_agent = str(agent_id or "").strip()
    now = time.monotonic()
    with _LOCK:
        return {
            action: max(0.0, expires_at - now)
            for (agent, action), expires_at in _WINDOWS.items()
            if agent == normalized_agent and expires_at > now
        }


def assistant_action_window_projection(
    *,
    agent_id: str,
    tool_name: str,
    argument_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Approval-card projection for the manage tool; ``None`` for other tools.

    ``eligible`` marks low-risk actions that may receive a window grant;
    ``activeWindows`` lists the already-delegated low-risk actions with their
    remaining seconds so the approval card can render the remaining
    authorization time granted earlier in this run.
    """

    if str(tool_name or "").strip() != ASSISTANT_MANAGE_TOOL_NAME:
        return None
    action = ""
    summary = argument_summary if isinstance(argument_summary, Mapping) else {}
    raw_action = str(summary.get("assistantAction") or "").strip()
    if raw_action in ASSISTANT_MANAGE_ACTIONS:
        action = raw_action
    if not action:
        # Frozen summary failed validation; keep the card conservative.
        return {"eligible": False, "remainingSeconds": 0, "activeWindows": []}
    remaining = assistant_action_window_remaining(
        agent_id=str(agent_id or "").strip(),
        tool_name=ASSISTANT_MANAGE_TOOL_NAME,
        tool_args={"action": action},
    )
    active = {
        window_action: int(window_remaining)
        for window_action, window_remaining in sorted(
            active_assistant_action_windows(str(agent_id or "").strip()).items()
        )
        if window_remaining > 0
    }
    return {
        "eligible": action in ASSISTANT_MANAGE_LOW_RISK_ACTIONS,
        "remainingSeconds": int(remaining),
        "durationSeconds": int(DEFAULT_ACTION_WINDOW_SECONDS),
        "activeWindows": [
            {"action": window_action, "remainingSeconds": window_remaining}
            for window_action, window_remaining in active.items()
        ],
    }


def reset_assistant_manage_action_windows() -> None:
    """Clear every active window (process restarts and test isolation)."""

    with _LOCK:
        _WINDOWS.clear()
