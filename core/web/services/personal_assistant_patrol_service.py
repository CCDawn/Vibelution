"""个人助理派遣心跳巡检（操作成本减负第 2 档）。

PA 派出任务后是纯被动方：``delegationPolicy.allowWakeMessages=False`` 刻意
让「目标 agent 的回复到达」不唤醒 PA（投递失败报告等后台收件箱写入依赖这
个静默语义），过期派遣也没人催。本模块让 PA 侧自己活起来，三个动作全部由
60s 心跳巡检驱动，任何一轮失败只记日志、绝不杀死循环：

1. 自动催办：``sentAt`` 距今超过阈值且 ``receipts`` 为空的 aged 派遣，经
   ``submit_agent_message_event`` 以 PA 身份向目标 agent 发跟进消息
   （source=``pa_followup``，wake_target=True）。催办与普通派遣走同一条
   kernel 通道落到目标 agent 收件箱，PA 自己不用醒；催办内容携带原派遣
   摘要，目标 agent 知道在催什么。
2. 回执消化唤醒：PA inbox 存在未消化的回执类消息（kind=``agent_inbox_reply``
   或 ``metadata.replyToMessageId`` 能对上派遣 messageId）时，逐条直呼
   ``wake_agent_for_inbox_message(..., ignore_delegation_wake_policy=True)``
   唤醒 PA 一次。这是刻意绕开 delegation 唤醒策略闸门的唯一例外路径：
   ``allowWakeMessages=False`` 的全局语义（到达不唤醒 PA）原样保留、此处
   不做任何修改——投递失败报告等后台写入仍依赖它静默；例外只发生在「PA
   自己的派遣已拿到回复、再不消化就永远没人看」这一种情形，并带 15min
   冷却 + 每小时 2 次上限。一次唤醒就是一轮完整 LLM turn，冷却是成本闸。
3. 定时摘要卡：聚合（进行中派遣/逾期待催办/未消化回执）进 humanAttention
   通道（kind=``assistant_digest``，severity=info，targetUrl=/personal-assistant）。
   内容指纹无变化不推新通知、id 每 ``DIGEST_MIN_INTERVAL_SECONDS`` 最多轮转
   一次，行只在 ``DIGEST_FRESHNESS_SECONDS`` 新鲜度窗口内可见后自然淡出。

节流硬要求（全部进程内 dict+RLock，形状仿 delivery-failure 报告器；重启
清零，测试经 ``reset_personal_assistant_patrol_for_tests`` 重置）：

- 催办：每派遣最多 ``MAX_FOLLOWUPS_PER_DISPATCH`` 轮、相邻两轮间隔
  ``>= FOLLOWUP_MIN_INTERVAL_SECONDS``、只催 ``FOLLOWUP_MAX_AGE_SECONDS``
  窗口内的派遣；idempotency_key 派生自 messageId+轮次，同轮重放由 kernel
  幂等账本兜底。
- 唤醒：冷却 ``WAKE_COOLDOWN_SECONDS``、滚动 1 小时最多 ``MAX_WAKES_PER_HOUR``
  次；skipped（busy/in-flight 等未真正起 turn）同样计入窗口——保守侧
  永远安全。
- 摘要：轮转间隔 ``DIGEST_MIN_INTERVAL_SECONDS``。

急停开关（默认开启，显式关闭才停；命名仿 ``VIBELUTION_TURN_STUCK_DETECTION``）：

- ``VIBELUTION_PA_PATROL``：总开关。关闭=循环空转，不催办、不唤醒、不推卡。
- ``VIBELUTION_PA_PATROL_WAKE``：唤醒子开关。关闭=保留催办与摘要卡，只停
  最贵的 PA 唤醒。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 急停开关
# ---------------------------------------------------------------------------

PA_PATROL_ENABLED_ENV = "VIBELUTION_PA_PATROL"
PA_PATROL_WAKE_ENABLED_ENV = "VIBELUTION_PA_PATROL_WAKE"

_DISABLED_TOKENS = frozenset({"0", "false", "off", "no", "disabled"})


def is_pa_patrol_enabled() -> bool:
    """Total switch: enabled unless the env explicitly turns it off."""

    raw = os.environ.get(PA_PATROL_ENABLED_ENV, "").strip().lower()
    return raw not in _DISABLED_TOKENS


def is_pa_patrol_wake_enabled() -> bool:
    """Wake sub-switch: kills only the (expensive) PA wake action."""

    raw = os.environ.get(PA_PATROL_WAKE_ENABLED_ENV, "").strip().lower()
    return raw not in _DISABLED_TOKENS


# ---------------------------------------------------------------------------
# 节流常量
# ---------------------------------------------------------------------------

PATROL_INTERVAL_SECONDS = 60.0

# 催办：阈值/间隔/上限/催办窗口。
FOLLOWUP_INITIAL_AGE_SECONDS = 30 * 60.0
FOLLOWUP_MIN_INTERVAL_SECONDS = 30 * 60.0
MAX_FOLLOWUPS_PER_DISPATCH = 2
FOLLOWUP_MAX_AGE_SECONDS = 24 * 3600.0

# 唤醒：冷却 + 每小时上限。
WAKE_COOLDOWN_SECONDS = 15 * 60.0
MAX_WAKES_PER_HOUR = 2
WAKE_HOUR_WINDOW_SECONDS = 3600.0

# 摘要卡：轮转（=推送一条新通知）间隔 + 行可见新鲜度。
DIGEST_MIN_INTERVAL_SECONDS = 30 * 60.0
DIGEST_FRESHNESS_SECONDS = 30 * 60.0

PATROL_SOURCE = "pa_followup"
_RECEIPT_INBOX_KIND = "agent_inbox_reply"
_PA_PENDING_INBOX_LIMIT = 200

ATTENTION_KIND_ASSISTANT_DIGEST = "assistant_digest"
ATTENTION_SEVERITY_INFO = "info"
ASSISTANT_DIGEST_TARGET_URL = "/personal-assistant"

_TITLE_LIMIT = 80
_BODY_LIMIT = 160
_ID_SEGMENT_LIMIT = 64
_SUMMARY_LIMIT = 200


def _clip(value: Any, *, limit: int = _TITLE_LIMIT) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        return f"{text[: limit - 1]}…"
    return text


def _id_segment(value: Any) -> str:
    return _clip(str(value or "").strip() or "unknown", limit=_ID_SEGMENT_LIMIT).replace(" ", "-")


def _parse_iso_timestamp(value: Any) -> float | None:
    """Epoch seconds for an ISO timestamp; None when absent/unparsable."""

    from .personal_attention_completion_service import _parse_iso_timestamp as _parse

    return _parse(value)


# ---------------------------------------------------------------------------
# 进程内节流状态（重启清零；形状仿 delivery-failure 报告器）
# ---------------------------------------------------------------------------


class _PatrolState:
    """Process-wide followup/wake/digest throttle state."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        # messageId -> {"rounds": int, "last_sent_at": float}
        self.followups: dict[str, dict[str, float]] = {}
        self.wake_last_at: float = 0.0
        self.wake_window: list[float] = []
        self.digest_fingerprint: str = ""
        self.digest_last_rotation: float = 0.0
        self.digest_row: dict[str, str] | None = None

    def reset(self) -> None:
        with self.lock:
            self.followups.clear()
            self.wake_last_at = 0.0
            self.wake_window.clear()
            self.digest_fingerprint = ""
            self.digest_last_rotation = 0.0
            self.digest_row = None


