"""完成类事件（派遣回执/run 完成/会话完成）进 humanAttention 通道的行为。

防刷屏是硬要求：新鲜度窗口、聚合稳定 id、每次采集上限三层都要有断言；
targetUrl 必须落到真实页面（派遣 tab / run 进度 / 会话页）而不是空状态页。
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import (
    agent_directory_service,
    personal_attention_completion_service as completion,
    personal_attention_service as attention,
    pet_activity_service,
    session_service,
)
from core.web.services import personal_assistant_dispatches_service as dispatches_service
from core.web.services.team_workflow.research_runtime import formal_read_runtime

from core.web.services import personal_assistant_service as _assistant_service

from tests.test_personal_assistant_service import (
    finance_env as _finance_env,
)
from tests.test_personal_assistant_service import personal_env as _personal_env

# 供 pytest 识别的无下划线 fixture 名（与 test_personal_attention_service 同法）。
finance_env = _finance_env
personal_env = _personal_env

NOW = 1_800_000_000.0


@pytest.fixture(autouse=True)
def _isolated_self_wake_agents(monkeypatch):
    monkeypatch.setattr(
        agent_directory_service, "find_agent_ids_by_metadata", lambda *_args, **_kwargs: []
    )


def _iso(epoch_seconds: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 派遣回执
# ---------------------------------------------------------------------------


class _FakeDispatchQuery:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def __call__(self, **_kwargs):
        self.calls += 1
        return self.payload


def _dispatch(message_id, *, receipts=None, target="研究员-01", summary="调研量子纠错"):
    return {
        "messageId": message_id,
        "threadId": "thread-1",
        "targetAgentId": "agent-1",
        "targetAgentName": target,
        "targetSessionId": "session-1",
        "summary": summary,
        "deliveryStatus": "read",
        "sentAt": _iso(NOW - 600),
        "receipts": receipts or [],
    }


def _receipt(message_id, received_at, summary="已完成调研并回传"):
    return {
        "messageId": message_id,
        "sourceAgentId": "agent-1",
        "sourceAgentName": "研究员-01",
        "summary": summary,
        "status": "done",
        "receivedAt": received_at,
    }


def test_dispatch_receipt_attention_reports_fresh_paired_receipt(monkeypatch):
    fake = _FakeDispatchQuery(
        {
            "assistantAgentId": "assistant",
            "dispatches": [
                _dispatch(
                    "msg-1",
                    receipts=[
                        _receipt("r-old", _iso(NOW - 3600)),
                        _receipt("r-new", _iso(NOW - 30)),
                    ],
                ),
                _dispatch("msg-2", receipts=[]),
            ],
            "unmatchedReceipts": [],
        }
    )
    monkeypatch.setattr(dispatches_service, "list_personal_assistant_dispatches", fake)

    rows = completion.collect_dispatch_receipt_attention(now=NOW)
    # 一条派遣只报一行（多条回执聚合），无回执的派遣不报。
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "dispatch-receipt:msg-1"
    assert row["kind"] == "dispatch_receipt"
    assert row["severity"] == "info"
    assert "研究员-01" in row["title"]
    # targetUrl 必须落到 PA 工作台派遣 tab，不许是空状态页。
    assert row["targetUrl"] == "/personal-assistant?panel=dispatches"


def test_dispatch_receipt_attention_window_blocks_stale_receipts(monkeypatch):
    fake = _FakeDispatchQuery(
        {
            "assistantAgentId": "assistant",
            "dispatches": [
                _dispatch("msg-stale", receipts=[_receipt("r-1", _iso(NOW - 3600))]),
                _dispatch("msg-nostamp", receipts=[_receipt("r-2", "")]),
                _dispatch("msg-fresh", receipts=[_receipt("r-3", _iso(NOW - 60))]),
            ],
            "unmatchedReceipts": [],
        }
    )
    monkeypatch.setattr(dispatches_service, "list_personal_assistant_dispatches", fake)

    rows = completion.collect_dispatch_receipt_attention(now=NOW)
    # 窗口外的旧回执与无时间戳回执都不重放——重启/跨天不弹旧消息。
    assert [row["id"] for row in rows] == ["dispatch-receipt:msg-fresh"]


def test_dispatch_receipt_attention_degrades_without_assistant_or_on_error(monkeypatch):
    from core.web.services.personal_assistant_dispatches_service import (
        PersonalAssistantMissingError,
    )

    def _missing(**_kwargs):
        raise PersonalAssistantMissingError("no assistant")

    monkeypatch.setattr(dispatches_service, "list_personal_assistant_dispatches", _missing)
    assert completion.collect_dispatch_receipt_attention(now=NOW) == []

    def _boom(**_kwargs):
        raise RuntimeError("inbox unavailable")

    monkeypatch.setattr(dispatches_service, "list_personal_assistant_dispatches", _boom)
    assert completion.collect_dispatch_receipt_attention(now=NOW) == []


# ---------------------------------------------------------------------------
# 科研 run 完成
# ---------------------------------------------------------------------------


class _FakeQueryService:
    def __init__(self, runs_by_team):
        self.runs_by_team = runs_by_team

    def list_runs(self, *, team_id, workflow_id):
        return {"workflowId": workflow_id, "runs": self.runs_by_team.get(team_id, [])}


def _run(run_id, *, status="succeeded", completed_ms=None, question="SCI-001", team="team-r"):
    return {
        "runId": run_id,
        "teamId": team,
        "questionId": question,
        "status": status,
        "completedAtMs": completed_ms,
        "updatedAtMs": completed_ms if completed_ms is not None else (NOW * 1000),
    }


@pytest.fixture()
def active_team(monkeypatch):
    monkeypatch.setattr(
        attention, "_active_teams", lambda: [{"teamId": "team-r", "teamName": "攻坚一组"}]
    )


def test_run_completed_attention_reports_recent_succeeded_run(active_team, monkeypatch):
    fake = _FakeQueryService(
        {"team-r": [_run("run-1", completed_ms=(NOW - 60) * 1000)]}
    )
    monkeypatch.setattr(formal_read_runtime, "get_query_service", lambda: fake)

    rows = completion.collect_run_completed_attention(now=NOW)
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "run-completed:team-r:run-1"
    assert row["kind"] == "run_completed"
    assert row["severity"] == "info"
    assert "SCI-001" in row["title"]
    # targetUrl 落到该 run 的工作流进度视图，带 teamId 与 runId。
    assert row["targetUrl"] == (
        "/teams?teamId=team-r&researchView=workflow"
        "&workflowId=challenge-cup-research&runId=run-1&panel=progress"
    )


def test_run_completed_attention_ignores_failed_and_stale_runs(active_team, monkeypatch):
    fake = _FakeQueryService(
        {
            "team-r": [
                _run("run-failed", status="failed", completed_ms=(NOW - 60) * 1000),
                _run("run-cancelled", status="cancelled", completed_ms=(NOW - 60) * 1000),
                _run("run-stale", completed_ms=(NOW - 7200) * 1000),
                _run("run-fresh", completed_ms=(NOW - 120) * 1000),
            ]
        }
    )
    monkeypatch.setattr(formal_read_runtime, "get_query_service", lambda: fake)

    rows = completion.collect_run_completed_attention(now=NOW)
    # 失败 run 由 anomaly 通道覆盖；窗口外的成功完成不重放。
    assert [row["id"] for row in rows] == ["run-completed:team-r:run-fresh"]


def test_run_completed_attention_caps_and_degrades(active_team, monkeypatch):
    fake = _FakeQueryService(
        {
            "team-r": [
                _run(f"run-{index}", completed_ms=(NOW - index) * 1000)
                for index in range(10)
            ]
        }
    )
    monkeypatch.setattr(formal_read_runtime, "get_query_service", lambda: fake)
    assert len(completion.collect_run_completed_attention(now=NOW)) == completion.MAX_RUN_COMPLETED_ITEMS

    def _unavailable():
        raise RuntimeError("read runtime unavailable")

    monkeypatch.setattr(formal_read_runtime, "get_query_service", _unavailable)
    assert completion.collect_run_completed_attention(now=NOW) == []


# ---------------------------------------------------------------------------
# 会话完成
# ---------------------------------------------------------------------------


def _pet_row(
    session_id, updated_at, *, tone="completed", title="量子纠错调研",
    agent="研究员-01", agent_id="agent-1",
):
    return {
        "sessionId": session_id,
        "title": title,
        "agentId": agent_id,
        "agentDisplayName": agent,
        "tone": tone,
        "phase": "completed",
        "updatedAt": updated_at,
    }


def test_session_completed_attention_maps_recent_completion_to_session_page(monkeypatch):
    monkeypatch.setattr(
        pet_activity_service,
        "get_pet_activity",
        lambda: {
            "sessions": [
                _pet_row("session-a", _iso(NOW - 5)),
                _pet_row("session-running", _iso(NOW - 3), tone="running"),
            ]
        },
    )
    monkeypatch.setattr(session_service, "list_sessions", lambda: [])

    rows = completion.collect_session_completed_attention(now=NOW)
    assert len(rows) == 1
    row = rows[0]
    assert row["id"].startswith("session-completed:session-a:")
    assert row["kind"] == "session_completed"
    assert row["severity"] == "info"
    # targetUrl 直达该会话页。
    assert row["targetUrl"] == "/chat?session=session-a"


def test_session_completed_attention_excludes_research_fanout_workers(monkeypatch):
    monkeypatch.setattr(
        pet_activity_service,
        "get_pet_activity",
        lambda: {
            "sessions": [
                _pet_row("session-child", _iso(NOW - 5)),
                _pet_row("session-parented", _iso(NOW - 4)),
                _pet_row("session-mine", _iso(NOW - 3)),
            ]
        },
    )
    monkeypatch.setattr(
        session_service,
        "list_sessions",
        lambda: [
            {"id": "session-child", "sessionKind": "child"},
            {"id": "session-parented", "parentSessionId": "session-root"},
            {"id": "session-mine", "sessionKind": "primary"},
        ],
    )

    rows = completion.collect_session_completed_attention(now=NOW)
    # 科研/自动会话每轮的“完成”不逐条推送，只留用户可见会话。
    assert len(rows) == 1
    assert rows[0]["targetUrl"] == "/chat?session=session-mine"


@pytest.mark.parametrize("worker_status", ["active", "archived"])
def test_session_completed_attention_excludes_self_wake_workers_only(monkeypatch, worker_status):
    def find_agents(key, value, *, status):
        if key == "virtualHumanSelfWake" and value is True and status == worker_status:
            return ["self-wake-worker"]
        return []

    monkeypatch.setattr(agent_directory_service, "find_agent_ids_by_metadata", find_agents)
    monkeypatch.setattr(
        pet_activity_service,
        "get_pet_activity",
        lambda: {
            "sessions": [
                _pet_row("hidden-work", _iso(NOW - 1), agent_id="self-wake-worker"),
                _pet_row("visible-probe", _iso(NOW - 2), agent_id="self-wake-worker"),
                _pet_row("companion-chat", _iso(NOW - 3), agent_id="companion"),
                # A display name alone must never suppress an ordinary chat.
                _pet_row("normal-chat", _iso(NOW - 4), agent="洛天依的自主行动"),
            ]
        },
    )
    monkeypatch.setattr(
        session_service,
        "list_sessions",
        lambda: [
            {"id": "hidden-work", "sessionKind": "main", "hiddenFromIndex": True},
            {"id": "visible-probe", "sessionKind": "main", "hiddenFromIndex": False},
            {"id": "companion-chat", "sessionKind": "main"},
            {"id": "normal-chat", "sessionKind": "main"},
        ],
    )

    rows = completion.collect_session_completed_attention(now=NOW)

    assert [row["targetUrl"] for row in rows] == [
        "/chat?session=companion-chat", "/chat?session=normal-chat",
    ]
    assert rows[1]["body"] == "洛天依的自主行动"


def test_session_completed_attention_self_wake_identity_failure_stays_silent(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise RuntimeError("Agent registry unavailable")

    monkeypatch.setattr(agent_directory_service, "find_agent_ids_by_metadata", unavailable)
    monkeypatch.setattr(
        pet_activity_service,
        "get_pet_activity",
        lambda: {"sessions": [_pet_row("visible-probe", _iso(NOW - 1))]},
    )
    monkeypatch.setattr(session_service, "list_sessions", lambda: [])
    monkeypatch.setattr(completion, "collect_dispatch_receipt_attention", lambda: [{"id": "receipt"}])
    monkeypatch.setattr(completion, "collect_run_completed_attention", lambda: [{"id": "run"}])

    # Unverified completion candidates stay silent; other attention sources survive.
    assert completion.collect_session_completed_attention(now=NOW) == []
    assert completion.collect_completion_attention() == [{"id": "receipt"}, {"id": "run"}]


def test_session_completed_attention_new_turn_gets_new_id(monkeypatch):
    stamps = [_iso(NOW - 30), _iso(NOW - 5)]
    monkeypatch.setattr(
        pet_activity_service,
        "get_pet_activity",
        lambda: {"sessions": [_pet_row("session-a", stamps.pop())]},
    )
    monkeypatch.setattr(session_service, "list_sessions", lambda: [])

    first = completion.collect_session_completed_attention(now=NOW)
    second = completion.collect_session_completed_attention(now=NOW)
    # 同一会话下一轮完成是新事件（id 带完成时间戳），不是被账本压住的旧 id。
    assert first[0]["id"] != second[0]["id"]


def test_session_completed_attention_skips_rows_without_stable_updated_at(monkeypatch):
    monkeypatch.setattr(
        pet_activity_service,
        "get_pet_activity",
        lambda: {
            "sessions": [
                # 缺 updatedAt：id 时间戳段没有稳定来源，15s 脉冲内逐轮都会
                # 生成新 id，账本压不住 → 直接跳过，不产通知。
                _pet_row("session-nostamp", ""),
                _pet_row("session-stamped", _iso(NOW - 5)),
            ]
        },
    )
    monkeypatch.setattr(session_service, "list_sessions", lambda: [])

    rows = completion.collect_session_completed_attention(now=NOW)
    assert len(rows) == 1
    assert rows[0]["id"].startswith("session-completed:session-stamped:")


def test_session_completed_attention_caps_and_degrades(monkeypatch):
    monkeypatch.setattr(
        pet_activity_service,
        "get_pet_activity",
        lambda: {
            "sessions": [
                _pet_row(f"session-{index}", _iso(NOW - index)) for index in range(8)
            ]
        },
    )
    monkeypatch.setattr(session_service, "list_sessions", lambda: [])
    assert len(completion.collect_session_completed_attention(now=NOW)) == (
        completion.MAX_SESSION_COMPLETED_ITEMS
    )

    def _boom():
        raise RuntimeError("activity unavailable")

    monkeypatch.setattr(pet_activity_service, "get_pet_activity", _boom)
    assert completion.collect_session_completed_attention(now=NOW) == []


# ---------------------------------------------------------------------------
# 聚合 + lane 接线
# ---------------------------------------------------------------------------


def test_completion_aggregation_caps_across_sources(monkeypatch):
    monkeypatch.setattr(
        completion,
        "collect_dispatch_receipt_attention",
        lambda **_kwargs: [
            {"id": f"dispatch-receipt:d{index}", "kind": "dispatch_receipt",
             "severity": "info", "title": "t", "targetUrl": "/x", "body": "b"}
            for index in range(4)
        ],
    )
    monkeypatch.setattr(
        completion,
        "collect_run_completed_attention",
        lambda **_kwargs: [
            {"id": f"run-completed:r{index}", "kind": "run_completed",
             "severity": "info", "title": "t", "targetUrl": "/x", "body": "b"}
            for index in range(4)
        ],
    )
    monkeypatch.setattr(
        completion,
        "collect_session_completed_attention",
        lambda **_kwargs: [],
    )
    rows = completion.collect_completion_attention()
    assert len(rows) == completion.MAX_COMPLETION_ITEMS


def test_completion_lane_is_wired_into_human_attention(monkeypatch):
    monkeypatch.setattr(attention, "collect_stage_task_attention", lambda: ([], []))
    row = {
        "id": "run-completed:team-r:run-1",
        "kind": "run_completed",
        "severity": "info",
        "title": "研究运行完成",
        "targetUrl": "/teams",
        "body": "攻坚一组",
    }
    monkeypatch.setattr(completion, "collect_completion_attention", lambda **_kwargs: [row])
    items = attention.collect_human_attention()
    assert row in items
    attention._reset_human_attention_cache_for_tests()


def test_overview_carries_completion_lane_on_every_page(personal_env, monkeypatch):
    """分页陷阱守卫：扩展 lane 必须每页同一份，不能只挂第一页。"""

    row = {
        "id": "dispatch-receipt:msg-9",
        "kind": "dispatch_receipt",
        "severity": "info",
        "title": "派遣回执",
        "targetUrl": "/personal-assistant?panel=dispatches",
        "body": "调研完成",
    }

    seen_offsets: list[int] = []

    def _overview(*, offset: int = 0, limit: int = 100, **_kwargs):
        seen_offsets.append(offset)
        sessions = [
            {"id": f"session-{index}", "agentId": "", "title": "s",
             "status": "ready", "turnId": "", "currentPhase": "idle"}
            for index in range(4)
        ]
        page = sessions[offset:offset + limit]
        next_offset = offset + limit if offset + limit < len(sessions) else None
        return {
            "generatedAt": "2026-10-21T00:00:00+00:00",
            "counts": {"agents": 0, "sessions": 0, "running": 0, "waiting": 0, "failed": 0},
            "agents": [],
            "sessions": page,
            "attention": [],
            "pagination": {"offset": offset, "limit": limit,
                           "nextOffset": next_offset, "revision": "r"},
        }

    monkeypatch.setattr(_assistant_service, "get_platform_overview", _overview)
    monkeypatch.setattr(attention, "collect_stage_task_attention", lambda: ([], []))
    monkeypatch.setattr(completion, "collect_completion_attention", lambda **_kwargs: [dict(row)])

    client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})
    first = client.get("/api/personal-assistant/overview", params={"offset": 0, "limit": 2})
    second = client.get("/api/personal-assistant/overview", params={"offset": 2, "limit": 2})
    assert first.status_code == 200 and second.status_code == 200
    first_body = first.json()
    second_body = second.json()
    # 会话行分页推进（两页真的不同），但 humanAttention lane 两页同份。
    assert seen_offsets == [0, 2]
    assert [s["id"] for s in first_body["sessions"]] == ["session-0", "session-1"]
    assert [s["id"] for s in second_body["sessions"]] == ["session-2", "session-3"]
    assert first_body["humanAttention"] == [row]
    assert second_body["humanAttention"] == [row]
    # 会话派生 attention 的旧不变量不受影响（行数 === waiting + failed === 0）。
    assert first_body["attention"] == [] and second_body["attention"] == []
