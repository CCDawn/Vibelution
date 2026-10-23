"""完成类事件的人工关注行（「好消息也推送」第 1 档）。

把三类完成事件投影进 overview ``humanAttention`` 通道，复用现有人工关注
双通道（助理窗通知卡 / 系统 toast）。三个来源全部只读，任何失败降级为
空列表，绝不阻塞 overview 轮询：

- ``dispatch_receipt`` —— 个人助理派遣收到配对回执。复用
  ``personal_assistant_dispatches_service.list_personal_assistant_dispatches``
  的现有回执配对（replyToMessageId/threadId 双键），本模块不做第二套配对。
- ``run_completed`` —— 科研工作流 run 到达终态 ``succeeded``。失败 run 已
  由 anomaly 通道覆盖，这里只报成功，不重复占用异常语义。
- ``session_completed`` —— 会话一轮回答完成。复用桌面宠物 activity 的
  ``completed`` 语气（本身就是 15s 脉冲）。

防刷屏策略（硬要求，三层）：

1. 新鲜度窗口：派遣回执 / run 完成只报 ``COMPLETION_RECENCY_WINDOW_SECONDS``
   内到达的事件——重启应用、跨天账本重置都不会重放旧完成；会话完成沿用
   pet activity 自带的 15s 完成脉冲，天然只在完成瞬间可见。
2. 聚合 + 稳定 id：同一派遣多条回执只报一行（id 按派遣 messageId 聚合）、
   同一 run 一行；id 跨轮询稳定，web 层按天账本与壳层 60s 去重窗口都能
   压住 5s 一次的轮询重发。会话 id 携带完成时间戳：同一会话下一轮完成是
   新事件（应再提醒），同一轮的重复轮询是同一 id（不再提醒）。
3. 每次采集条数上限：三个来源各自设上限，聚合层再设全局上限，单次轮询
   最多涌入 ``MAX_COMPLETION_ITEMS`` 条，堆叠卡片（上限 3）不会被淹没。
   科研/自动会话的每轮“完成”由 run 级通道聚合承载，会话级通道排除
   child/有父会话的研究扇出 worker，以及自主行动 Agent 的后台会话，不逐轮刷屏。

通知语气统一 ``info``（不占用停靠/异常的 critical/high）。行结构沿用
humanAttention 契约：``id``/``kind``/``severity``/``title``/``targetUrl``/
可选 ``body``；无 ``actions``（完成类是纯信息卡，卡片整体点击即“查看
结果”跳转，没有决策按钮）。
"""

from __future__ import annotations

import time
from typing import Any

ATTENTION_KIND_DISPATCH_RECEIPT = "dispatch_receipt"
ATTENTION_KIND_RUN_COMPLETED = "run_completed"
ATTENTION_KIND_SESSION_COMPLETED = "session_completed"

# 完成类是好消息，统一低平语气；critical/high 保留给停靠与异常。
ATTENTION_SEVERITY_INFO = "info"

# 回执 / run 完成的新鲜度窗口：窗口外的完成不再进入 lane，因此应用重启或
# web 层按天账本重置都不会把旧完成重新弹给用户。
COMPLETION_RECENCY_WINDOW_SECONDS = 30 * 60.0

MAX_DISPATCH_RECEIPT_ITEMS = 3
MAX_RUN_COMPLETED_ITEMS = 4
MAX_SESSION_COMPLETED_ITEMS = 3
# 聚合层全局上限：单次轮询新增的完成类行总量的硬顶。
MAX_COMPLETION_ITEMS = 8

DISPATCH_RECEIPT_TARGET_URL = "/personal-assistant?panel=dispatches"

_TITLE_LIMIT = 80
_ID_SEGMENT_LIMIT = 64


def _clip(value: Any, *, limit: int = _TITLE_LIMIT) -> str:
    from .personal_attention_service import _clip as _attention_clip

    return _attention_clip(value, limit=limit)


def _active_teams() -> list[dict[str, str]]:
    from .personal_attention_service import _active_teams as _teams

    return _teams()


def _research_workspace_url(team_id: str, extra: dict[str, str] | None = None) -> str:
    from .personal_attention_service import _research_workspace_url as _url

    return _url(team_id, extra)


def _parse_iso_timestamp(value: Any) -> float | None:
    """Epoch seconds for an ISO timestamp; None when absent/unparsable."""

    from .session.timebase import parse_timestamp_utc

    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = parse_timestamp_utc(text)
    except Exception:  # noqa: BLE001 - an unparsable stamp is not an attention error
        return None
    if parsed is None:
        return None
    return parsed.timestamp()


def _within_window(stamp_seconds: float | None, *, now: float) -> bool:
    if stamp_seconds is None:
        return False
    age = now - stamp_seconds
    return 0 <= age <= COMPLETION_RECENCY_WINDOW_SECONDS


def _id_segment(value: Any) -> str:
    return _clip(str(value or "").strip() or "unknown", limit=_ID_SEGMENT_LIMIT).replace(" ", "-")


# ---------------------------------------------------------------------------
# 派遣回执到达
# ---------------------------------------------------------------------------