_patrol_state = _PatrolState()


def reset_personal_assistant_patrol_for_tests() -> None:
    """Reset all throttle/digest state between tests (restart semantics)."""

    _patrol_state.reset()


def _followup_gate(state: _PatrolState, message_id: str, *, now: float) -> tuple[bool, int]:
    """Read-only gate: returns (allowed, next_round_index)."""

    with state.lock:
        entry = state.followups.get(message_id)
        rounds = int((entry or {}).get("rounds") or 0)
        if rounds >= MAX_FOLLOWUPS_PER_DISPATCH:
            return False, rounds
        last_sent = float((entry or {}).get("last_sent_at") or 0.0)
        if rounds > 0 and now - last_sent < FOLLOWUP_MIN_INTERVAL_SECONDS:
            return False, rounds
        return True, rounds + 1


def _record_followup(state: _PatrolState, message_id: str, round_index: int, *, now: float) -> None:
    with state.lock:
        state.followups[message_id] = {"rounds": int(round_index), "last_sent_at": float(now)}


def _wake_gate(state: _PatrolState, *, now: float) -> bool:
    with state.lock:
        if state.wake_last_at and now - state.wake_last_at < WAKE_COOLDOWN_SECONDS:
            return False
        hour_ago = now - WAKE_HOUR_WINDOW_SECONDS
        recent = [stamp for stamp in state.wake_window if stamp > hour_ago]
        return len(recent) < MAX_WAKES_PER_HOUR


