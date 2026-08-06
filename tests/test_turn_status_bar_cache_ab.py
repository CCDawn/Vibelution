"""A/B: prompt-prefix cache hit proxy with vs without Turn Status Bar.

DeepSeek-style automatic prefix cache only hits the shared byte prefix from
token 0. The production status bar is rewritten every iteration; placement at
the **tail** must not shrink the stable body prefix, while mid-list placement
(legacy) freezes hits at the static head.

This suite is deterministic (no live LLM). Metrics approximate provider prefix
cache by comparing serialized consecutive model payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from core.orchestration.turn_status_bar import (
    TURN_STATUS_BAR_HEADER,
    build_turn_status_bar_message,
    collect_turn_status_snapshot,
    strip_turn_status_bar_messages,
    upsert_turn_status_bar_message,
)

Placement = Literal["none", "tail", "mid"]


def _message_role(message: Any) -> str:
    if isinstance(message, SystemMessage):
        return "system"
    if isinstance(message, HumanMessage):
        return "user"
    if isinstance(message, AIMessage):
        return "assistant"
    if isinstance(message, ToolMessage):
        return "tool"
    if isinstance(message, dict):
        return str(message.get("role") or message.get("type") or "unknown")
    return type(message).__name__.lower()


def _message_text(message: Any) -> str:
    if isinstance(message, dict):
        content = message.get("content")
    else:
        content = getattr(message, "content", "")
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or item))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content or "")


def serialize_messages_for_prefix_cache(messages: list[Any]) -> str:
    """Canonical byte-like serialization used as a prefix-cache proxy.

    Order-sensitive; roles and tool_call ids are included so pure-append tool
    trails extend the common prefix the same way automatic provider caches do.
    """

    chunks: list[str] = []
    for message in messages:
        role = _message_role(message)
        text = _message_text(message)
        tool_call_id = ""
        tool_calls = ""
        if isinstance(message, ToolMessage):
            tool_call_id = str(getattr(message, "tool_call_id", "") or "")
        elif isinstance(message, AIMessage):
            raw_calls = getattr(message, "tool_calls", None) or []
            if raw_calls:
                tool_calls = repr(
                    [
                        {
                            "id": str(item.get("id") or ""),
                            "name": str(item.get("name") or ""),
                            "args": item.get("args") if isinstance(item, dict) else {},
                        }
                        for item in raw_calls
                        if isinstance(item, dict)
                    ]
                )
        elif isinstance(message, dict):
            tool_call_id = str(message.get("tool_call_id") or message.get("toolCallId") or "")
        chunks.append(f"[{role}|{tool_call_id}]{text}{tool_calls}")
    return "\n".join(chunks)


def common_prefix_length(left: str, right: str) -> int:
    limit = min(len(left), len(right))
    index = 0
    while index < limit and left[index] == right[index]:
        index += 1
    return index


@dataclass(frozen=True, slots=True)
class PrefixCacheStepMetric:
    step: int
    payload_chars: int
    common_prefix_chars: int
    hit_ratio: float
    new_chars: int
    body_chars: int
    body_common_prefix_chars: int
    body_hit_ratio: float


@dataclass(frozen=True, slots=True)
class PrefixCacheArmResult:
    placement: Placement
    steps: tuple[PrefixCacheStepMetric, ...]
    mean_hit_ratio: float
    final_hit_ratio: float
    mean_payload_chars: float
    mean_body_hit_ratio: float
    final_body_hit_ratio: float


def _status_bar_for_step(step: int) -> SystemMessage:
    snapshot = collect_turn_status_snapshot(
        iteration=step,
        model="deepseek-chat",
        provider="deepseek",
        tool_policy={
            "maxCallsPerTurn": 32,
            "maxCallsPerTurnByModelFamily": {"deepseek": 64},
        },
    )
    # Force budget counters to move each step so the bar body is volatile.
    from dataclasses import replace

    snapshot = replace(
        snapshot,
        tools_used=min(32, step * 2),
        tools_remaining=max(0, 32 - step * 2),
        budget_status="ok" if step * 2 < 28 else "tight",
    )
    return build_turn_status_bar_message(snapshot)


def _apply_status_bar(messages: list[Any], *, step: int, placement: Placement) -> list[Any]:
    if placement == "none":
        return strip_turn_status_bar_messages(messages)
    bar = _status_bar_for_step(step)
    if placement == "tail":
        return upsert_turn_status_bar_message(messages, bar)
    # Legacy / harmful mid placement: rewrite status before the current user.
    cleaned = strip_turn_status_bar_messages(messages)
    if not cleaned:
        return [bar]
    # Insert after first system (if any), before remaining trail — severs tool growth.
    if _message_role(cleaned[0]) == "system" and not str(
        getattr(cleaned[0], "content", "") or ""
    ).startswith(TURN_STATUS_BAR_HEADER):
        return [cleaned[0], bar, *cleaned[1:]]
    return [bar, *cleaned]


def simulate_tool_loop_prefix_metrics(
    *,
    placement: Placement,
    steps: int = 6,
    tool_result_chars: int = 400,
) -> PrefixCacheArmResult:
    """Simulate pure-append tool iterations and score consecutive prefix hits."""

    base: list[Any] = [
        SystemMessage(content="## Stable agent protocol\n" + ("rules.\n" * 40)),
        HumanMessage(content="请在仓库内完成关系抽取并返回证据。"),
    ]
    trail = list(base)
    metrics: list[PrefixCacheStepMetric] = []
    previous_payload = ""
    previous_body = ""

    for step in range(1, steps + 1):
        call_id = f"call-{step}"
        trail = strip_turn_status_bar_messages(trail) + [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": call_id,
                        "name": "grep_search_tool",
                        "args": {"regex_pattern": f"pattern-{step}"},
                    }
                ],
            ),
            ToolMessage(
                content=("evidence-" + str(step) + "-") * max(1, tool_result_chars // 12),
                tool_call_id=call_id,
            ),
        ]
        payload_messages = _apply_status_bar(trail, step=step, placement=placement)
        serialized = serialize_messages_for_prefix_cache(payload_messages)
        body_serialized = serialize_messages_for_prefix_cache(
            strip_turn_status_bar_messages(payload_messages)
        )
        if previous_payload:
            common = common_prefix_length(previous_payload, serialized)
            hit_ratio = common / max(1, len(serialized))
            new_chars = max(0, len(serialized) - common)
            body_common = common_prefix_length(previous_body, body_serialized)
            body_hit = body_common / max(1, len(body_serialized))
        else:
            common = 0
            hit_ratio = 0.0
            new_chars = len(serialized)
            body_common = 0
            body_hit = 0.0
        metrics.append(
            PrefixCacheStepMetric(
                step=step,
                payload_chars=len(serialized),
                common_prefix_chars=common,
                hit_ratio=hit_ratio,
                new_chars=new_chars,
                body_chars=len(body_serialized),
                body_common_prefix_chars=body_common,
                body_hit_ratio=body_hit,
            )
        )
        previous_payload = serialized
        previous_body = body_serialized

    # Step-1 has no previous payload; mean over steps that can hit (2..N).
    hittable = [item for item in metrics if item.step >= 2]
    mean_hit = sum(item.hit_ratio for item in hittable) / max(1, len(hittable))
    final_hit = hittable[-1].hit_ratio if hittable else 0.0
    mean_body_hit = sum(item.body_hit_ratio for item in hittable) / max(1, len(hittable))
    final_body_hit = hittable[-1].body_hit_ratio if hittable else 0.0
    mean_payload = sum(item.payload_chars for item in metrics) / max(1, len(metrics))
    return PrefixCacheArmResult(
        placement=placement,
        steps=tuple(metrics),
        mean_hit_ratio=mean_hit,
        final_hit_ratio=final_hit,
        mean_payload_chars=mean_payload,
        mean_body_hit_ratio=mean_body_hit,
        final_body_hit_ratio=final_body_hit,
    )


def format_ab_report(arms: dict[str, PrefixCacheArmResult]) -> str:
    lines = [
        "Turn Status Bar × Prompt Prefix Cache A/B (deterministic proxy)",
        "=" * 88,
        f"{'arm':<10} {'mean_hit':>9} {'final_hit':>10} {'body_mean':>10} {'body_final':>11} {'mean_payload':>12}",
        "-" * 88,
    ]
    for name, arm in arms.items():
        lines.append(
            f"{name:<10} {arm.mean_hit_ratio:9.3f} {arm.final_hit_ratio:10.3f} "
            f"{arm.mean_body_hit_ratio:10.3f} {arm.final_body_hit_ratio:11.3f} "
            f"{arm.mean_payload_chars:12.0f}"
        )
    lines.append("-" * 88)
    lines.append("hit_ratio = common_prefix_chars(prev, curr) / len(curr)  [full wire payload]")
    lines.append("body_hit  = same metric after stripping Turn Status Bar messages")
    lines.append("placement=tail is production; mid is legacy anti-pattern; none is control.")
    return "\n".join(lines)


def test_ab_status_bar_tail_matches_no_bar_prefix_cache_growth():
    """A/B: production tail status bar must not reduce body prefix-hit vs no bar."""

    off = simulate_tool_loop_prefix_metrics(placement="none", steps=6)
    on_tail = simulate_tool_loop_prefix_metrics(placement="tail", steps=6)

    report = format_ab_report({"none": off, "tail": on_tail})
    assert "body_mean" in report

    # Body (history + tools) growth is identical: pure-append for both arms.
    assert abs(on_tail.mean_body_hit_ratio - off.mean_body_hit_ratio) <= 0.001
    assert abs(on_tail.final_body_hit_ratio - off.final_body_hit_ratio) <= 0.001
    # Once the trail is long, most of the next request is already in the prefix.
    assert off.final_body_hit_ratio >= 0.84
    assert on_tail.final_body_hit_ratio >= 0.84
    # Early steps dilute the mean (new tool page is large vs short history).
    assert off.mean_body_hit_ratio >= 0.70
    assert on_tail.mean_body_hit_ratio >= 0.70

    # Full payload hit is slightly lower with a rewritten tail bar (volatile suffix),
    # but still tracks the control arm once the trail is long.
    assert off.final_hit_ratio >= 0.84
    assert on_tail.final_hit_ratio >= 0.74
    assert on_tail.final_hit_ratio >= off.final_hit_ratio - 0.12
    assert on_tail.mean_payload_chars >= off.mean_payload_chars


def test_ab_status_bar_mid_placement_crushes_prefix_cache_vs_tail():
    """A/B: mid-list status rewrites freeze full-wire prefix; tail does not."""

    on_tail = simulate_tool_loop_prefix_metrics(placement="tail", steps=6)
    on_mid = simulate_tool_loop_prefix_metrics(placement="mid", steps=6)

    report = format_ab_report({"tail": on_tail, "mid": on_mid})
    assert "tail" in report and "mid" in report

    # Mid placement rewrites a volatile block before the growing tool trail, so
    # full-wire common prefix stays near the static head. Tail keeps tool pages
    # inside the prefix. (body_* strips the bar, so mid/tail body hits match.)
    assert on_mid.mean_hit_ratio < on_tail.mean_hit_ratio - 0.10
    assert on_mid.final_hit_ratio < on_tail.final_hit_ratio - 0.10
    assert on_mid.final_hit_ratio < 0.70
    assert on_tail.final_hit_ratio >= 0.72
    assert on_tail.final_body_hit_ratio >= 0.85
    assert abs(on_mid.mean_body_hit_ratio - on_tail.mean_body_hit_ratio) <= 0.001


def test_ab_status_bar_none_vs_tail_tool_trail_stays_in_common_prefix():
    """Body tool trail under tail placement remains a pure prefix of the next body."""

    steps = 5
    base: list[Any] = [
        SystemMessage(content="stable"),
        HumanMessage(content="task"),
    ]
    trail = list(base)
    bodies: list[list[Any]] = []
    for step in range(1, steps + 1):
        call_id = f"c{step}"
        trail = strip_turn_status_bar_messages(trail) + [
            AIMessage(content="", tool_calls=[{"id": call_id, "name": "read_file_tool", "args": {}}]),
            ToolMessage(content=f"chunk-{step}", tool_call_id=call_id),
        ]
        with_bar = upsert_turn_status_bar_message(trail, _status_bar_for_step(step))
        bodies.append(strip_turn_status_bar_messages(with_bar))

    for index in range(1, len(bodies)):
        prev = bodies[index - 1]
        curr = bodies[index]
        assert curr[: len(prev)] == prev
        assert len(curr) == len(prev) + 2


def test_ab_report_prints_readable_summary_for_operators(capsys):
    arms = {
        "none": simulate_tool_loop_prefix_metrics(placement="none", steps=4),
        "tail": simulate_tool_loop_prefix_metrics(placement="tail", steps=4),
        "mid": simulate_tool_loop_prefix_metrics(placement="mid", steps=4),
    }
    print(format_ab_report(arms))
    captured = capsys.readouterr().out
    assert "Turn Status Bar" in captured
    # Full-wire hit: tail >> mid; body hit: tail ≈ none (bar stripped).
    assert arms["tail"].mean_hit_ratio > arms["mid"].mean_hit_ratio
    assert arms["tail"].final_body_hit_ratio >= arms["none"].final_body_hit_ratio - 0.001
