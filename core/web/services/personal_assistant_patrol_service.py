"""个人助理派遣心跳巡检（操作成本减负第 2 档；批三收口环改造）。

PA 派出任务后是纯被动方：``delegationPolicy.allowWakeMessages=False`` 刻意
让「目标 agent 的回复到达」不唤醒 PA（投递失败报告等后台收件箱写入依赖这
个静默语义），过期派遣也没人催。本模块让 PA 侧自己活起来，三个动作全部由
60s 心跳巡检驱动，任何一轮失败只记日志、绝不杀死循环：

1. 自动催办：最近派遣/回执活动超过阈值且任务仍待推进的 aged 派遣，经
   ``submit_agent_message_event`` 以 PA 身份向目标 agent 发跟进消息
   （source=``pa_followup``，wake_target=True）。催办与普通派遣走同一条
   kernel 通道落到目标 agent 收件箱，PA 自己不用醒；催办内容携带原派遣
   摘要，目标 agent 知道在催什么。提交前的 strict 原行正读优先走台账
   信封列比对（``dispatch_envelope_is_current``），台账答不了才回退
   JSONL strict 扫描——不再每轮全文件正读。
2. 回执消化唤醒（批三核心）：「未消化回执」判定以台账为准——
   ``digested_at IS NULL`` 且配对到活跃派遣（直接回复 / 经催办链回指 /
   线程唯一配对），没有回执窗口，出窗回执照样可见照样唤醒；台账不可用
   时回退旧的计数窗口现算。命中时一次唤醒把全部 wake-eligible 回执合并
   进一轮 turn（carrier=最新一条，其余回执摘要并入 prompt content），不再
   一条一轮。这是刻意绕开 delegation 唤醒策略闸门的唯一例外路径：
   ``allowWakeMessages=False`` 的全局语义（到达不唤醒 PA）原样保留、此处
   不做任何修改——投递失败报告等后台写入仍依赖它静默；例外只发生在「PA
   自己的派遣已拿到回复、再不消化就永远没人看」这一种情形，并带 15min
   冷却 + 每小时 2 次上限。一次唤醒就是一轮完整 LLM turn，冷却是成本闸。
   唤醒遵循「先预留后提交」（范本 assistant_runtime/patrol）：提交前把
   ``reserved`` 意图落台账，turn 真正起来（started）才把本批 N 条回执在
   一个事务里全部落 ``digested_at``（全有或全无，不留半消化态）并 consume
   其余回实行；结果不可证（异常）记 ``unknown`` 永不重试、可证未提交
   （skipped 类）记 ``cancelled_pre_admission`` 可重试。
3. 定时摘要卡：聚合（进行中派遣/逾期待催办/未消化回执）进 humanAttention
   通道（kind=``assistant_digest``，severity=info；旧助理页退役后 targetUrl
   置空，点击仅聚焦工作台）。
   内容指纹无变化不推新通知、id 每 ``DIGEST_MIN_INTERVAL_SECONDS`` 最多轮转
   一次，行只在 ``DIGEST_FRESHNESS_SECONDS`` 新鲜度窗口内可见后自然淡出。
   停摆升级：信号持续未处理（派遣一直待确认 / 回执一直没人消化）时，卡过
   新鲜度窗口后按同一节流重新轮转一个新 id 再提醒一次，正文带「已持续
   N 分钟待处理」；不再 30min 后静默消失。信号归零照旧清行。

节流硬要求：

- 催办（进程内 dict+RLock，形状仿 delivery-failure 报告器；测试经
  ``reset_personal_assistant_patrol_for_tests`` 重置）：每派遣最多
  ``MAX_FOLLOWUPS_PER_DISPATCH`` 轮、相邻两轮间隔
  ``>= FOLLOWUP_MIN_INTERVAL_SECONDS``、只催 ``FOLLOWUP_MAX_AGE_SECONDS``
  窗口内的派遣；idempotency_key 派生自 messageId+轮次，同轮重放由 kernel
  幂等账本兜底。
- 唤醒（持久化在台账 ``wake_attempts`` 表，重启不清零不风暴）：冷却
  ``WAKE_COOLDOWN_SECONDS``、滚动 1 小时最多 ``MAX_WAKES_PER_HOUR`` 次；
  只有真实提交（started，或提交与否不可证的 unknown）计入配额——
  busy/skipped 可证未起 turn，不再白白吃配额。台账不可用时回退进程内
  窗口（同样只记真实提交）。
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
from datetime import datetime, timezone
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
# 旧 /personal-assistant 工作台页已退役：摘要卡不再深链，targetUrl 置空，
# 点击 toast 仅聚焦工作台（不跳转具体页面）。
ASSISTANT_DIGEST_TARGET_URL = ""

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


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        # 当前「连续有信号」段的起点（epoch）；0 = 当前无信号。只用于停摆
        # 升级卡正文里的「已持续 N 分钟」，信号归零即清零——不是新持久化，
        # 与其余摘要状态一样重启清零。
        self.digest_signal_since: float = 0.0

    def reset(self) -> None:
        with self.lock:
            self.followups.clear()
            self.wake_last_at = 0.0
            self.wake_window.clear()
            self.digest_fingerprint = ""
            self.digest_last_rotation = 0.0
            self.digest_row = None
            self.digest_signal_since = 0.0


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


def _wake_gate(*, stamps: list[float], now: float) -> bool:
    """Cooldown + hourly cap over real-submission stamps only."""

    if stamps and now - max(stamps) < WAKE_COOLDOWN_SECONDS:
        return False
    hour_ago = now - WAKE_HOUR_WINDOW_SECONDS
    return sum(1 for stamp in stamps if stamp > hour_ago) < MAX_WAKES_PER_HOUR


def _in_memory_wake_stamps(state: _PatrolState) -> list[float]:
    with state.lock:
        stamps = list(state.wake_window)
        if state.wake_last_at and state.wake_last_at not in stamps:
            stamps.append(state.wake_last_at)
        return stamps


def _wake_throttle_stamps(
    state: _PatrolState,
    *,
    ledger_ready: bool,
    now: float,
) -> list[float]:
    """Ledger stamps plus any in-memory fallback stamps, else in-memory only.

    The union matters: a submission whose ledger stamp write failed
    (``complete_wake`` False, e.g. sqlite transient busy) is mirrored into
    the process window, and the gate must honor it even while the ledger
    itself keeps answering. Each submission lands in exactly one store
    (the other is skipped), so the union never double-counts.
    """

    if ledger_ready:
        persisted = _ledger_recent_wake_stamps(
            window_seconds=WAKE_HOUR_WINDOW_SECONDS, now=now
        )
        if persisted is not None:
            stamps = list(persisted)
            for stamp in _in_memory_wake_stamps(state):
                if all(abs(stamp - seen) > 1e-9 for seen in stamps):
                    stamps.append(stamp)
            return stamps
    return _in_memory_wake_stamps(state)


def _record_wake_submission(
    state: _PatrolState,
    *,
    now: float,
    ledger_recorded: bool,
) -> None:
    """Record a real (or unprovably-not-refused) submission toward the quota.

    Skipped attempts (busy/in-flight — provably no turn started) never land
    here. ``ledger_recorded`` must be the actual ``complete_wake`` outcome:
    only a confirmed ledger stamp (``wake_attempts.submitted_at_ms``) skips
    the in-memory mirror — a failed write falls back to it so the gate can
    never lose the submission.
    """

    if ledger_recorded:
        return
    with state.lock:
        state.wake_last_at = float(now)
        state.wake_window = [
            stamp for stamp in state.wake_window if stamp > now - WAKE_HOUR_WINDOW_SECONDS
        ]
        state.wake_window.append(float(now))


# ---------------------------------------------------------------------------
# 台账 seam（批三；monkeypatch 友好的薄封装，失败一律回退 JSONL 语义）
# ---------------------------------------------------------------------------


def _ledger_ready(pa_agent_id: str) -> bool:
    """Change-driven harvest + readiness probe; False on any failure."""

    if not pa_agent_id:
        return False
    try:
        from . import personal_assistant_dispatch_ledger as ledger

        return bool(ledger.ensure_harvested(pa_agent_id))
    except Exception:  # noqa: BLE001 - ledger must never break the patrol
        return False


def _ledger_undigested_receipts(pa_agent_id: str) -> list[dict[str, Any]] | None:
    """Paired undigested receipts (no window); None = ledger cannot answer."""

    try:
        from . import personal_assistant_dispatch_ledger as ledger

        return ledger.undigested_wake_receipts(pa_agent_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("PA patrol ledger undigested query failed (%s).", type(exc).__name__)
        return None


def _ledger_wake_covered() -> dict[str, str]:
    """Receipts covered by non-retryable wake attempts; {} on failure."""

    try:
        from . import personal_assistant_dispatch_ledger as ledger

        return ledger.wake_covered_receipt_ids()
    except Exception as exc:  # noqa: BLE001
        logger.warning("PA patrol ledger coverage read failed (%s).", type(exc).__name__)
        return {}


def _ledger_recent_wake_stamps(*, window_seconds: float, now: float) -> list[float] | None:
    """Persisted submission stamps (seconds); None = ledger cannot answer."""

    try:
        from . import personal_assistant_dispatch_ledger as ledger

        stamps = ledger.recent_wake_submissions(
            window_ms=int(window_seconds * 1000), now_ms=int(now * 1000)
        )
        return [stamp / 1000.0 for stamp in stamps]
    except Exception as exc:  # noqa: BLE001
        logger.warning("PA patrol ledger throttle read failed (%s).", type(exc).__name__)
        return None


def _ledger_reserve_wake(receipt_ids: list[str], *, now: float) -> str | None:
    """Commit the wake intent before submitting; None on failure."""

    try:
        from . import personal_assistant_dispatch_ledger as ledger

        return ledger.reserve_wake(
            receipt_ids,
            reserved_at=_utc_now_iso(),
            reserved_at_ms=int(now * 1000),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("PA patrol wake reservation failed (%s).", type(exc).__name__)
        return None


def _ledger_complete_wake(
    attempt_id: str,
    *,
    state: str,
    reason: str = "",
    submitted_at_ms: float | None = None,
) -> bool:
    try:
        from . import personal_assistant_dispatch_ledger as ledger

        return ledger.complete_wake(
            attempt_id,
            state=state,
            reason=reason,
            submitted_at_ms=None if submitted_at_ms is None else int(submitted_at_ms * 1000),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("PA patrol wake completion failed (%s).", type(exc).__name__)
        return False


def _ledger_mark_digested(receipt_ids: list[str], *, digested_at: str) -> list[str]:
    """All-or-nothing digest marking; the ids on success, [] on failure."""

    try:
        from . import personal_assistant_dispatch_ledger as ledger

        ledger.mark_receipts_digested(receipt_ids, digested_at=digested_at)
        return list(receipt_ids)
    except Exception as exc:  # noqa: BLE001
        logger.warning("PA patrol digest marking failed (%s).", type(exc).__name__)
        return []


def _ledger_dispatch_current(
    message_id: str,
    *,
    source_agent_id: str,
    target_agent_id: str,
    target_session_id: str,
    source_session_id: str,
    thread_id: str,
) -> bool | None:
    """Ledger verdict for the follow-up strict read; None = fall back."""

    try:
        from . import personal_assistant_dispatch_ledger as ledger

        return ledger.dispatch_envelope_is_current(
            message_id,
            source_agent_id=source_agent_id,
            target_agent_id=target_agent_id,
            target_session_id=target_session_id,
            source_session_id=source_session_id,
            thread_id=thread_id,
        )
    except Exception:  # noqa: BLE001 - strict fallback must stay available
        return None


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
    from .personal_assistant_dispatches_service import _metadata as dispatch_metadata

    return dispatch_metadata(row)


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


def _consume_pa_inbox_messages(
    pa_agent_id: str,
    message_ids: list[str],
    *,
    session_id: str = "",
    turn_id: str = "",
) -> list[str]:
    """Consume merged-wake receipts from the PA inbox (best effort per row)."""

    if not message_ids:
        return []
    from .agent_directory.ops_residual import consume_agent_inbox_message

    consumed: list[str] = []
    for message_id in message_ids:
        try:
            consume_agent_inbox_message(
                pa_agent_id,
                message_id,
                consumed_by_session_id=session_id,
                consumed_by_turn_id=turn_id,
            )
            consumed.append(message_id)
        except Exception as exc:  # noqa: BLE001 - one bad row must not stop the batch
            logger.warning(
                "PA patrol wake consume failed. messageId=%s error=%s",
                message_id, type(exc).__name__,
            )
    return consumed


def _collect_undigested_receipts(
    pa_agent_id: str,
    dispatch_message_ids: set[str],
    *,
    ledger_ready: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(all undigested, wake-eligible)`` — ledger-driven when available.

    The ledger query has no receipt window: a paired ``digested_at IS NULL``
    receipt stays wake-eligible no matter how far outside the legacy JSONL
    windows it fell (批三核心目标). Receipt bodies join from the PA inbox
    read for the wake prompt; rows the window cannot see degrade to ledger
    summary text. Receipts covered by a non-retryable wake attempt stay in
    the digest count but never re-enter the wake set — the coverage filter
    applies on the legacy fallback too, so a failed ledger query can never
    resurrect receipts an ``unknown``/``accepted`` attempt already covered.
    Ledger unavailable → the legacy counting-window scan, unchanged.
    """

    covered: dict[str, str] = {}
    if ledger_ready and pa_agent_id:
        # Coverage is read before the query so the fallback branch below
        # keeps filtering even when the ledger query itself fails.
        covered = _ledger_wake_covered()
        rows = _ledger_undigested_receipts(pa_agent_id)
        if rows is not None:
            inbox_by_id: dict[str, dict[str, Any]] = {}
            try:
                for row in _read_pa_pending_messages(pa_agent_id):
                    key = _text(row, "messageId") or _text(row, "eventId")
                    if key and key not in inbox_by_id:
                        inbox_by_id[key] = row
            except Exception:  # noqa: BLE001 - prompt enrichment only
                inbox_by_id = {}
            merged: list[dict[str, Any]] = []
            for paired in rows:
                message_id = _text(paired, "messageId")
                base = inbox_by_id.get(message_id)
                if isinstance(base, dict):
                    enriched = dict(base)
                    enriched.setdefault("messageId", message_id)
                else:
                    # Out-of-window or unreadable body: the ledger row is
                    # the pairing authority, the prompt degrades to summary.
                    enriched = dict(paired)
                    enriched.setdefault("content", "")
                merged.append(enriched)
            eligible = [
                row for row in merged if _text(row, "messageId") not in covered
            ]
            return merged, eligible
    rows = find_undigested_receipts(pa_agent_id, dispatch_message_ids)
    if covered:
        return rows, [row for row in rows if _text(row, "messageId") not in covered]
    return rows, list(rows)