def _record_wake_attempt(state: _PatrolState, *, now: float) -> None:
    # skipped（busy/in-flight，未真正起 turn）同样计入：保守侧永远安全，
    # 代价只是忙碌时段少试几次。
    with state.lock:
        state.wake_last_at = float(now)
        state.wake_window = [
            stamp for stamp in state.wake_window if stamp > now - WAKE_HOUR_WINDOW_SECONDS
        ]
        state.wake_window.append(float(now))


# ---------------------------------------------------------------------------
# 只读采集（monkeypatch 友好的薄封装）
# ---------------------------------------------------------------------------


def _load_dispatches() -> dict[str, Any]:
    from .personal_assistant_dispatches_service import list_personal_assistant_dispatches

    return list_personal_assistant_dispatches()


def _read_pa_pending_messages(pa_agent_id: str) -> list[dict[str, Any]]:
    from .agent_directory.ops_residual import list_agent_inbox_messages_for_agent

    return list_agent_inbox_messages_for_agent(
        pa_agent_id,
        limit=_PA_PENDING_INBOX_LIMIT,
        status="pending",
        prompt_eligible_only=True,
    )


def _submit_followup_event(**kwargs: Any) -> dict[str, Any]:
    from core.agent_kernel.adapters import submit_agent_message_event

    return submit_agent_message_event(**kwargs)


def _wake_pa(message: dict[str, Any]) -> dict[str, Any]:
    from .session.agent_sessions import wake_agent_for_inbox_message

    return wake_agent_for_inbox_message(message, ignore_delegation_wake_policy=True)


def _text(row: dict[str, Any], key: str) -> str:
    return str((row or {}).get(key) or "").strip()


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    value = (row or {}).get("metadata")
    return value if isinstance(value, dict) else {}


def _is_receipt_like(row: dict[str, Any], dispatch_message_ids: set[str]) -> bool:
    if _text(row, "kind") == _RECEIPT_INBOX_KIND:
        return True
    reply_to = _text(_metadata(row), "replyToMessageId")
    return bool(reply_to) and reply_to in dispatch_message_ids


def find_undigested_receipts(
    pa_agent_id: str,
    dispatch_message_ids: set[str],
) -> list[dict[str, Any]]:
    """Pending, prompt-eligible receipt-like rows in the PA inbox."""

    if not pa_agent_id:
        return []
    rows = _read_pa_pending_messages(pa_agent_id)
    return [
        row
        for row in rows or []
        if isinstance(row, dict) and _is_receipt_like(row, dispatch_message_ids)
    ]


def _dispatch_age_seconds(dispatch: dict[str, Any], *, now: float) -> float | None:
    stamp = _parse_iso_timestamp(_text(dispatch, "sentAt"))
    if stamp is None:
        return None
    return now - stamp


def _is_aged_dispatch(dispatch: dict[str, Any], *, now: float) -> bool:
    """Aged = no receipts, sent long enough ago, still inside the chase window."""

    if dispatch.get("receipts"):
        return False
    message_id = _text(dispatch, "messageId")
    if not message_id:
        return False
    age = _dispatch_age_seconds(dispatch, now=now)
    if age is None:
        return False
    return FOLLOWUP_INITIAL_AGE_SECONDS <= age <= FOLLOWUP_MAX_AGE_SECONDS


# ---------------------------------------------------------------------------
# 动作 1：自动催办
# ---------------------------------------------------------------------------