def collect_dispatch_receipt_attention(
    *, limit: int = MAX_DISPATCH_RECEIPT_ITEMS, now: float | None = None
) -> list[dict[str, str]]:
    """PA dispatches with a freshly paired receipt, one row per dispatch."""

    from .personal_assistant_dispatches_service import (
        PersonalAssistantDispatchesError,
        list_personal_assistant_dispatches,
    )

    observed = time.time() if now is None else now
    try:
        listing = list_personal_assistant_dispatches()
    except PersonalAssistantDispatchesError:
        # No assistant identity → no dispatches can exist; stay silent.
        return []
    except Exception:  # noqa: BLE001 - dispatch read failure is not an attention error
        return []

    rows: list[tuple[float, dict[str, str]]] = []
    for dispatch in listing.get("dispatches") or []:
        if not isinstance(dispatch, dict):
            continue
        receipts = [row for row in dispatch.get("receipts") or [] if isinstance(row, dict)]
        if not receipts:
            continue
        newest_stamp = max(
            (
                stamp
                for stamp in (
                    _parse_iso_timestamp(receipt.get("receivedAt")) for receipt in receipts
                )
                if stamp is not None
            ),
            default=None,
        )
        if not _within_window(newest_stamp, now=observed):
            continue
        message_id = str(dispatch.get("messageId") or "").strip()
        if not message_id:
            continue
        target_name = str(dispatch.get("targetAgentName") or "").strip() or "目标 agent"
        newest_receipt = max(
            receipts,
            key=lambda receipt: _parse_iso_timestamp(receipt.get("receivedAt")) or 0.0,
        )
        receipt_summary = str(newest_receipt.get("summary") or "").strip()
        body = str(dispatch.get("summary") or "").strip() or receipt_summary
        rows.append(
            (
                newest_stamp or observed,
                {
                    "id": f"dispatch-receipt:{_id_segment(message_id)}",
                    "kind": ATTENTION_KIND_DISPATCH_RECEIPT,
                    "severity": ATTENTION_SEVERITY_INFO,
                    "title": _clip(f"派遣回执：{target_name}"),
                    "targetUrl": DISPATCH_RECEIPT_TARGET_URL,
                    "body": _clip(body or "派遣已收到回执"),
                },
            )
        )
    rows.sort(key=lambda row: row[0], reverse=True)
    return [row for _, row in rows[: max(0, int(limit))]]


# ---------------------------------------------------------------------------
# 科研 run 终态完成
# ---------------------------------------------------------------------------

_RUN_SUCCEEDED_STATUS = "succeeded"


def collect_run_completed_attention(
    *, limit: int = MAX_RUN_COMPLETED_ITEMS, now: float | None = None
) -> list[dict[str, str]]:
    """Research runs that reached the ``succeeded`` terminal state recently."""

    from .team_workflow.research_runtime import formal_read_runtime
    from .team_workflow.research_runtime.service import CHALLENGE_CUP_WORKFLOW_ID

    observed = time.time() if now is None else now
    try:
        query = formal_read_runtime.get_query_service()
    except Exception:  # noqa: BLE001 - unconfigured runtime / migration barrier stays silent
        return []

    rows: list[tuple[float, dict[str, str]]] = []
    for team in _active_teams():
        try:
            runs = (
                query.list_runs(
                    team_id=team["teamId"],
                    workflow_id=CHALLENGE_CUP_WORKFLOW_ID,
                )
                or {}
            ).get("runs") or []
        except Exception:  # noqa: BLE001 - one unreadable team degrades to no signal
            continue
        for run in runs:
            if not isinstance(run, dict):
                continue
            if str(run.get("status") or "").strip() != _RUN_SUCCEEDED_STATUS:
                continue
            stamp_ms = run.get("completedAtMs") or run.get("updatedAtMs")
            try:
                stamp = float(stamp_ms) / 1000.0 if stamp_ms is not None else None
            except (TypeError, ValueError):
                stamp = None
            if not _within_window(stamp, now=observed):
                continue
            run_id = str(run.get("runId") or "").strip()
            team_id = str(run.get("teamId") or team["teamId"]).strip()
            if not run_id or not team_id:
                continue
            question_id = str(run.get("questionId") or "").strip()
            label = question_id or run_id
            rows.append(
                (
                    stamp or 0.0,
                    {
                        "id": f"run-completed:{_id_segment(team_id)}:{_id_segment(run_id)}",
                        "kind": ATTENTION_KIND_RUN_COMPLETED,
                        "severity": ATTENTION_SEVERITY_INFO,
                        "title": _clip(f"研究运行完成：{label}"),
                        "targetUrl": _research_workspace_url(
                            team_id,
                            {"runId": run_id, "panel": "progress"},
                        ),
                        "body": _clip(f"{team['teamName']} · {question_id}".strip(" ·") or "运行已完成"),
                    },
                )
            )
    rows.sort(key=lambda row: row[0], reverse=True)
    return [row for _, row in rows[: max(0, int(limit))]]


# ---------------------------------------------------------------------------
# 会话完成
# ---------------------------------------------------------------------------