def _merged_wake_message(
    carrier: dict[str, Any],
    receipts: list[dict[str, Any]],
    pa_agent_id: str,
) -> dict[str, Any]:
    """One turn digests every wake-eligible receipt, not one per turn.

    The carrier (newest receipt) keeps its identity — ``wake_agent_for_inbox_message``
    consumes exactly it — while every other receipt is appended to the prompt
    content so the single PA turn sees the whole batch.
    """

    message = dict(carrier)
    message.setdefault("targetAgentId", pa_agent_id)
    message.setdefault("targetSessionId", "")
    others = [
        row
        for row in receipts
        if _text(row, "messageId") != _text(carrier, "messageId")
    ]
    if not others:
        return message
    lines = [
        f"[合并消化] 本轮唤醒一并处理 {len(receipts)} 条未消化回执（全部随本轮标记为已消化）：",
    ]
    for index, row in enumerate([carrier, *others], start=1):
        source = _text(row, "sourceAgentName") or _text(row, "sourceAgentId") or "外部来源"
        summary = _clip(_text(row, "summary"), limit=_SUMMARY_LIMIT) or "（无摘要）"
        lines.append(
            f"{index}. {_text(row, 'messageId')}（{source}，{_text(row, 'createdAt')}）：{summary}"
        )
    lines.append("请逐条核对以上回执并纳入处理；这些回执已随本轮一并消化，无需再等下一次提醒。")
    content = _text(message, "content") or _text(message, "summary")
    message["content"] = "\n".join([content, *lines]) if content else "\n".join(lines)
    message["summary"] = _clip(
        f"合并 {len(receipts)} 条回执：{_text(message, 'summary')}", limit=_SUMMARY_LIMIT
    )
    return message


