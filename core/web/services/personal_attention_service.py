"""Human-attention sources aggregated into the assistant overview feed.


双通道人工注意通知的后端聚合层：把「需要人工注意」的停靠项投影成

overview ``attention`` 条目。只做轮询聚合（overview GET 已有轮询），不加

推送通道。两类来源都以阶段任务存储为权威（纯文件只读，任何进程可读）：


- ``knowledge_review`` —— 知识入库复核停靠（阶段任务 ``stageId ==

  ingestion`` 且 ``status == needs_review``，即入库提案已完成、停在治理

  复核门）。真实停靠形态是阶段任务记录（writeback closureSummary 的

  ``knowledge_review_pending``），不是候选存储状态——候选店里的

  ``steward_pending_*`` 状态属于另一条源审查链，不在此重复投影。

- ``anomaly`` —— 人工升级项（阶段任务带非空 ``anomalyEscalation``，如

  失败规划师的 escalate_human 裁决），加上 state-v2 异常收件箱投影的

  critical/high 条目（``anomaly_inbox_service.build_anomaly_inbox`` 合同

  投影；需要进程内 formal read runtime，未配置时整源静默跳过，不阻塞）。


同一条任务既停靠复核又带升级时只按 ``anomaly`` 报一次，避免一条停靠弹

两个通知。


severity 只使用异常收件合同冻结的 ``ANOMALY_SEVERITY_*`` 值；

``knowledge_review`` 固定映射为 ``high``（流程停在人工复核门，等待人决

定）。防爆炸：两类新源各自设上限并按 severity 降序；单团队/单文件/单题

目读取失败降级为跳过该范围，绝不阻塞 overview 主路径。条目字段对既有

approval/error 条目只增不改：``id``（任务 id / anomaly 键，跨轮询稳

定）、``kind``、``severity``、``title``、``targetUrl``（前端路由路

径）、可选 ``body``。

"""


from __future__ import annotations


import json

import threading

import time

from pathlib import Path

from typing import Any, Iterator

from urllib.parse import urlencode


from core.research.workflow.contracts.anomaly_inbox import (

    ANOMALY_SEVERITY_CRITICAL,

    ANOMALY_SEVERITY_HIGH,

    ANOMALY_SEVERITY_RANK,

)


ATTENTION_KIND_KNOWLEDGE_REVIEW = "knowledge_review"

ATTENTION_KIND_ANOMALY = "anomaly"

ATTENTION_KIND_AFFAIR_REMINDER = "affair_reminder"


MAX_KNOWLEDGE_REVIEW_ITEMS = 20

MAX_ANOMALY_ITEMS = 20


_STAGE_ID_INGESTION = "ingestion"

_STAGE_STATUS_NEEDS_REVIEW = "needs_review"

_MAX_TASK_STORES_PER_TEAM = 500

_NOTIFIED_SEVERITIES = frozenset({ANOMALY_SEVERITY_CRITICAL, ANOMALY_SEVERITY_HIGH})

_TITLE_LIMIT = 80

_TEAM_NAME_LIMIT = 48

_CHALLENGE_CUP_WORKFLOW_ID = "challenge-cup-research"



def _clip(value: Any, *, limit: int) -> str:

    text = " ".join(str(value or "").split())

    if len(text) > limit:

        return f"{text[: limit - 1]}…"

    return text



def _active_teams() -> list[dict[str, str]]:

    """Read-only team references (no canvas or chat-room hydration)."""


    from core.web.services import team_service


    try:

        listing = team_service.list_team_graph_references()

    except Exception:  # noqa: BLE001 - an unavailable team index is not an attention error

        return []

    teams: list[dict[str, str]] = []

    for row in listing.get("teams") or []:

        if not isinstance(row, dict):

            continue

        team_id = str(row.get("teamId") or "").strip()

        if not team_id:

            continue

        teams.append(

            {

                "teamId": team_id,

                "teamName": _clip(row.get("name") or team_id, limit=_TEAM_NAME_LIMIT),

            }

        )

    return teams



def _research_workspace_url(

    team_id: str, extra: dict[str, str] | None = None

) -> str:

    params = {

        "teamId": team_id,

        "researchView": "workflow",

        "workflowId": _CHALLENGE_CUP_WORKFLOW_ID,

        **(extra or {}),

    }

    return "/teams?" + urlencode(params)



def _task_summary_text(task: dict[str, Any]) -> str:

    summary = str(task.get("summary") or "").strip()

    if summary:

        return summary

    writeback = task.get("writeback") if isinstance(task.get("writeback"), dict) else {}

    closure = (

        writeback.get("closureSummary")

        if isinstance(writeback.get("closureSummary"), dict)

        else {}

    )

    return str(closure.get("message") or "").strip()