def collect_session_completed_attention(
    *, limit: int = MAX_SESSION_COMPLETED_ITEMS, now: float | None = None
) -> list[dict[str, str]]:
    """Sessions whose completing turn just settled, user-facing sessions only.

    防刷屏：只有 pet activity 判定为 ``completed`` 语气（15s 完成脉冲）的
    会话进入候选；child / 有父会话的研究扇出 worker 被排除——它们的每轮
    “完成”由 ``run_completed`` 在 run 级聚合承载，不逐轮刷屏。id 携带完成
    时间戳：同一轮重复轮询是同一 id（账本压住），下一轮完成是新的 id（应
    再次提醒）。自主行动 worker 按 Agent 身份排除，包括额外创建的可见会话；
    虚拟人本人的正常聊天仍保留完成提醒。
    """

    from . import agent_directory_service, pet_activity_service
    from .session_service import list_sessions

    observed = time.time() if now is None else now
    try:
        activity = pet_activity_service.get_pet_activity()
    except Exception:  # noqa: BLE001 - activity projection failure is not an attention error
        return []
    completed_rows = [
        row
        for row in activity.get("sessions") or []
        if isinstance(row, dict) and row.get("tone") == "completed"
    ]
    if not completed_rows:
        return []

    # Auxiliary user_chat sessions can reference a hidden self-wake Agent.
    # Use persisted identity, not session visibility or an editable display name.
    try:
        self_wake_agent_ids = {
            agent_id
            for status in ("active", "archived")
            for agent_id in agent_directory_service.find_agent_ids_by_metadata(
                "virtualHumanSelfWake", True, status=status
            )
        }
    except Exception:  # noqa: BLE001 - unverified completion identities stay silent
        return []

    # 完成候选存在时才做一次会话清单对照（list_sessions 有自己的缓存），
    # 用来排除研究扇出的 child / 有父会话 worker。
    automated_session_ids: set[str] = set()
    try:
        for session in list_sessions():
            if not isinstance(session, dict):
                continue
            session_id = str(session.get("id") or "").strip()
            if not session_id:
                continue
            if (
                str(session.get("sessionKind") or "").strip() == "child"
                or str(session.get("parentSessionId") or "").strip()
            ):
                automated_session_ids.add(session_id)
    except Exception:  # noqa: BLE001 - index failure degrades to unfiltered candidates
        automated_session_ids = set()

    rows: list[tuple[float, dict[str, str]]] = []
    for row in completed_rows:
        session_id = str(row.get("sessionId") or "").strip()
        if not session_id or session_id in automated_session_ids:
            continue
        if str(row.get("agentId") or "").strip() in self_wake_agent_ids:
            continue
        # id 的时间戳段必须来自行内稳定字段：缺 updatedAt 的行拿不到稳定
        # 完成时刻（退到 observed 会让 15s 脉冲内每次轮询都生成新 id，账本
        # 压不住，同一完成弹多次），直接跳过。
        stamp = _parse_iso_timestamp(row.get("updatedAt"))
        if stamp is None:
            continue
        agent_name = str(row.get("agentDisplayName") or "").strip()
        title = str(row.get("title") or "").strip() or "会话"
        rows.append(
            (
                stamp,
                {
                    "id": (
                        f"session-completed:{_id_segment(session_id)}:"
                        f"{int(round(stamp))}"
                    ),
                    "kind": ATTENTION_KIND_SESSION_COMPLETED,
                    "severity": ATTENTION_SEVERITY_INFO,
                    "title": _clip(f"会话已完成：{title}"),
                    "targetUrl": f"/chat?session={session_id}",
                    "body": _clip(agent_name or "本轮回答已完成"),
                },
            )
        )
    rows.sort(key=lambda row: row[0], reverse=True)
    return [row for _, row in rows[: max(0, int(limit))]]


def collect_completion_attention(*, limit: int = MAX_COMPLETION_ITEMS) -> list[dict[str, str]]:
    """Aggregate the three completion sources; failures degrade per source."""

    collected: list[dict[str, str]] = []
    for collector in (
        collect_dispatch_receipt_attention,
        collect_run_completed_attention,
        collect_session_completed_attention,
    ):
        try:
            collected.extend(collector())
        except Exception:  # noqa: BLE001 - one completion source must not hide the others
            continue
    # 新鲜度窗口之外理论上不会出现旧行，这里仍按出现顺序截断到全局上限。
    return collected[: max(0, int(limit))]


__all__ = [
    "ATTENTION_KIND_DISPATCH_RECEIPT",
    "ATTENTION_KIND_RUN_COMPLETED",
    "ATTENTION_KIND_SESSION_COMPLETED",
    "ATTENTION_SEVERITY_INFO",
    "COMPLETION_RECENCY_WINDOW_SECONDS",
    "MAX_COMPLETION_ITEMS",
    "DISPATCH_RECEIPT_TARGET_URL",
    "collect_completion_attention",
    "collect_dispatch_receipt_attention",
    "collect_run_completed_attention",
    "collect_session_completed_attention",
]