def _attempt_merged_wake(
    state: _PatrolState,
    wake_eligible: list[dict[str, Any]],
    pa_agent_id: str,
    *,
    ledger_ready: bool,
    now: float,
) -> dict[str, Any]:
    """Reserve → submit → settle one merged wake, per the B-chain state machine.

    ``reserved`` is committed before any submission; ``accepted`` (turn
    started — the whole batch is digest-marked in one transaction and the
    non-carrier receipts are consumed) and ``unknown`` (outcome unprovable —
    never retried) consume quota; ``cancelled_pre_admission`` (skipped —
    provably no turn) is retryable and consumes nothing. Without a
    reservation (ledger off or reserve failed) the legacy single-receipt
    wake runs unchanged.
    """

    carrier = max(
        wake_eligible,
        key=lambda row: _parse_iso_timestamp(_text(row, "createdAt")) or 0.0,
    )
    carrier_id = _text(carrier, "messageId")
    receipt_ids = [_text(row, "messageId") for row in wake_eligible if _text(row, "messageId")]
    attempt_id = _ledger_reserve_wake(receipt_ids, now=now) if ledger_ready else None
    if attempt_id:
        wake_message = _merged_wake_message(carrier, wake_eligible, pa_agent_id)
    else:
        if ledger_ready:
            logger.warning(
                "PA patrol wake reservation unavailable; falling back to the legacy wake."
            )
        wake_message = dict(carrier)
        wake_message.setdefault("targetAgentId", pa_agent_id)
        wake_message.setdefault("targetSessionId", "")

    delivery: dict[str, Any]
    digested_ids: list[str] = []
    consumed_ids: list[str] = []
    try:
        delivery = _wake_pa(wake_message)
    except Exception as exc:  # noqa: BLE001 - wake failure must not kill the pass
        logger.warning("PA patrol wake failed (%s).", type(exc).__name__)
        delivery = {"wakeStatus": "error", "reason": type(exc).__name__}
        # Unprovable outcome: quota consumed, receipts never re-woken.
        recorded = False
        if attempt_id:
            recorded = _ledger_complete_wake(
                attempt_id,
                state="unknown",
                reason=str(delivery["reason"]),
                submitted_at_ms=now,
            )
        _record_wake_submission(state, now=now, ledger_recorded=recorded)
    else:
        wake_status = _text(delivery, "wakeStatus")
        if wake_status.startswith("started"):
            recorded = False
            if attempt_id:
                recorded = _ledger_complete_wake(
                    attempt_id, state="accepted", submitted_at_ms=now
                )
            _record_wake_submission(state, now=now, ledger_recorded=recorded)
            if attempt_id:
                # One turn saw the whole batch → one transaction lands all
                # N digested_at stamps (all or nothing, no half-digested).
                digested_ids = _ledger_mark_digested(
                    receipt_ids, digested_at=_utc_now_iso()
                )
                consumed_ids = _consume_pa_inbox_messages(
                    pa_agent_id,
                    [mid for mid in receipt_ids if mid != carrier_id],
                    session_id=_text(delivery, "targetSessionId"),
                    turn_id=_text(delivery, "turnId"),
                )
        elif wake_status.startswith("skipped"):
            # Provably not submitted: retryable, and it must not eat quota.
            if attempt_id:
                _ledger_complete_wake(
                    attempt_id, state="cancelled_pre_admission", reason=wake_status
                )
        else:
            # Unrecognized outcome — treat as unprovable (conservative).
            recorded = False
            if attempt_id:
                recorded = _ledger_complete_wake(
                    attempt_id,
                    state="unknown",
                    reason=wake_status or "unrecognized",
                    submitted_at_ms=now,
                )
            _record_wake_submission(state, now=now, ledger_recorded=recorded)
    return {
        "attempted": True,
        "receiptCount": len(wake_eligible),
        "mergedReceiptIds": receipt_ids if attempt_id else [mid for mid in [carrier_id] if mid],
        "digestedReceiptIds": digested_ids,
        "consumedReceiptIds": consumed_ids,
        "delivery": delivery,
    }


