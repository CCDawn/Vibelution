"""Per-iteration turn status bar injected into model-visible messages.

The status bar is volatile and rewritten every agent iteration (tools used,
budget_status, iteration index, ...).

Placement is intentionally at the **end of the message list** (after user /
assistant / tool trail), not before the current user. DeepSeek automatic
prefix cache only hits the common byte-prefix; if a changing status block sits
before user+tools, every iteration severs the prefix and prior tool results
never become cache hits — even when the agent loop only appends tool pages.
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


def _coerce_nonnegative_int(value: Any, *, default: int = 0) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        try:
            return max(0, int(default or 0))
        except (TypeError, ValueError):
            return 0


def _reserve_for_verify(max_calls: int) -> int:
    budget = _coerce_nonnegative_int(max_calls)
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
        policy = {"maxCallsPerTurn": _coerce_nonnegative_int(getattr(auth, "max_calls_per_turn", 0))}

    max_from_auth = _coerce_nonnegative_int(getattr(auth, "max_calls_per_turn", 0)) if auth is not None else 0
    used = _coerce_nonnegative_int(getattr(auth, "call_count", 0)) if auth is not None else 0
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
    # Prefer family resolved from the current model/policy when available so a
    # leftover authorization context from another turn cannot mislabel the bar.
    auth_profile = str(getattr(auth, "budget_profile", "") or "").strip() if auth is not None else ""
    budget_profile = family or auth_profile

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
        iteration=_coerce_nonnegative_int(iteration),
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


def _append_budget_section(lines: list[str], snapshot: TurnStatusBarSnapshot) -> None:
    if snapshot.tools_max > 0:
        budget_line = (
            f"- tools: used {snapshot.tools_used}/{snapshot.tools_max}, "
            f"remaining {snapshot.tools_remaining}, "
            f"reserve_for_verify {snapshot.reserve_for_verify}"
        )
    else:
        budget_line = f"- tools: used {snapshot.tools_used}, max unlimited"
    lines.extend(
        [
            "### budget",
            budget_line,
            f"- budget_profile: {snapshot.budget_profile or 'default'}",
            f"- budget_status: {snapshot.budget_status}",
        ]
    )
    if snapshot.model or snapshot.provider or snapshot.profile_id:
        model_bits = [part for part in (snapshot.model, snapshot.provider, snapshot.profile_id) if part]
        lines.append(f"- model: {' · '.join(model_bits)}")
    if snapshot.iteration:
        lines.append(f"- iteration: {snapshot.iteration}")
    if snapshot.turn_id:
        lines.append(f"- turn_id: {snapshot.turn_id}")
    if snapshot.mental_enabled:
        lines.append("### mental")
        lines.append("- mental_enabled: true")
        if snapshot.mental_cognitive_state:
            lines.append(f"- cognitive_state: {snapshot.mental_cognitive_state}")
        if snapshot.mental_intervention:
            lines.append(f"- intervention: {snapshot.mental_intervention}")
        else:
            lines.append("- intervention: none (normal)")
    if snapshot.budget_status == "tight":
        lines.append(
            "- action: budget tight — prefer finishing the current step; do not start new exploration branches."
        )
    elif snapshot.budget_status == "exhausted":
        lines.append(
            "- action: budget exhausted — stop tool calls now; next user message resets the quota. "
            "Do not probe further or write a long wrap-up."
        )
    elif snapshot.budget_status == "ok":
        lines.append("- action: prefer structured tools over repeated shell retries.")


def _append_clock_section(lines: list[str], extras: Mapping[str, Any] | None) -> None:
    from datetime import datetime, timezone

    clock = ""
    tz_name = ""
    if isinstance(extras, Mapping):
        clock = str(extras.get("clock") or extras.get("localTime") or "").strip()
        tz_name = str(extras.get("timezone") or extras.get("timeZone") or "").strip()
    if not clock:
        now = datetime.now().astimezone()
        clock = now.isoformat(timespec="seconds")
        if not tz_name:
            tz_name = str(now.tzinfo or timezone.utc)
    lines.append("### clock")
    lines.append(f"- local_time: {clock}")
    if tz_name:
        lines.append(f"- timezone: {tz_name}")


def _append_git_brief_section(lines: list[str], extras: Mapping[str, Any] | None) -> None:
    git = extras.get("git") if isinstance(extras, Mapping) else None
    if not isinstance(git, Mapping):
        return
    lines.append("### git_brief")
    if not bool(git.get("available", True)):
        lines.append(f"- available: false")
        error = str(git.get("error") or "").strip()
        if error:
            lines.append(f"- error: {error[:200]}")
        return
    branch = str(git.get("branch") or "").strip() or "?"
    dirty = bool(git.get("dirty"))
    summary = str(git.get("summary") or "").strip()
    head = str(git.get("headRevShort") or git.get("headRev") or "").strip()
    upstream = git.get("upstream") if isinstance(git.get("upstream"), Mapping) else {}
    ahead = int(upstream.get("ahead") or upstream.get("aheadCount") or 0)
    behind = int(upstream.get("behind") or upstream.get("behindCount") or 0)
    lines.append(f"- branch: {branch}")
    if head:
        lines.append(f"- head: {head}")
    lines.append(f"- dirty: {'yes' if dirty else 'no'}")
    if ahead or behind:
        lines.append(f"- ahead_behind: +{ahead}/-{behind}")
    if summary:
        lines.append(f"- summary: {summary[:240]}")


def _append_git_paths_section(
    lines: list[str],
    extras: Mapping[str, Any] | None,
    *,
    max_paths: int,
) -> None:
    git = extras.get("git") if isinstance(extras, Mapping) else None
    if not isinstance(git, Mapping):
        return
    files = git.get("files") if isinstance(git.get("files"), list) else []
    if not files:
        lines.append("### git_paths")
        lines.append("- paths: (none)")
        return
    cap = max(1, int(max_paths or 12))
    lines.append("### git_paths")
    shown = 0
    for item in files:
        if shown >= cap:
            break
        if not isinstance(item, Mapping):
            continue
        path = str(item.get("path") or item.get("file") or "").strip()
        if not path:
            continue
        status = str(item.get("status") or item.get("changeType") or item.get("xy") or "").strip()
        lines.append(f"- {status or '?'} {path}")
        shown += 1
    total = int(git.get("totalFiles") or len(files) or 0)
    if total > shown:
        lines.append(f"- truncated: showing {shown}/{total}")


def _append_run_digest_section(
    lines: list[str],
    extras: Mapping[str, Any] | None,
    *,
    max_tools: int,
) -> None:
    digest = extras.get("runDigest") if isinstance(extras, Mapping) else None
    if not isinstance(digest, Mapping):
        digest = extras if isinstance(extras, Mapping) else {}
    task = str(digest.get("task") or digest.get("goal") or "").strip()
    tools = digest.get("recentTools") if isinstance(digest.get("recentTools"), list) else []
    if not tools and isinstance(digest.get("tools"), list):
        tools = digest.get("tools")  # type: ignore[assignment]
    cap = max(1, int(max_tools or 8))
    tool_names = [str(item or "").strip() for item in tools if str(item or "").strip()][:cap]
    if not task and not tool_names:
        return
    lines.append("### run_digest")
    if task:
        lines.append(f"- task: {task[:200]}")
    if tool_names:
        lines.append(f"- recent_tools: {', '.join(tool_names)}")


def _append_cache_hint_section(lines: list[str], extras: Mapping[str, Any] | None) -> None:
    cache = extras.get("cacheHint") if isinstance(extras, Mapping) else None
    if not isinstance(cache, Mapping):
        cache = extras.get("promptCache") if isinstance(extras, Mapping) else None
    if not isinstance(cache, Mapping):
        return
    read_hits = cache.get("cacheReadTokens", cache.get("cache_read_tokens", cache.get("read")))
    writes = cache.get("cacheWriteTokens", cache.get("cache_write_tokens", cache.get("write")))
    uncached = cache.get("uncachedInputTokens", cache.get("uncached_input_tokens", cache.get("uncached")))
    if read_hits is None and writes is None and uncached is None:
        return
    lines.append("### cache_hint")
    if read_hits is not None:
        lines.append(f"- cache_read_tokens: {read_hits}")
    if writes is not None:
        lines.append(f"- cache_write_tokens: {writes}")
    if uncached is not None:
        lines.append(f"- uncached_input_tokens: {uncached}")


def _append_identity_section(lines: list[str], snapshot: TurnStatusBarSnapshot, extras: Mapping[str, Any] | None) -> None:
    identity = extras.get("identity") if isinstance(extras, Mapping) else None
    if not isinstance(identity, Mapping):
        identity = extras if isinstance(extras, Mapping) else {}
    session_id = str(identity.get("sessionId") or identity.get("session_id") or "").strip()
    agent_id = str(
        identity.get("agentId") or identity.get("agent_id") or snapshot.agent_id or ""
    ).strip()
    worktree = str(identity.get("worktree") or identity.get("worktreePath") or "").strip()
    if not session_id and not agent_id and not worktree:
        return
    lines.append("### identity")
    if session_id:
        short = session_id if len(session_id) <= 24 else f"{session_id[:10]}…{session_id[-6:]}"
        lines.append(f"- session: {short}")
    if agent_id:
        lines.append(f"- agent: {agent_id}")
    if worktree:
        lines.append(f"- worktree: {worktree[-80:]}")


def format_turn_status_bar(
    snapshot: TurnStatusBarSnapshot,
    *,
    config: Mapping[str, Any] | None = None,
    extras: Mapping[str, Any] | None = None,
) -> str:
    """Human + model readable status block (Chinese-first operational labels).

    ``config`` selects which sections append at the tail (session-level).
    ``extras`` supplies optional live facts (git, clock, cache, identity, digest).
    """

    from core.orchestration.turn_status_tail_config import (
        BLOCK_BUDGET,
        BLOCK_CACHE_HINT,
        BLOCK_CLOCK,
        BLOCK_GIT_BRIEF,
        BLOCK_GIT_PATHS,
        BLOCK_IDENTITY,
        BLOCK_RUN_DIGEST,
        block_enabled,
        normalize_turn_status_tail_config,
    )

    cfg = normalize_turn_status_tail_config(config)
    limits = cfg.get("limits") if isinstance(cfg.get("limits"), Mapping) else {}
    max_tail = int(limits.get("maxTailChars") or 2500)
    max_paths = int(limits.get("gitPathsMax") or 12)
    max_tools = int(limits.get("runDigestToolsMax") or 8)

    lines: list[str] = [
        TURN_STATUS_BAR_HEADER,
        "- purpose: live turn telemetry at message-list tail; do not ignore budget_status",
        "- placement: tail-only (prefix-cache safe)",
    ]

    if block_enabled(cfg, BLOCK_BUDGET):
        _append_budget_section(lines, snapshot)
    if block_enabled(cfg, BLOCK_CLOCK):
        _append_clock_section(lines, extras)
    if block_enabled(cfg, BLOCK_GIT_BRIEF):
        _append_git_brief_section(lines, extras)
    if block_enabled(cfg, BLOCK_GIT_PATHS):
        _append_git_paths_section(lines, extras, max_paths=max_paths)
    if block_enabled(cfg, BLOCK_RUN_DIGEST):
        _append_run_digest_section(lines, extras, max_tools=max_tools)
    if block_enabled(cfg, BLOCK_CACHE_HINT):
        _append_cache_hint_section(lines, extras)
    if block_enabled(cfg, BLOCK_IDENTITY):
        _append_identity_section(lines, snapshot, extras)

    # If user disabled every block but inject is still on, keep a minimal budget line
    # so the model still sees a non-empty status bar header contract.
    if len(lines) <= 3 and block_enabled(cfg, BLOCK_BUDGET) is False:
        lines.append("### status")
        lines.append("- blocks: none selected (tail inject enabled with empty composition)")

    text = "\n".join(lines)
    if len(text) > max_tail:
        text = text[: max(0, max_tail - 48)].rstrip() + "\n- truncated: maxTailChars reached"
    return text


def build_turn_status_bar_message(
    snapshot: TurnStatusBarSnapshot,
    *,
    config: Mapping[str, Any] | None = None,
    extras: Mapping[str, Any] | None = None,
) -> SystemMessage:
    return SystemMessage(
        content=format_turn_status_bar(snapshot, config=config, extras=extras)
    )


def collect_turn_status_tail_extras(
    *,
    session_id: str = "",
    agent_id: str = "",
    task: str = "",
    recent_tools: Sequence[str] | None = None,
    include_git: bool = False,
    cache_hint: Mapping[str, Any] | None = None,
    worktree: str = "",
) -> dict[str, Any]:
    """Best-effort live extras for optional tail sections (failures stay soft)."""

    extras: dict[str, Any] = {
        "identity": {
            "sessionId": str(session_id or "").strip(),
            "agentId": str(agent_id or "").strip(),
            "worktree": str(worktree or "").strip(),
        },
        "runDigest": {
            "task": str(task or "").strip(),
            "recentTools": [str(item).strip() for item in list(recent_tools or []) if str(item).strip()],
        },
    }
    if isinstance(cache_hint, Mapping):
        extras["cacheHint"] = dict(cache_hint)
    if include_git:
        try:
            from core.web.services.git_status_service import get_git_status

            extras["git"] = get_git_status(limit=40)
        except Exception as exc:
            extras["git"] = {"available": False, "error": f"{type(exc).__name__}: {exc}", "files": []}
    return extras


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
    """Replace any previous status bar and append the latest after the full trail.

    Must stay after user/assistant/tool messages so pure-append agent steps can
    extend the provider automatic prefix cache. Inserting a rewritten status bar
    before the current user (legacy placement) freezes cache hits at the static
    head (~system + agent static) and forces every tool page to rebill as miss.
    """

    cleaned = strip_turn_status_bar_messages(messages)
    if status_message is None:
        return cleaned
    return list(cleaned) + [status_message]