def _followup_content(dispatch: dict[str, Any], *, round_index: int, age_seconds: float) -> str:
    summary = _clip(_text(dispatch, "summary"), limit=_SUMMARY_LIMIT)
    minutes = max(1, int(age_seconds // 60))
    target_name = _text(dispatch, "targetAgentName") or _text(dispatch, "targetAgentId")
    lines = [
        f"[派遣催办]（第 {round_index} 次跟进）",
        (
            f"个人助理此前派给 {target_name} 的任务已等待约 {minutes} 分钟，"
            "仍未收到回执。"
        ),
    ]
    if summary:
        lines.append(f"原任务摘要: {summary}")
    lines.append(f"派遣消息ID: {_text(dispatch, 'messageId')}")
    lines.append("请尽快处理：已完成请回复回执；仍在进行请简短同步当前状态。")
    return "\n".join(lines)


def _pa_sender() -> dict[str, Any] | None:
    from . import personal_assistant_service

    agent = personal_assistant_service.profile_agent()
    if agent is None:
        return None
    agent_id = _text(agent, "agentId")
    if not agent_id:
        return None
    return {
        "type": "agent",
        "id": agent_id,
        "agentId": agent_id,
        "displayName": _text(agent, "displayName") or _text(agent, "name"),
        "agentCode": _text(agent, "agentCode"),
    }


def send_followup_for_dispatch(
    dispatch: dict[str, Any],
    *,
    round_index: int,
    age_seconds: float,
    pa_sender: dict[str, Any],
) -> dict[str, Any]:
    """Submit one follow-up message to the dispatch target via the kernel."""

    message_id = _text(dispatch, "messageId")
    target_agent_id = _text(dispatch, "targetAgentId")
    summary = _clip(_text(dispatch, "summary"), limit=_SUMMARY_LIMIT)
    content = _followup_content(dispatch, round_index=round_index, age_seconds=age_seconds)
    return _submit_followup_event(
        source=PATROL_SOURCE,
        sender=pa_sender,
        recipient_agent_ids=[target_agent_id],
        content=content,
        correlation_id=_text(dispatch, "threadId") or message_id,
        wake_target=True,
        metadata={
            "sourceSurface": PATROL_SOURCE,
            "inboxKind": PATROL_SOURCE,
            "messageSummary": _clip(f"催办（第 {round_index} 次）：{summary or '派遣未回执'}", limit=_SUMMARY_LIMIT),
            "inboxCreatedBy": "pa_patrol",
            "paFollowupOfMessageId": message_id,
            "paFollowupRound": int(round_index),
        },
        source_id=message_id,
        # 同 (派遣, 轮次) 永远同一个 key：进程内重放与重启后第一轮都由
        # kernel 幂等账本兜底，不会双发。
        idempotency_key=f"pa-followup:{message_id}:{int(round_index)}",
    )


# ---------------------------------------------------------------------------
# 动作 3：定时摘要卡
# ---------------------------------------------------------------------------


def _digest_aggregate(
    *,
    in_flight: int,
    aged_due: int,
    undigested_receipts: int,
) -> dict[str, int]:
    return {
        "inFlightDispatches": max(0, int(in_flight)),
        "agedDueChases": max(0, int(aged_due)),
        "undigestedReceipts": max(0, int(undigested_receipts)),
    }


def _digest_fingerprint(aggregate: dict[str, int]) -> str:
    payload = json.dumps(aggregate, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _digest_row(aggregate: dict[str, int], rotation: float) -> dict[str, str]:
    title = _clip(
        "助理派遣摘要：进行中 {inFlightDispatches} · 逾期待催办 {agedDueChases}"
        " · 未消化回执 {undigestedReceipts}".format(**aggregate)
    )
    body = _clip(
        "个人助理有派遣仍在进行或回执未消化；点击查看派遣面板详情。",
        limit=_BODY_LIMIT,
    )
    return {
        "id": f"assistant-digest:{int(rotation)}",
        "kind": ATTENTION_KIND_ASSISTANT_DIGEST,
        "severity": ATTENTION_SEVERITY_INFO,
        "title": title,
        "targetUrl": ASSISTANT_DIGEST_TARGET_URL,
        "body": body,
    }


def _refresh_digest(
    state: _PatrolState,
    aggregate: dict[str, int],
    *,
    now: float,
) -> tuple[bool, dict[str, str] | None]:
    """Rotate the digest id at most once per interval on fingerprint change.

    Returns ``(rotated, row)``; ``row`` is None when there is no signal at
    all (everything settled → the lane goes quiet instead of showing 0s).
    """

    fingerprint = _digest_fingerprint(aggregate)
    has_signal = any(value > 0 for value in aggregate.values())
    with state.lock:
        if not has_signal:
            state.digest_fingerprint = fingerprint
            state.digest_last_rotation = float(now)
            state.digest_row = None
            return False, None
        rotated = False
        if (
            fingerprint != state.digest_fingerprint
            and now - state.digest_last_rotation >= DIGEST_MIN_INTERVAL_SECONDS
        ):
            state.digest_fingerprint = fingerprint
            state.digest_last_rotation = float(now)
            rotated = True
        row = _digest_row(aggregate, state.digest_last_rotation)
        state.digest_row = row
        return rotated, row


def collect_assistant_digest_attention() -> list[dict[str, str]]:
    """humanAttention source: the current digest row, if fresh and enabled."""

    if not is_pa_patrol_enabled():
        return []
    state = _patrol_state
    with state.lock:
        row = dict(state.digest_row) if state.digest_row else None
        rotated = state.digest_last_rotation
    if row is None:
        return []
    if time.time() - rotated > DIGEST_FRESHNESS_SECONDS:
        return []
    return [row]


# ---------------------------------------------------------------------------
# 巡检主循环
# ---------------------------------------------------------------------------


def patrol_once(*, now: float | None = None) -> dict[str, Any]:
    """One patrol pass: chase aged dispatches, wake on receipts, refresh digest.

    Per-stage failures are logged and swallowed — one bad stage must never
    kill the pass, and one bad pass must never kill the loop.
    """

    observed = time.time() if now is None else float(now)
    if not is_pa_patrol_enabled():
        return {"enabled": False, "wakeEnabled": False, "followupsSent": [], "wake": None, "digest": None}

    from .personal_assistant_dispatches_service import PersonalAssistantDispatchesError

    try:
        listing = _load_dispatches()
    except PersonalAssistantDispatchesError:
        # No assistant identity → nothing to patrol.
        return {"enabled": True, "wakeEnabled": False, "reason": "no_assistant"}
    except Exception as exc:  # noqa: BLE001 - dispatch read failure must not kill the pass
        logger.warning("PA patrol dispatch read failed (%s).", type(exc).__name__)
        return {"enabled": True, "wakeEnabled": False, "reason": "dispatch_read_failed"}

    pa_sender = None
    try:
        pa_sender = _pa_sender()
    except Exception as exc:  # noqa: BLE001
        logger.warning("PA patrol assistant profile read failed (%s).", type(exc).__name__)
    pa_agent_id = str((listing or {}).get("assistantAgentId") or (pa_sender or {}).get("agentId") or "").strip()

    dispatches = [
        row for row in (listing or {}).get("dispatches") or [] if isinstance(row, dict)
    ]
    dispatch_message_ids = {_text(row, "messageId") for row in dispatches} - {""}

    result: dict[str, Any] = {
        "enabled": True,
        "wakeEnabled": is_pa_patrol_wake_enabled(),
        "agedMessageIds": [],
        "followupsSent": [],
        "wake": None,
        "digest": None,
    }

    # ---- stage 1: follow-ups ----
    try:
        undigested = find_undigested_receipts(pa_agent_id, dispatch_message_ids)
    except Exception as exc:  # noqa: BLE001 - inbox read failure must not kill the pass
        logger.warning("PA patrol inbox read failed (%s).", type(exc).__name__)
        undigested = []

    try:
        aged = [row for row in dispatches if _is_aged_dispatch(row, now=observed)]
        result["agedMessageIds"] = [_text(row, "messageId") for row in aged]
        if pa_sender is not None:
            for dispatch in aged:
                message_id = _text(dispatch, "messageId")
                allowed, next_round = _followup_gate(_patrol_state, message_id, now=observed)
                if not allowed:
                    continue
                age = _dispatch_age_seconds(dispatch, now=observed) or FOLLOWUP_INITIAL_AGE_SECONDS
                try:
                    send_followup_for_dispatch(
                        dispatch,
                        round_index=next_round,
                        age_seconds=age,
                        pa_sender=pa_sender,
                    )
                except Exception as exc:  # noqa: BLE001 - one failed chase must not stop the rest
                    logger.warning(
                        "PA patrol follow-up submit failed. messageId=%s round=%s error=%s",
                        message_id, next_round, type(exc).__name__,
                    )
                    continue
                _record_followup(_patrol_state, message_id, next_round, now=observed)
                result["followupsSent"].append({"messageId": message_id, "round": next_round})
    except Exception as exc:  # noqa: BLE001
        logger.warning("PA patrol follow-up stage failed (%s).", type(exc).__name__)

    # ---- stage 2: receipt digestion wake ----
    try:
        if result["wakeEnabled"] and undigested:
            if _wake_gate(_patrol_state, now=observed):
                newest = max(
                    undigested,
                    key=lambda row: _parse_iso_timestamp(_text(row, "createdAt")) or 0.0,
                )
                wake_message = dict(newest)
                wake_message.setdefault("targetAgentId", pa_agent_id)
                wake_message.setdefault("targetSessionId", "")
                try:
                    delivery = _wake_pa(wake_message)
                except Exception as exc:  # noqa: BLE001 - wake failure must not kill the pass
                    logger.warning("PA patrol wake failed (%s).", type(exc).__name__)
                    delivery = {"wakeStatus": "error", "reason": type(exc).__name__}
                # 无论 started 还是 skipped 都记窗口（见 _record_wake_attempt）。
                _record_wake_attempt(_patrol_state, now=observed)
                result["wake"] = {
                    "attempted": True,
                    "receiptCount": len(undigested),
                    "delivery": delivery,
                }
            else:
                result["wake"] = {"attempted": False, "reason": "throttled", "receiptCount": len(undigested)}
        elif undigested:
            result["wake"] = {"attempted": False, "reason": "wake_disabled", "receiptCount": len(undigested)}
    except Exception as exc:  # noqa: BLE001
        logger.warning("PA patrol wake stage failed (%s).", type(exc).__name__)

    # ---- stage 3: digest card ----
    try:
        aged_with_budget = 0
        for message_id in result["agedMessageIds"]:
            allowed, _round = _followup_gate(_patrol_state, message_id, now=observed)
            if allowed:
                aged_with_budget += 1
        in_flight = sum(1 for row in dispatches if not row.get("receipts"))
        aggregate = _digest_aggregate(
            in_flight=in_flight,
            aged_due=aged_with_budget,
            undigested_receipts=len(undigested),
        )
        rotated, row = _refresh_digest(_patrol_state, aggregate, now=observed)
        result["digest"] = {"rotated": rotated, "row": row, "aggregate": aggregate}
    except Exception as exc:  # noqa: BLE001
        logger.warning("PA patrol digest stage failed (%s).", type(exc).__name__)

    return result


async def run_personal_assistant_patrol_forever(
    *,
    interval_seconds: float = PATROL_INTERVAL_SECONDS,
    startup_jobs: Any = None,
) -> None:
    """Forever patrol loop; one bad pass never disables the next one."""

    import asyncio

    interval = max(0.01, float(interval_seconds))
    # Give startup recovery a quiet first interval before the first pass.
    await asyncio.sleep(interval)
    iteration = 0
    while True:
        try:
            if startup_jobs is None:
                await asyncio.to_thread(patrol_once)
            else:
                iteration += 1
                await startup_jobs.run_sync(f"pa-patrol-{iteration}", patrol_once)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - a failed pass must not kill the loop
            logger.warning("PA patrol iteration failed (%s); retrying.", type(exc).__name__)
        await asyncio.sleep(interval)


__all__ = [
    "ASSISTANT_DIGEST_TARGET_URL",
    "ATTENTION_KIND_ASSISTANT_DIGEST",
    "ATTENTION_SEVERITY_INFO",
    "DIGEST_FRESHNESS_SECONDS",
    "DIGEST_MIN_INTERVAL_SECONDS",
    "FOLLOWUP_INITIAL_AGE_SECONDS",
    "FOLLOWUP_MAX_AGE_SECONDS",
    "FOLLOWUP_MIN_INTERVAL_SECONDS",
    "MAX_FOLLOWUPS_PER_DISPATCH",
    "MAX_WAKES_PER_HOUR",
    "PA_PATROL_ENABLED_ENV",
    "PA_PATROL_WAKE_ENABLED_ENV",
    "PATROL_INTERVAL_SECONDS",
    "PATROL_SOURCE",
    "WAKE_COOLDOWN_SECONDS",
    "collect_assistant_digest_attention",
    "find_undigested_receipts",
    "is_pa_patrol_enabled",
    "is_pa_patrol_wake_enabled",
    "patrol_once",
    "reset_personal_assistant_patrol_for_tests",
    "run_personal_assistant_patrol_forever",
    "send_followup_for_dispatch",
]