def _dispatch_age_seconds(dispatch: dict[str, Any], *, now: float) -> float | None:
    stamp = _parse_iso_timestamp(_text(dispatch, "sentAt"))
    if stamp is None:
        return None
    return now - stamp


def _is_aged_dispatch(dispatch: dict[str, Any], *, now: float) -> bool:
    """Chase actionable tasks after quiet time, inside the original send window."""

    if _text(dispatch, "deliveryStatus").lower() == "revoked" or _text(dispatch, "taskStatus") in {
        "completed", "failed", "cancelled", "blocked",
    }:
        return False
    message_id = _text(dispatch, "messageId")
    if not message_id:
        return False
    age = _dispatch_age_seconds(dispatch, now=now)
    if age is None:
        return False
    last_activity = now - age
    for receipt in dispatch.get("receipts") or []:
        if isinstance(receipt, dict):
            received = _parse_iso_timestamp(_text(receipt, "receivedAt"))
            if received is not None:
                last_activity = max(last_activity, received)
    return (
        0 <= age <= FOLLOWUP_MAX_AGE_SECONDS
        and now - last_activity >= FOLLOWUP_INITIAL_AGE_SECONDS
    )


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
            "需要同步任务进展或完成证据。"
        ),
    ]
    if summary:
        lines.append(f"原任务摘要: {summary}")
    lines.append(f"派遣消息ID: {_text(dispatch, 'messageId')}")
    lines.extend([
        "请使用现有 agent_message_tool 回复个人助理，并用 metadata_json 关联原派遣：",
        f"回复地址 target_session={_text(dispatch, 'sourceSessionId')}；这是原派遣发起会话，请勿猜测其他会话。",
        json.dumps({
            "replyToMessageId": _text(dispatch, "messageId"),
            "personalAssistantTask": {
                "schemaVersion": 1,
                "dispatchMessageId": _text(dispatch, "messageId"),
                "status": "running/blocked/completed/failed",
                "evidenceRefs": ["可核验的产出或验证记录引用"],
            },
        }, ensure_ascii=False),
        "status 请选择当前真实状态；completed 必须提供 evidenceRefs。普通回执不会关闭任务。",
    ])
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