def _iter_stage_tasks(team_id: str) -> Iterator[tuple[str, dict[str, Any]]]:

    """Yield ``(research_project_id, task)`` from a team's stage task stores.


    Pure file reads over ``research_projects/*/workspace/

    source_collection_runs/*/stage_session_tasks.json``; one unreadable store

    is skipped, never raised. Bounded so a runaway directory cannot stall the

    overview poll.

    """


    from core.web.services.team_workflow.research_projects import (

        formal_team_workspace_root,

    )


    try:

        projects_root = formal_team_workspace_root(team_id) / "research_projects"

        if not projects_root.is_dir():

            return

        run_stores = sorted(

            projects_root.glob(

                "*/workspace/source_collection_runs/*/stage_session_tasks.json"

            )

        )

    except Exception:  # noqa: BLE001 - path resolution failure is not an attention error

        return

    for store_path in run_stores[:_MAX_TASK_STORES_PER_TEAM]:

        try:

            payload = json.loads(store_path.read_text(encoding="utf-8"))

        except (OSError, ValueError):

            continue

        tasks = payload.get("tasks") if isinstance(payload, dict) else None

        if not isinstance(tasks, list):

            continue

        try:

            relative = store_path.relative_to(projects_root)

            project_id = relative.parts[0]

        except ValueError:

            continue

        for task in tasks:

            if isinstance(task, dict):

                yield project_id, task



def _escalation_severity(task: dict[str, Any]) -> str:

    escalation = task.get("anomalyEscalation")

    if not isinstance(escalation, dict):

        return ANOMALY_SEVERITY_CRITICAL

    items = escalation.get("items")

    best = ""

    if isinstance(items, list):

        for item in items:

            if not isinstance(item, dict):

                continue

            severity = str(item.get("severity") or "").strip()

            if severity in ANOMALY_SEVERITY_RANK and (

                not best or ANOMALY_SEVERITY_RANK[severity] < ANOMALY_SEVERITY_RANK[best]

            ):

                best = severity

    return best or ANOMALY_SEVERITY_CRITICAL



def collect_stage_task_attention(

    *,

    knowledge_review_limit: int = MAX_KNOWLEDGE_REVIEW_ITEMS,

    anomaly_limit: int = MAX_ANOMALY_ITEMS,

) -> tuple[list[dict[str, str]], list[dict[str, str]]]:

    """Aggregate stage-task docks into (knowledge_review, anomaly) entries."""


    knowledge_review: list[dict[str, str]] = []

    anomaly: list[dict[str, str]] = []

    for team in _active_teams():

        for project_id, task in _iter_stage_tasks(team["teamId"]):

            task_id = str(task.get("taskId") or "").strip()

            if not task_id:

                continue

            target = _research_workspace_url(

                team["teamId"],

                {"researchProjectId": project_id, "panel": "progress"},

            )

            if isinstance(task.get("anomalyEscalation"), dict) and task["anomalyEscalation"]:

                # Escalated docks report once as anomaly, never duplicated as

                # knowledge_review even when they also sit at the review gate.

                anomaly.append(

                    {

                        "id": f"escalation:{task_id}",

                        "kind": ATTENTION_KIND_ANOMALY,

                        "severity": _escalation_severity(task),

                        "title": _clip(

                            task.get("title") or "阶段任务等待人工处理",

                            limit=_TITLE_LIMIT,

                        ),

                        "targetUrl": target,

                        "body": _clip(

                            f"{team['teamName']} · {project_id} · {_task_summary_text(task)}",

                            limit=_TITLE_LIMIT,

                        ),

                    }

                )

                continue

            if (

                str(task.get("stageId") or "") == _STAGE_ID_INGESTION

                and str(task.get("status") or "").strip().lower()

                == _STAGE_STATUS_NEEDS_REVIEW

            ):

                knowledge_review.append(

                    {

                        "id": f"review:{task_id}",

                        "kind": ATTENTION_KIND_KNOWLEDGE_REVIEW,

                        "severity": ANOMALY_SEVERITY_HIGH,

                        "title": _clip(

                            task.get("title") or "知识入库复核",

                            limit=_TITLE_LIMIT,

                        ),

                        "targetUrl": target,

                        "body": _clip(

                            f"{team['teamName']} · 入库提案已完成，等待治理复核。",

                            limit=_TITLE_LIMIT,

                        ),

                    }

                )

    knowledge_review.sort(key=lambda row: ANOMALY_SEVERITY_RANK.get(row["severity"], 99))

    anomaly.sort(key=lambda row: ANOMALY_SEVERITY_RANK.get(row["severity"], 99))

    return (

        knowledge_review[: max(0, knowledge_review_limit)],

        anomaly[: max(0, anomaly_limit)],

    )



