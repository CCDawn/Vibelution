"""Per-iteration turn status bar injected into model-visible messages.

The status bar is volatile: it is rewritten every agent iteration so the model
can observe live budget / progress without polluting the cacheable system
prefix or durable chat history.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from langchain_core.messages import SystemMessage

from core.orchestration.tool_budget_profiles import detect_model_family, resolve_max_calls_per_turn

TURN_STATUS_BAR_HEADER = "## Turn Status Bar"


@dataclass(frozen=True, slots=True)
class TurnStatusBarSnapshot:
    iteration: int = 0
    tools_used: int = 0
    tools_max: int = 0
    tools_remaining: int = 0
    reserve_for_verify: int = 0
    budget_profile: str = "default"
    budget_status: str = "unknown"  # unknown | ok | tight | exhausted | unlimited
    model: str = ""
    provider: str = ""
    profile_id: str = ""
    turn_id: str = ""
    agent_id: str = ""
    mental_enabled: bool = False
    mental_cognitive_state: str = ""
    mental_intervention: str = ""


def _reserve_for_verify(max_calls: int) -> int:
    budget = max(0, int(max_calls or 0))
    if budget <= 0:
        return 0
    return max(2, min(3, budget // 8 or 2))


def _budget_status(*, used: int, max_calls: int, remaining: int, reserve: int) -> str:
    if max_calls <= 0:
        return "unlimited"
    if remaining <= 0 or used >= max_calls:
        return "exhausted"
    if remaining <= reserve:
        return "tight"
    return "ok"


def collect_turn_status_snapshot(
    *,
    iteration: int = 0,
    model: str = "",
    provider: str = "",
    profile_id: str = "",
    tool_policy: Mapping[str, Any] | None = None,
    authorization: Any | None = None,
    mental_enabled: bool = False,
    mental_model: Any | None = None,
) -> TurnStatusBarSnapshot:
    """Build a live snapshot from authorization context + model identity."""

    auth = authorization
    if auth is None:
        try:
            from core.authorization.tool_authorization_service import current_execution_authorization

            auth = current_execution_authorization()
        except Exception:
            auth = None

    policy = tool_policy if isinstance(tool_policy, Mapping) else None
    if policy is None and auth is not None:
        # Fall back to installed max only.
        policy = {"maxCallsPerTurn": int(getattr(auth, "max_calls_per_turn", 0) or 0)}

    max_from_auth = int(getattr(auth, "max_calls_per_turn", 0) or 0) if auth is not None else 0
    used = int(getattr(auth, "call_count", 0) or 0) if auth is not None else 0
    resolved_max, family = resolve_max_calls_per_turn(
        policy,
        model=model,
        provider=provider,
        profile_id=profile_id,
    )
    # Prefer the live authorization cap once installed (already model-resolved).
    tools_max = max_from_auth if auth is not None else resolved_max
    if tools_max < 0:
        tools_max = 0
    remaining = 0 if tools_max <= 0 else max(0, tools_max - used)
    reserve = _reserve_for_verify(tools_max)
    budget_profile = str(getattr(auth, "budget_profile", "") or "").strip() or family

    mental_state = ""
    mental_intervention = ""
    if mental_enabled and mental_model is not None:
        try:
            diagnosis = mental_model.diagnose()
            mental_state = str(getattr(diagnosis, "state", "") or "").strip()
            mental_intervention = str(getattr(diagnosis, "intervention", "") or "").strip()
            # Keep status bar compact: one-line intervention excerpt only.
            if mental_intervention:
                mental_intervention = " ".join(mental_intervention.split())
                if len(mental_intervention) > 240:
                    mental_intervention = f"{mental_intervention[:239].rstrip()}…"
            if mental_state.lower() in {"", "normal"}:
                mental_state = "normal"
                mental_intervention = ""
        except Exception:
            mental_state = ""
            mental_intervention = ""

    return TurnStatusBarSnapshot(
        iteration=max(0, int(iteration or 0)),
        tools_used=max(0, used),
        tools_max=tools_max,
        tools_remaining=remaining,
        reserve_for_verify=reserve,
        budget_profile=budget_profile or detect_model_family(model=model, provider=provider, profile_id=profile_id),
        budget_status=_budget_status(
            used=used,
            max_calls=tools_max,
            remaining=remaining,
            reserve=reserve,
        ),
        model=str(model or "").strip(),
        provider=str(provider or "").strip(),
        profile_id=str(profile_id or "").strip(),
        turn_id=str(getattr(auth, "turn_id", "") or "").strip() if auth is not None else "",
        agent_id=str(getattr(auth, "agent_id", "") or "").strip() if auth is not None else "",
        mental_enabled=bool(mental_enabled),
        mental_cognitive_state=mental_state,
        mental_intervention=mental_intervention,
    )


def format_turn_status_bar(snapshot: TurnStatusBarSnapshot) -> str:
    """Human + model readable status block (Chinese-first operational labels)."""

    if snapshot.tools_max > 0:
        budget_line = (
            f"- tools: used {snapshot.tools_used}/{snapshot.tools_max}, "
            f"remaining {snapshot.tools_remaining}, "
            f"reserve_for_verify {snapshot.reserve_for_verify}"
        )
    else:
        budget_line = f"- tools: used {snapshot.tools_used}, max unlimited"
    lines = [
        TURN_STATUS_BAR_HEADER,
        "- purpose: live turn telemetry; update every model step; do not ignore budget_status",
        budget_line,
        f"- budget_profile: {snapshot.budget_profile or 'default'}",
        f"- budget_status: {snapshot.budget_status}",
    ]
    if snapshot.model or snapshot.provider or snapshot.profile_id:
        model_bits = [part for part in (snapshot.model, snapshot.provider, snapshot.profile_id) if part]
        lines.append(f"- model: {' · '.join(model_bits)}")
    if snapshot.iteration:
        lines.append(f"- iteration: {snapshot.iteration}")
    if snapshot.turn_id:
        lines.append(f"- turn_id: {snapshot.turn_id}")
    if snapshot.mental_enabled:
        lines.append("### mental")
        lines.append(f"- mental_enabled: true")
        if snapshot.mental_cognitive_state:
            lines.append(f"- cognitive_state: {snapshot.mental_cognitive_state}")
        if snapshot.mental_intervention:
            lines.append(f"- intervention: {snapshot.mental_intervention}")
        else:
            lines.append("- intervention: none (normal)")
    if snapshot.budget_status == "tight":
        lines.append(
            "- action: budget tight — stop broad exploration; reserve remaining calls for "
            "lint/test/git or final read-only checks; summarize if verification is impossible."
        )
    elif snapshot.budget_status == "exhausted":
        lines.append(
            "- action: budget exhausted — do not request more tools; summarize current state, "
            "what is done, what is blocked, and the smallest next user action."
        )
    elif snapshot.budget_status == "ok":
        lines.append(
            "- action: prefer structured tools over repeated shell retries; keep reserve_for_verify free."
        )
    return "\n".join(lines)


def build_turn_status_bar_message(snapshot: TurnStatusBarSnapshot) -> SystemMessage:
    return SystemMessage(content=format_turn_status_bar(snapshot))


def is_turn_status_bar_message(message: Any) -> bool:
    content: Any = None
    if isinstance(message, SystemMessage):
        content = getattr(message, "content", None)
    elif isinstance(message, dict):
        role = str(message.get("role") or "").strip().lower()
        if role not in {"system", "user"}:
            return False
        content = message.get("content")
    else:
        return False
    return str(content or "").strip().startswith(TURN_STATUS_BAR_HEADER)


def strip_turn_status_bar_messages(messages: Sequence[Any] | None) -> list[Any]:
    return [message for message in list(messages or []) if not is_turn_status_bar_message(message)]


def upsert_turn_status_bar_message(
    messages: Sequence[Any] | None,
    status_message: Any | None,
) -> list[Any]:
    """Replace any previous status bar and insert the latest before current user."""

    from core.orchestration.turn_outcome import TurnOutcomeController

    cleaned = strip_turn_status_bar_messages(messages)
    if status_message is None:
        return cleaned
    return TurnOutcomeController.insert_volatile_context_before_current_user(
        messages=cleaned,
        context_messages=[status_message],
    )