def _followup_target_is_current(
    dispatch: dict[str, Any],
    pa_agent_id: str,
    *,
    ledger_ready: bool = False,
) -> bool:
    """Read native authority only; never recover/create a missing target session."""
    from . import personal_assistant_dispatches_service as dispatches
    from . import session_service
    from .session_archive_service import conversation_is_archived

    target_id = _text(dispatch, "targetAgentId")
    session_id = _text(dispatch, "targetSessionId")
    message_id = _text(dispatch, "messageId")
    if not target_id or not session_id or not message_id or not pa_agent_id:
        return False
    targets = [row for row in dispatches._agent_rows() if _text(row, "agentId") == target_id]
    if len(targets) != 1 or _text(targets[0], "status") != "active":
        return False
    target = targets[0]
    # Native wake redirects a replaced direct session even if it still exists.
    # Reject that seam here instead of waking a different session.
    metadata = target.get("metadata") if isinstance(target.get("metadata"), dict) else {}
    if (
        _text(metadata, "previousDirectSessionId") == session_id
        and _text(target, "directSessionId")
        and _text(target, "directSessionId") != session_id
    ):
        return False
    session = session_service.load_session_chat_state(session_service.PROJECT_ROOT, session_id)
    if (
        not isinstance(session, dict)
        or _text(session, "id") != session_id
        or _text(session, "agentId") != target_id
        or conversation_is_archived(session)
    ):
        return False
    # Last read before submit: revocation/source/landing checks use the original
    # inbox row, never the earlier aggregate or user-supplied custom metadata.
    # 批三：优先读台账信封列（含 instance 唯一性与收割完整性闸门），台账
    # 答不了（None）才回退 JSONL strict 正读——不再每轮全文件扫描。
    if ledger_ready:
        ledger_verdict = _ledger_dispatch_current(
            message_id,
            source_agent_id=pa_agent_id,
            target_agent_id=target_id,
            target_session_id=session_id,
            source_session_id=_text(dispatch, "sourceSessionId"),
            thread_id=_text(dispatch, "threadId"),
        )
        if ledger_verdict is not None:
            return ledger_verdict
    originals = dispatches._scan_inbox_reverse(
        dispatches._inbox_path(target),
        predicate=lambda row: (_text(row, "messageId") or _text(row, "eventId")) == message_id,
        cap=2,
        strict=True,
    )
    return bool(
        len(originals) == 1
        and _text(originals[0], "sourceAgentId") == pa_agent_id
        and _text(originals[0], "targetAgentId") == target_id
        and _text(originals[0], "targetSessionId") == session_id
        and _text(dispatch, "sourceSessionId")
        and _text(dispatches._metadata(originals[0]), "sourceSessionId") == _text(dispatch, "sourceSessionId")
        and _text(originals[0], "threadId") == _text(dispatch, "threadId")
        and _text(originals[0], "status").lower() != "revoked"
        and not dispatches._is_followup(originals[0])
    )