def collect_knowledge_review_attention(

    *, limit: int = MAX_KNOWLEDGE_REVIEW_ITEMS

) -> list[dict[str, str]]:

    """Steward knowledge-review docks as attention entries."""


    return collect_stage_task_attention(knowledge_review_limit=limit, anomaly_limit=0)[0]



def _question_ids_with_state(team_id: str) -> list[str]:

    """Distinct question ids that own chain records for one team (read-only)."""


    from core.web.services.team_workflow.research_runtime import hypothesis_first_chain

    from core.web.services.team_workflow.storage_durability import read_jsonl_cached


    try:

        path = hypothesis_first_chain._storage_path(team_id)

        if not path.exists():

            return []

        records = read_jsonl_cached(path)

    except Exception:  # noqa: BLE001 - an unreadable chain ledger degrades to no signal

        return []

    seen: list[str] = []

    for record in records:

        if not isinstance(record, dict):

            continue

        question_id = str(record.get("questionId") or "").strip().upper()

        if question_id and question_id not in seen:

            seen.append(question_id)

    return sorted(seen)



def _team_question_inbox(team_id: str, question_id: str):

    """Contract inbox for one (team, question) scope; None on any read failure."""


    from core.web.services.team_workflow.research_runtime import (

        anomaly_inbox_service,

        hypothesis_first_state_v2,

    )


    try:

        snapshot = hypothesis_first_state_v2.project_hypothesis_first_state_v2(

            team_id, question_id

        )

        return anomaly_inbox_service.build_anomaly_inbox(

            snapshot,

            gate_waits=anomaly_inbox_service.derive_gate_waits(snapshot),

        )

    except Exception:  # noqa: BLE001 - one broken scope must not hide the other scopes

        return None



def _state_v2_anomaly_entries() -> list[dict[str, str]]:

    """Critical/high anomaly-inbox items projected from state-v2 snapshots."""


    entries: list[dict[str, str]] = []

    for team in _active_teams():

        for question_id in _question_ids_with_state(team["teamId"]):

            inbox = _team_question_inbox(team["teamId"], question_id)

            if inbox is None:

                continue

            for item in inbox.items:

                if item.severity not in _NOTIFIED_SEVERITIES:

                    continue

                scope = item.scope

                scoped_question = scope.questionId or question_id

                entries.append(

                    {

                        "id": "anomaly:"

                        + "|".join(

                            (

                                scope.teamId or team["teamId"],

                                scoped_question,

                                scope.runId,

                                scope.nodeId,

                                scope.meetingRoundId,

                                item.kind,

                            )

                        ),

                        "kind": ATTENTION_KIND_ANOMALY,

                        "severity": item.severity,

                        "title": _clip(item.summary, limit=_TITLE_LIMIT),

                        "targetUrl": _research_workspace_url(

                            team["teamId"],

                            {"questionId": scoped_question, "panel": "progress"},

                        ),

                        "body": _clip(

                            f"{team['teamName']} · {scoped_question}",

                            limit=_TITLE_LIMIT,

                        ),

                    }

                )

    entries.sort(key=lambda row: ANOMALY_SEVERITY_RANK.get(row["severity"], 99))

    return entries



def collect_anomaly_attention(

    *, limit: int = MAX_ANOMALY_ITEMS

) -> list[dict[str, str]]:

    """Escalated stage tasks plus critical/high state-v2 inbox items."""


    entries: list[dict[str, str]] = []

    seen_ids: set[str] = set()

    for source in (

        lambda: collect_stage_task_attention(knowledge_review_limit=0)[1],

        _state_v2_anomaly_entries,

    ):

        try:

            produced = source()

        except Exception:  # noqa: BLE001 - one anomaly source must not hide the other

            continue

        for entry in produced:

            if entry["id"] in seen_ids:

                continue

            seen_ids.add(entry["id"])

            entries.append(entry)

    entries.sort(key=lambda row: ANOMALY_SEVERITY_RANK.get(row["severity"], 99))

    return entries[: max(0, limit)]



def _collect_affair_reminder_attention() -> list[dict[str, str]]:
    """Due/overdue personal-affairs rows; lazy import keeps collector wiring optional."""
    from .personal_affairs_service import collect_affair_reminder_attention

    return collect_affair_reminder_attention()