def send_followup_for_dispatch(
    dispatch: dict[str, Any],
    *,
    round_index: int,
    age_seconds: float,
    pa_sender: dict[str, Any],
    ledger_ready: bool = False,
) -> dict[str, Any]:
    """Submit one follow-up message to the dispatch target via the kernel."""

    message_id = _text(dispatch, "messageId")
    target_agent_id = _text(dispatch, "targetAgentId")
    summary = _clip(_text(dispatch, "summary"), limit=_SUMMARY_LIMIT)
    content = _followup_content(dispatch, round_index=round_index, age_seconds=age_seconds)
    if (
        _text(dispatch, "deliveryStatus").lower() == "revoked"
        or not _followup_target_is_current(
            dispatch, _text(pa_sender, "agentId"), ledger_ready=ledger_ready
        )
    ):
        return {"accepted": False, "reason": "dispatch_target_unavailable"}
    return _submit_followup_event(
        source=PATROL_SOURCE,
        sender={**pa_sender, "sessionId": _text(dispatch, "sourceSessionId")},
        recipient_agent_ids=[target_agent_id],
        content=content,
        correlation_id=_text(dispatch, "threadId") or message_id,
        wake_target=True,
        metadata={
            "sourceSurface": PATROL_SOURCE,
            "sourceSessionId": _text(dispatch, "sourceSessionId"),
            "inboxKind": PATROL_SOURCE,
            "messageSummary": _clip(f"催办（第 {round_index} 次）：{summary or '派遣待更新'}", limit=_SUMMARY_LIMIT),
            "inboxCreatedBy": "pa_patrol",
            "targetSessionId": _text(dispatch, "targetSessionId"),
            "agentToolMetadataJson": json.dumps({
                "paFollowupOfMessageId": message_id,
                "paFollowupRound": int(round_index),
            }),
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
    blocked: int = 0,
    failed: int = 0,
) -> dict[str, int]:
    return {
        "inFlightDispatches": max(0, int(in_flight)),
        "agedDueChases": max(0, int(aged_due)),
        "undigestedReceipts": max(0, int(undigested_receipts)),
        "blockedDispatches": max(0, int(blocked)),
        "failedDispatches": max(0, int(failed)),
    }


def _digest_fingerprint(aggregate: dict[str, int]) -> str:
    payload = json.dumps(aggregate, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _stalled_duration_label(seconds: float) -> str:
    """``"31 分钟"`` / ``"2 小时"`` / ``"2 小时 5 分钟"``; empty under one minute."""

    minutes = int(max(0.0, float(seconds)) // 60)
    if minutes < 1:
        return ""
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return f"{hours} 小时 {minutes} 分钟"
    if hours:
        return f"{hours} 小时"
    return f"{minutes} 分钟"


def _digest_row(
    aggregate: dict[str, int],
    rotation: float,
    *,
    stalled_seconds: float = 0.0,
) -> dict[str, str]:
    """Digest row; ``stalled_seconds`` is how long the signal has persisted.

    行形状（id/kind/severity/title/targetUrl/body）不变。只有信号已持续
    超过 ``DIGEST_FRESHNESS_SECONDS``（即这张卡是停摆升级重现的）时，正文
    才追加「已持续 N 分钟待处理」——首张卡与正常路径的正文逐字保持原样，
    用户在 toast 里就能分辨「首次提醒」和「还没人处理的升级提醒」，不需要
    前端新字段。
    """

    title = _clip(
        "助理派遣摘要：进行中 {inFlightDispatches} · 逾期待催办 {agedDueChases}"
        " · 阻塞 {blockedDispatches} · 失败 {failedDispatches}"
        " · 未消化回执 {undigestedReceipts}".format(**aggregate)
    )
    stalled = (
        _stalled_duration_label(stalled_seconds)
        if stalled_seconds >= DIGEST_FRESHNESS_SECONDS
        else ""
    )
    body = _clip(
        "个人助理有派遣仍在进行或回执未消化"
        + (f"，已持续 {stalled}待处理" if stalled else "")
        + "；点击查看派遣面板详情。",
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
    """Rotate the digest id at most once per interval; re-surface stalls.

    Returns ``(rotated, row)``; ``row`` is None when there is no signal at
    all (everything settled → the lane goes quiet instead of showing 0s).

    轮转触发条件（二者任一，且都受 ``DIGEST_MIN_INTERVAL_SECONDS`` 节流）：

    1. 内容指纹变化（原有语义）。
    2. 停摆升级：指纹没变但当前卡已过 ``DIGEST_FRESHNESS_SECONDS`` 而信号
       仍在——派遣一直 awaiting_confirmation、回执一直没人消化。此前这种
       情形永不轮转，卡过新鲜度窗口后从 humanAttention 静默消失、再无提醒。
       现在它按同一节流重新轮转一个新 id：humanAttention 的唯一前端消费方
       （``HumanAttentionNotifier`` → 按 id 日级去重的 toast）只对新 id 再
       提醒一次，所以「重新出现」必须换 id 才对用户可见；节流仍跟随巡逻
       节奏，最多每 ``DIGEST_MIN_INTERVAL_SECONDS`` 一次，不会每巡逻都推。
       信号归零照旧清行（已处理的事项不会被这条路径复活）。
    """

    fingerprint = _digest_fingerprint(aggregate)
    has_signal = any(value > 0 for value in aggregate.values())
    with state.lock:
        if not has_signal:
            state.digest_fingerprint = fingerprint
            state.digest_last_rotation = float(now)
            state.digest_row = None
            state.digest_signal_since = 0.0
            return False, None
        if state.digest_signal_since <= 0.0:
            state.digest_signal_since = float(now)
        since_rotation = now - state.digest_last_rotation
        card_stale = since_rotation >= DIGEST_FRESHNESS_SECONDS
        rotated = False
        if (
            (fingerprint != state.digest_fingerprint or card_stale)
            and since_rotation >= DIGEST_MIN_INTERVAL_SECONDS
        ):
            state.digest_fingerprint = fingerprint
            state.digest_last_rotation = float(now)
            rotated = True
        row = _digest_row(
            aggregate,
            state.digest_last_rotation,
            stalled_seconds=now - state.digest_signal_since,
        )
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

    # ---- stage 0: undigested receipts (ledger-driven, 批三核心) ----
    ledger_ready = _ledger_ready(pa_agent_id)
    try:
        undigested, wake_eligible = _collect_undigested_receipts(
            pa_agent_id, dispatch_message_ids, ledger_ready=ledger_ready
        )
    except Exception as exc:  # noqa: BLE001 - inbox read failure must not kill the pass
        logger.warning("PA patrol inbox read failed (%s).", type(exc).__name__)
        undigested, wake_eligible = [], []

    # ---- stage 1: follow-ups ----
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
                    delivery = send_followup_for_dispatch(
                        dispatch,
                        round_index=next_round,
                        age_seconds=age,
                        pa_sender=pa_sender,
                        ledger_ready=ledger_ready,
                    )
                    if delivery.get("accepted") is False:
                        continue
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

    # ---- stage 2: receipt digestion wake (merged, reserved-then-submitted) ----
    try:
        if result["wakeEnabled"] and wake_eligible:
            stamps = _wake_throttle_stamps(
                _patrol_state, ledger_ready=ledger_ready, now=observed
            )
            if _wake_gate(stamps=stamps, now=observed):
                result["wake"] = _attempt_merged_wake(
                    _patrol_state,
                    wake_eligible,
                    pa_agent_id,
                    ledger_ready=ledger_ready,
                    now=observed,
                )
            else:
                result["wake"] = {"attempted": False, "reason": "throttled", "receiptCount": len(wake_eligible)}
        elif wake_eligible:
            result["wake"] = {"attempted": False, "reason": "wake_disabled", "receiptCount": len(wake_eligible)}
    except Exception as exc:  # noqa: BLE001
        logger.warning("PA patrol wake stage failed (%s).", type(exc).__name__)

    # ---- stage 3: digest card ----
    try:
        aged_with_budget = 0
        for message_id in result["agedMessageIds"]:
            allowed, _round = _followup_gate(_patrol_state, message_id, now=observed)
            if allowed:
                aged_with_budget += 1
        current = [row for row in dispatches if _text(row, "deliveryStatus").lower() != "revoked"]
        in_flight = sum(
            1 for row in current if _text(row, "taskStatus") not in {"completed", "failed", "cancelled"}
        )
        aggregate = _digest_aggregate(
            in_flight=in_flight,
            aged_due=aged_with_budget,
            undigested_receipts=len(undigested),
            blocked=sum(1 for row in current if _text(row, "taskStatus") == "blocked"),
            failed=sum(1 for row in current if _text(row, "taskStatus") == "failed"),
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