def attach_attention_to_overview(payload: dict[str, Any]) -> dict[str, Any]:

    """Attach human-attention entries to every overview page.


    Composition point used by the overview route (keeps the collector wiring

    out of the assistant service itself). The collected entries land in a

    separate ``humanAttention`` lane carried on EVERY page: the workbench

    read model keeps only the last page's extra fields when it stitches

    paginated session rows together, so a first-page-only lane would be

    dropped whenever sessions span multiple pages. The list itself is page

    independent (same entries on each page); the session-derived

    ``attention`` list keeps its original pagination and counts invariant

    (attention rows === waiting + failed). Any collector failure is

    swallowed — the overview must never break because an attention source

    is unavailable.

    """


    if not isinstance(payload, dict):

        return payload

    if not isinstance(payload.get("attention"), list):

        return payload

    extension: list[dict[str, str]] = []

    for collector in (

        collect_knowledge_review_attention,

        collect_anomaly_attention,

        _collect_affair_reminder_attention,

    ):

        try:

            extension.extend(collector())

        except Exception:  # noqa: BLE001 - one attention source must not break the overview

            continue

    if extension:

        # 人类关注行走独立通道：会话派生 attention 与 counts 的旧不变量

        # （行数 === waiting + failed）原样保留，前端分页校验不受影响。

        payload["humanAttention"] = extension

    return payload


# ---------------------------------------------------------------------------
# 投递失败上报 → 个人助理 agent 收件箱
#
# 双通道通知的账本语义是 at-most-once：web 侧先记 ledger 再异步 notify，
# IPC 拒绝或壳侧 invalid_payload 时用户可能永远看不到这条关注事项。这里
# 提供统一入口，把失败写成个人助理收件箱里一条 ``delivery_failure`` 消息
# （prompt_eligible=True；个人助理 delegation_policy allowWakeMessages=False，
# 消息只留收件箱等下一轮——正是「汇报」语义，不唤醒）。防灌水：进程内
# 每 (kind, stage) 桶每小时上限 + 同 (id, kind, stage) 去重窗口。任何失败
# 吞掉，绝不影响调用方主路径（overview 轮询 / supervisor 事件记录）。
# ---------------------------------------------------------------------------


ATTENTION_DELIVERY_FAILURE_INBOX_KIND = "delivery_failure"

ATTENTION_DELIVERY_FAILURE_STAGE_RENDERER = "renderer"

ATTENTION_DELIVERY_FAILURE_STAGE_SHELL = "shell"

ATTENTION_DELIVERY_FAILURE_STAGES = frozenset(
    {ATTENTION_DELIVERY_FAILURE_STAGE_RENDERER, ATTENTION_DELIVERY_FAILURE_STAGE_SHELL}
)


MAX_DELIVERY_FAILURES_PER_BUCKET_PER_HOUR = 6

DELIVERY_FAILURE_DEDUP_WINDOW_SECONDS = 30 * 60

_DELIVERY_FAILURE_SEEN_MAX = 512

_DELIVERY_FAILURE_ID_LIMIT = 128

_DELIVERY_FAILURE_KIND_LIMIT = 40

_DELIVERY_FAILURE_SEVERITY_LIMIT = 16

_DELIVERY_FAILURE_REASON_LIMIT = 320

_DELIVERY_FAILURE_TITLE_LIMIT = 120

_DELIVERY_FAILURE_STAGE_LABELS = {
    ATTENTION_DELIVERY_FAILURE_STAGE_RENDERER: "前端渲染通道",
    ATTENTION_DELIVERY_FAILURE_STAGE_SHELL: "桌面壳通道",
}


class _DeliveryFailureState:
    """Process-wide rate limit + dedup state (module-level singleton)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.bucket_windows: dict[tuple[str, str], list[float]] = {}
        self.seen: dict[str, float] = {}

    def reset(self) -> None:
        with self.lock:
            self.bucket_windows.clear()
            self.seen.clear()


_delivery_failure_state = _DeliveryFailureState()


def reset_attention_delivery_failure_reporter_for_tests() -> None:
    """Reset the process-level rate limit/dedup state between tests."""

    _delivery_failure_state.reset()


def _claim_delivery_failure_slot(
    state: _DeliveryFailureState,
    *,
    attention_id: str,
    kind: str,
    stage: str,
    now: float,
) -> str:
    """Reserve one report slot; returns "" on success or a rejection reason."""

    seen_key = f"{attention_id}|{kind}|{stage}"

    bucket_key = (kind, stage)

    hour_ago = now - 3600.0

    with state.lock:

        # 同 (id, kind, stage) 去重窗口：窗口内重复失败只报一次。

        last_seen = state.seen.get(seen_key)

        if last_seen is not None and now - last_seen < DELIVERY_FAILURE_DEDUP_WINDOW_SECONDS:

            return "duplicate"

        # 惰性清理过期 seen 条目，防止状态无界增长。

        if len(state.seen) >= _DELIVERY_FAILURE_SEEN_MAX:

            state.seen = {

                key: seen_at

                for key, seen_at in state.seen.items()

                if now - seen_at < DELIVERY_FAILURE_DEDUP_WINDOW_SECONDS

            }

        window = [
            stamp
            for stamp in state.bucket_windows.get(bucket_key, [])
            if stamp > hour_ago
        ]

        if len(window) >= MAX_DELIVERY_FAILURES_PER_BUCKET_PER_HOUR:

            return "rate_limited"

        window.append(now)

        state.bucket_windows[bucket_key] = window

        state.seen[seen_key] = now

        return ""


def _delivery_failure_message(
    *,
    attention_id: str,
    kind: str,
    severity: str,
    stage: str,
    reason: str,
    title: str,
) -> tuple[str, str, dict[str, str]]:
    """Build (content, summary, metadata) for the inbox row; all bounded."""

    stage_label = _DELIVERY_FAILURE_STAGE_LABELS.get(stage, stage)

    summary = _clip(f"人工关注通知投递失败（{kind}/{stage}）", limit=_TITLE_LIMIT)

    lines = [
        f"人工关注通知投递失败（{stage_label}），这条关注事项可能没有被看到。",
        f"- 通知ID: {attention_id}",
        f"- 类型: {kind}",
    ]

    if severity:
        lines.append(f"- 严重度: {severity}")

    if title:
        lines.append(f"- 标题: {title}")

    if reason:
        lines.append(f"- 原因: {reason}")

    lines.append("请确认对应事项是否仍需人工处理。")

    metadata = {
        "attentionId": attention_id,
        "kind": kind,
        "severity": severity,
        "stage": stage,
        "reason": reason,
        "reportedBy": "personal_attention_service",
    }

    return "\n".join(lines), summary, metadata


def report_attention_delivery_failure(
    *,
    id: str = "",
    kind: str = "",
    severity: str = "",
    stage: str,
    reason: str = "",
    title: str = "",
) -> dict[str, Any]:
    """Write one delivery-failure report into the assistant inbox; never raises.

    Returns ``{"accepted": bool, "reason": str}``; every failure mode
    (missing assistant, rate limit, dedup window, writer error) degrades to
    ``accepted=False`` without touching the caller's path.
    """

    try:

        normalized_stage = str(stage or "").strip()

        if normalized_stage not in ATTENTION_DELIVERY_FAILURE_STAGES:

            return {"accepted": False, "reason": "invalid_stage"}

        attention_id = _clip(id or "unknown", limit=_DELIVERY_FAILURE_ID_LIMIT)

        normalized_kind = _clip(kind or "unknown", limit=_DELIVERY_FAILURE_KIND_LIMIT)

        normalized_severity = _clip(severity, limit=_DELIVERY_FAILURE_SEVERITY_LIMIT)

        normalized_reason = _clip(reason, limit=_DELIVERY_FAILURE_REASON_LIMIT)

        normalized_title = _clip(title, limit=_DELIVERY_FAILURE_TITLE_LIMIT)

        rejection = _claim_delivery_failure_slot(
            _delivery_failure_state,
            attention_id=attention_id,
            kind=normalized_kind,
            stage=normalized_stage,
            now=time.monotonic(),
        )

        if rejection:
            return {"accepted": False, "reason": rejection}

        from core.web.services import (
            agent_directory_service,
            personal_assistant_service,
        )

        assistant = (
            personal_assistant_service.get_personal_assistant().get("assistant") or {}
        )

        agent_id = str(assistant.get("agentId") or "").strip()

        if not agent_id:
            return {"accepted": False, "reason": "no_assistant"}

        content, summary, metadata = _delivery_failure_message(
            attention_id=attention_id,
            kind=normalized_kind,
            severity=normalized_severity,
            stage=normalized_stage,
            reason=normalized_reason,
            title=normalized_title,
        )

        agent_directory_service.write_agent_inbox_message(
            agent_id,
            content=content,
            summary=summary,
            kind=ATTENTION_DELIVERY_FAILURE_INBOX_KIND,
            prompt_eligible=True,
            created_by="attention_monitor",
            metadata=metadata,
        )

        return {"accepted": True, "reason": ""}

    except Exception:  # noqa: BLE001 - reporting must never break the caller

        return {"accepted": False, "reason": "error"}
