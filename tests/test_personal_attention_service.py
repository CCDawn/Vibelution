"""Attention aggregation sources feed the assistant overview without side effects."""


import dataclasses


import json


from fastapi.testclient import TestClient


from core.research.workflow.contracts.anomaly_inbox import (

    AnomalyInbox,

    AnomalyInboxItem,

    AnomalyInboxScope,

)

from core.research.workflow.definition import build_challenge_cup_workflow_definition

from core.research.workflow.definition_registry import register_or_resolve


from core.web.app import create_app

from core.web.control import CONTROL_TOKEN_HEADER, get_control_token

from core.web.services import personal_attention_service as attention

from core.web.services import (

    personal_assistant_service as service,

    pet_activity_service,

    team_service,

)

from core.web.services.team_workflow import research_projects

from core.web.services.team_workflow.research_runtime import (

    anomaly_inbox_service,

    formal_read_runtime,

    hypothesis_first_chain,

    hypothesis_first_state_v2,

)

from tests._support.workflow_ledger_helpers import (

    FIXED_NOW_MS,

    build_attempt_record,

    build_command_record,

    build_event_record,

    build_run_record,

    open_ledger_store,

)

from tests.test_personal_assistant_service import (

    finance_env as _finance_env,

)

from tests.test_personal_assistant_service import personal_env as _personal_env


finance_env = _finance_env

personal_env = _personal_env


_NEW_ENTRY_FIELDS = {"id", "kind", "severity", "title", "targetUrl", "body"}


_HUMAN_ATTENTION_COLLECTORS = (
    "collect_knowledge_review_attention",
    "collect_anomaly_attention",
    "_collect_human_gate_attention",
    "_collect_affair_reminder_attention",
)


def test_anomaly_scan_reuses_claim_sources_only_within_each_request(monkeypatch):
    from core.research.evidence import ClaimEvidenceStore
    from core.web.services.team_workflow.research_runtime import hypothesis_first_chain as chain

    reads = 0

    def evidence(_store, _team_id):
        nonlocal reads
        reads += 1
        return [{"revision": reads}]

    def collect():
        first = chain._claim_evidence_records("team-1")
        assert chain._claim_evidence_records("team-1") == first
        return first

    monkeypatch.setattr(ClaimEvidenceStore, "list", evidence)
    monkeypatch.setattr(attention, "_collect_state_v2_anomaly_entries", collect)
    assert attention._state_v2_anomaly_entries() == [{"revision": 1}]
    assert attention._state_v2_anomaly_entries() == [{"revision": 2}]
    assert chain._claim_evidence_records("team-1") == [{"revision": 3}]


def test_human_attention_feed_and_overview_share_all_four_sources(monkeypatch):
    monkeypatch.setattr(attention, "collect_stage_task_attention", lambda: ([], []))
    rows = []
    for name, kind in zip(_HUMAN_ATTENTION_COLLECTORS, (
        "knowledge_review", "anomaly", "human_gate", "affair_reminder"
    )):
        row = {"id": name, "kind": kind, "title": name}
        rows.append(row)
        monkeypatch.setattr(attention, name, lambda row=row, **_kwargs: [row])
    assert attention.collect_human_attention() == rows
    payload = {"attention": [{"id": "approval-1", "kind": "approval"}]}
    assert attention.attach_attention_to_overview(payload)["humanAttention"] == rows
    assert payload["attention"] == [{"id": "approval-1", "kind": "approval"}]


def test_human_attention_feed_isolates_each_failed_source_and_keeps_empty_overview_shape(monkeypatch):
    monkeypatch.setattr(attention, "collect_stage_task_attention", lambda: ([], []))
    def fail(**_kwargs):
        raise RuntimeError("Source unavailable")

    for broken in _HUMAN_ATTENTION_COLLECTORS:
        with monkeypatch.context() as patch:
            for name in _HUMAN_ATTENTION_COLLECTORS:
                patch.setattr(attention, name, fail if name == broken else lambda name=name, **_kwargs: [{"id": name}])
            assert attention.collect_human_attention() == [
                {"id": name} for name in _HUMAN_ATTENTION_COLLECTORS if name != broken
            ]
    for name in _HUMAN_ATTENTION_COLLECTORS:
        monkeypatch.setattr(attention, name, lambda **_kwargs: [])
    assert attention.collect_human_attention() == []
    assert attention.attach_attention_to_overview({"attention": []}) == {"attention": []}


def test_human_attention_reads_shared_stage_files_once_per_request(monkeypatch):
    calls = []
    review = {"id": "review", "kind": "knowledge_review", "severity": "high"}
    anomaly = {"id": "stage-anomaly", "kind": "anomaly", "severity": "high"}
    inbox = {"id": "inbox-anomaly", "kind": "anomaly", "severity": "critical"}

    def stages():
        calls.append("stage-scan")
        return [review], [anomaly]

    monkeypatch.setattr(attention, "collect_stage_task_attention", stages)
    monkeypatch.setattr(attention, "_state_v2_anomaly_entries", lambda: [inbox, anomaly])
    monkeypatch.setattr(attention, "_collect_human_gate_attention", lambda: [])
    monkeypatch.setattr(attention, "_collect_affair_reminder_attention", lambda: [])
    assert attention.collect_human_attention() == [review, inbox, anomaly]
    assert calls == ["stage-scan"]


def test_failed_shared_stage_scan_keeps_other_notification_sources(monkeypatch):
    def stages():
        raise OSError("stage source unavailable")

    inbox = {"id": "inbox", "kind": "anomaly", "severity": "critical"}
    gate = {"id": "gate", "actions": [{"decision": "accept"}], "meta": {"runId": "run"}}
    reminder = {"id": "reminder"}
    monkeypatch.setattr(attention, "collect_stage_task_attention", stages)
    monkeypatch.setattr(attention, "_state_v2_anomaly_entries", lambda: [inbox])
    monkeypatch.setattr(attention, "_collect_human_gate_attention", lambda: [gate])
    monkeypatch.setattr(attention, "_collect_affair_reminder_attention", lambda: [reminder])
    assert attention.collect_human_attention() == [inbox, gate, reminder]



def _team(team_id: str, name: str = "科研团队") -> dict:

    return {"teamId": team_id, "name": name, "status": "active"}



def _patch_teams(monkeypatch, *teams: dict) -> None:

    monkeypatch.setattr(

        team_service,

        "list_team_graph_references",

        lambda **_kwargs: {"teams": list(teams)},

    )



def _patch_formal_root(monkeypatch, tmp_path) -> None:

    """Point stage-task scanning at an isolated (possibly empty) teams root."""


    monkeypatch.setattr(

        research_projects,

        "formal_team_workspace_root",

        lambda team_id: tmp_path / "teams" / team_id,

    )



def _write_stage_tasks(tmp_path, team_id: str, tasks: list[dict], *, project_id: str = "proj-1") -> None:

    store = (

        tmp_path

        / "teams"

        / team_id

        / "research_projects"

        / project_id

        / "workspace"

        / "source_collection_runs"

        / "run-1"

        / "stage_session_tasks.json"

    )

    store.parent.mkdir(parents=True, exist_ok=True)

    store.write_text(json.dumps({"tasks": tasks}, ensure_ascii=False), encoding="utf-8")



def _patch_chain_questions(monkeypatch, tmp_path, question_ids: list[str]) -> None:

    chain_path = tmp_path / "hypothesis_first_chain.jsonl"

    chain_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [

        json.dumps({"recordKind": "note", "questionId": question_id}, ensure_ascii=False)

        for question_id in question_ids

    ]

    chain_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    monkeypatch.setattr(hypothesis_first_chain, "_storage_path", lambda team_id: chain_path)



def _snapshot(question_id: str, *, awaiting: int = 0, budget_problem: bool = False) -> dict:

    problems = []

    if budget_problem:

        problems.append(

            {

                "code": "budget_exceeded",

                "message": "正式运行预算耗尽，需要人工补预算",

                "sourceKind": "formal_run",

                "sourceId": "run-1",

            }

        )

    return {

        "teamId": "team-research",

        "questionId": question_id,

        "computedAt": "2026-10-18T00:00:00Z",

        "awaitingHumanCount": awaiting,

        "problems": problems,

    }



def _task(task_id: str, *, stage_id: str, status: str, **extra) -> dict:

    return {

        "taskId": task_id,

        "stageId": stage_id,

        "status": status,

        "title": f"任务 {task_id}",

        "summary": "",

        **extra,

    }



def test_knowledge_review_attention_lists_ingestion_needs_review_docks(

    personal_env, monkeypatch, tmp_path

):

    _patch_teams(monkeypatch, _team("team-research", "材料团队"))

    _patch_formal_root(monkeypatch, tmp_path)

    _write_stage_tasks(

        tmp_path,

        "team-research",

        [

            _task("task-review", stage_id="ingestion", status="needs_review"),

            _task("task-running", stage_id="ingestion", status="running"),

            _task("task-other-stage", stage_id="relations", status="needs_review"),

        ],

    )


    entries = attention.collect_knowledge_review_attention()


    assert [row["id"] for row in entries] == ["review:task-review"]

    row = entries[0]

    assert set(row) == _NEW_ENTRY_FIELDS

    assert row["kind"] == "knowledge_review"

    assert row["severity"] == "high"

    assert row["title"] == "任务 task-review"

    assert "teamId=team-research" in row["targetUrl"] and "researchProjectId=proj-1" in row["targetUrl"]

    assert row["body"].startswith("材料团队")

    # id 跨轮询稳定

    assert attention.collect_knowledge_review_attention() == entries



def test_escalated_task_reports_once_as_anomaly_not_review(

    personal_env, monkeypatch, tmp_path

):

    _patch_teams(monkeypatch, _team("team-research", "材料团队"))

    _patch_formal_root(monkeypatch, tmp_path)

    _write_stage_tasks(

        tmp_path,

        "team-research",

        [

            # 同一任务既带升级又停靠复核：只按 anomaly 报一次。

            _task(

                "task-escalated",

                stage_id="ingestion",

                status="needs_review",

                anomalyEscalation={

                    "items": [

                        {"severity": "critical", "summary": "阶段任务等待人工处理"},

                        {"severity": "medium", "summary": "次要项"},

                    ]

                },

            )

        ],

    )


    anomaly_rows = attention.collect_anomaly_attention()

    review_rows = attention.collect_knowledge_review_attention()


    assert [row["id"] for row in anomaly_rows] == ["escalation:task-escalated"]

    assert anomaly_rows[0]["severity"] == "critical"

    assert anomaly_rows[0]["kind"] == "anomaly"

    assert review_rows == []



def test_anomaly_attention_keeps_critical_high_with_stable_ids(

    personal_env, monkeypatch, tmp_path

):

    _patch_teams(monkeypatch, _team("team-research", "材料团队"))

    _patch_formal_root(monkeypatch, tmp_path)

    _patch_chain_questions(monkeypatch, tmp_path, ["SCI-001", "SCI-002"])


    def fake_project(team_id, question_id, **_kwargs):

        return _snapshot(question_id, awaiting=2, budget_problem=True)


    monkeypatch.setattr(

        hypothesis_first_state_v2, "project_hypothesis_first_state_v2", fake_project

    )


    entries = attention.collect_anomaly_attention()


    assert len(entries) == 4

    assert all(set(row) == _NEW_ENTRY_FIELDS for row in entries)

    assert all(row["kind"] == "anomaly" for row in entries)

    assert [row["severity"] for row in entries] == ["critical", "critical", "high", "high"]

    for row in entries:

        assert row["severity"] in {"critical", "high"}

        assert row["id"].startswith("anomaly:team-research|SCI-")

        assert "panel=progress" in row["targetUrl"] and "teamId=team-research" in row["targetUrl"]

        assert row["body"].startswith("材料团队 · SCI-")

    budget_rows = [row for row in entries if row["severity"] == "critical"]

    assert all("预算" in row["title"] for row in budget_rows)

    gate_rows = [row for row in entries if row["severity"] == "high"]

    assert all("等待人工" in row["title"] for row in gate_rows)

    # id 跨轮询稳定

    assert attention.collect_anomaly_attention() == entries



def test_anomaly_attention_filters_medium_and_failures_degrade(

    personal_env, monkeypatch, tmp_path

):

    _patch_teams(monkeypatch, _team("team-research", "材料团队"))

    _patch_formal_root(monkeypatch, tmp_path)

    _patch_chain_questions(monkeypatch, tmp_path, ["SCI-001", "SCI-002"])


    scope = AnomalyInboxScope(teamId="team-research", questionId="SCI-001")


    def inbox_with_kinds(*_args, **_kwargs):

        return AnomalyInbox.create(

            [

                AnomalyInboxItem.create(

                    kind="drift_sentinel_hit",

                    scope=scope,

                    first_seen_at="2026-10-18T00:00:00Z",

                    last_seen_at="2026-10-18T00:00:00Z",

                    summary="抽样漂移",

                    evidence=["problem:drift_sentinel_hit"],

                ),

                AnomalyInboxItem.create(

                    kind="budget_exhausted",

                    scope=scope,

                    first_seen_at="2026-10-18T00:00:00Z",

                    last_seen_at="2026-10-18T00:00:00Z",

                    summary="预算耗尽",

                    evidence=["problem:budget_exceeded"],

                ),

            ]

        )


    def broken_project(team_id, question_id, **_kwargs):

        if question_id == "SCI-001":

            raise hypothesis_first_state_v2.HypothesisFirstStateScopeError(

                "catalog_question_unknown", "missing", status_code=404

            )

        return _snapshot(question_id, awaiting=1)


    monkeypatch.setattr(

        hypothesis_first_state_v2, "project_hypothesis_first_state_v2", broken_project

    )

    monkeypatch.setattr(anomaly_inbox_service, "build_anomaly_inbox", inbox_with_kinds)


    entries = attention.collect_anomaly_attention()


    # SCI-001 投影失败被跳过；SCI-002 的 medium 漂移信号被过滤，只剩 critical。

    assert [row["severity"] for row in entries] == ["critical"]

    assert "预算耗尽" in entries[0]["title"]



def test_attention_sources_are_capped_and_severity_sorted(

    personal_env, monkeypatch, tmp_path

):

    _patch_teams(monkeypatch, _team("team-research", "材料团队"))

    _patch_formal_root(monkeypatch, tmp_path)

    _write_stage_tasks(

        tmp_path,

        "team-research",

        [

            _task(f"task-{index:02d}", stage_id="ingestion", status="needs_review")

            for index in range(25)

        ],

    )

    knowledge_rows = attention.collect_knowledge_review_attention()

    assert len(knowledge_rows) == attention.MAX_KNOWLEDGE_REVIEW_ITEMS


    questions = [f"SCI-{index:03d}" for index in range(1, 13)]

    _patch_chain_questions(monkeypatch, tmp_path, questions)

    monkeypatch.setattr(

        hypothesis_first_state_v2,

        "project_hypothesis_first_state_v2",

        lambda team_id, question_id, **_kwargs: _snapshot(

            question_id, awaiting=1, budget_problem=True

        ),

    )

    anomaly_rows = attention.collect_anomaly_attention()

    assert len(anomaly_rows) == attention.MAX_ANOMALY_ITEMS

    severities = [row["severity"] for row in anomaly_rows]

    assert severities == sorted(

        severities,

        key=lambda value: {"critical": 0, "high": 1, "medium": 2}[value],

    )

    assert severities.count("critical") == 12 and severities.count("high") == 8



def test_overview_route_appends_new_sources_without_touching_existing_rows(

    personal_env, monkeypatch, tmp_path

):

    _patch_teams(monkeypatch, _team("team-research", "材料团队"))

    _patch_formal_root(monkeypatch, tmp_path)

    _write_stage_tasks(

        tmp_path,

        "team-research",

        [_task("task-review", stage_id="ingestion", status="needs_review")],

    )

    _patch_chain_questions(monkeypatch, tmp_path, ["SCI-001"])

    monkeypatch.setattr(

        hypothesis_first_state_v2,

        "project_hypothesis_first_state_v2",

        lambda team_id, question_id, **_kwargs: _snapshot(

            question_id, awaiting=1, budget_problem=True

        ),

    )

    monkeypatch.setattr(

        pet_activity_service,

        "get_pet_activity",

        lambda: {

            "generatedAt": "2026-10-18T00:00:00+00:00",

            "sessions": [

                {"sessionId": "approval", "tone": "approval", "title": "等待批准"},

                {"sessionId": "failed", "tone": "error", "title": "执行失败"},

                {"sessionId": "live", "tone": "running", "title": "运行中"},

            ],

        },

    )


    client = TestClient(

        create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()}

    )

    response = client.get("/api/personal-assistant/overview")


    assert response.status_code == 200

    body = response.json()

    rows = body["attention"]

    assert rows == [

        {"id": "approval", "kind": "approval", "title": "等待批准", "sessionId": "approval"},

        {"id": "failed", "kind": "error", "title": "执行失败", "sessionId": "failed"},

    ]

    # 人类关注行走独立通道：attention 与 counts 不变量原样保留。

    human = body["humanAttention"]

    assert [row["kind"] for row in human] == ["knowledge_review", "anomaly", "anomaly"]

    assert all(set(row) == _NEW_ENTRY_FIELDS for row in human)

    # counts/pagination 语义不被新源改写

    assert body["counts"]["waiting"] == 1 and body["counts"]["failed"] == 1

    assert body["pagination"]["nextOffset"] is None

    # 翻页页不再重复扩展条目（扩展只进第一页概览）

    offset_body = client.get("/api/personal-assistant/overview?offset=1").json()

    assert offset_body["attention"] == [

        {"id": "failed", "kind": "error", "title": "执行失败", "sessionId": "failed"}

    ]

    # 人类关注通道与分页无关：每一页携带同一份列表，前端读模型缝合多页时

    # 只保留末页附加字段，扩展不能只挂第一页（129 会话 >100 必分页场景）。

    assert offset_body["humanAttention"] == human



def test_missing_stores_and_broken_collectors_never_break_the_overview(

    personal_env, monkeypatch, tmp_path

):

    _patch_formal_root(monkeypatch, tmp_path)

    # 隔离环境没有团队/阶段任务/链路账本：两个新源都合法为空。

    assert attention.collect_knowledge_review_attention() == []

    assert attention.collect_anomaly_attention() == []

    first_page = {"attention": [], "pagination": {"offset": 0}}

    assert attention.attach_attention_to_overview(first_page) == first_page


    # 收集器自身异常时组合函数 fail-open：概览原样返回。

    _patch_teams(monkeypatch, _team("team-research"))

    monkeypatch.setattr(

        attention,

        "collect_knowledge_review_attention",

        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),

    )

    payload = {

        "attention": [{"id": "approval", "kind": "approval", "title": "等待批准", "sessionId": "approval"}],

        "pagination": {"offset": 0},

    }

    attached = attention.attach_attention_to_overview(payload)

    assert [row["id"] for row in attached["attention"]] == ["approval"]

    # 空扩展不落键：旧 wire 形状在无人类关注事项时保持不变。

    assert "humanAttention" not in attached



def test_overview_route_serializes_new_attention_kinds(personal_env, monkeypatch):

    payload = {

        "generatedAt": "2026-10-18T00:00:00+00:00",

        "counts": {"agents": 0, "sessions": 0, "running": 0, "waiting": 0, "failed": 0},

        "agents": [],

        "sessions": [],

        "attention": [

            {

                "id": "cand-review",

                "kind": "knowledge_review",

                "severity": "high",

                "title": "知识包",

                "targetUrl": "/teams?teamId=team-research",

                "body": "等待治理复核",

            },

            {

                "id": "anomaly:team-research|SCI-001||run-1||budget_exhausted",

                "kind": "anomaly",

                "severity": "critical",

                "title": "预算耗尽",

                "targetUrl": "/teams?teamId=team-research&panel=progress",

                "body": "团队 · SCI-001",

            },

        ],

        "pagination": {"offset": 0, "limit": 100, "nextOffset": None, "revision": "r"},

    }


    monkeypatch.setattr(service, "get_platform_overview", lambda **_kwargs: payload)

    client = TestClient(

        create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()}

    )

    response = client.get("/api/personal-assistant/overview")

    assert response.status_code == 200

    body = response.json()

    assert [row["kind"] for row in body["attention"]] == ["knowledge_review", "anomaly"]

    assert body["attention"][0]["severity"] == "high"

    assert body["attention"][1]["severity"] == "critical"


    # 既有 approval 行保持 wire 兼容：不铺新字段、不改写原值。

    payload["attention"].append(

        {"id": "session-1", "kind": "approval", "title": "等待批准", "sessionId": "session-1"}

    )

    response = client.get("/api/personal-assistant/overview")

    assert response.status_code == 200

    assert response.json()["attention"][2] == {

        "id": "session-1",

        "kind": "approval",

        "title": "等待批准",

        "sessionId": "session-1",

    }



def test_severity_values_come_from_the_frozen_contract_table():

    from core.research.workflow.contracts.anomaly_inbox import (

        ANOMALY_KIND_SEVERITY,

        ANOMALY_SEVERITIES,

    )


    # 收集器只用冻结 severity 词汇；knowledge_review 的 high 也落在同一闭集。

    assert attention.ANOMALY_SEVERITY_HIGH in ANOMALY_SEVERITIES

    assert attention.ANOMALY_SEVERITY_CRITICAL in ANOMALY_SEVERITIES

    assert set(ANOMALY_KIND_SEVERITY.values()) <= set(ANOMALY_SEVERITIES)


class _FakeAffairsService:
    """Records the requested agent and replays a canned projection."""

    def __init__(self, items):
        self.items = items
        self.requested_agent_ids = []

    def list_items(self, agent_id, *, kind="", status=""):
        self.requested_agent_ids.append(agent_id)
        return {
            "schemaVersion": 1,
            "agentId": agent_id,
            "items": [dict(item) for item in self.items],
            "counts": {"open": 0, "overdue": 0, "done": 0},
            "updatedAt": "2026-10-19T00:00:00Z",
        }


def _affair(item_id, *, status="open", due_state="overdue", due_at="2026-10-19T02:00:00Z", title="整理周报"):
    return {
        "schemaVersion": 1,
        "itemId": item_id,
        "kind": "todo",
        "title": title,
        "note": "",
        "status": status,
        "dueAt": due_at,
        "createdAt": "2026-10-17T00:00:00Z",
        "updatedAt": "2026-10-19T00:00:00Z",
        "completedAt": "",
        "sourceTurnId": "",
        "dueState": due_state,
    }


def _patch_affairs(monkeypatch, fake):
    from core.web.services import personal_affairs_service as affairs_web

    monkeypatch.setattr(affairs_web, "get_personal_affairs_service", lambda: fake)
    return affairs_web


def test_affair_reminder_attention_requires_an_assistant(monkeypatch):
    monkeypatch.setattr(service, "profile_agent", lambda: None)
    from core.web.services.personal_affairs_service import (
        collect_affair_reminder_attention,
    )

    assert collect_affair_reminder_attention() == []


def test_affair_reminder_attention_maps_due_open_items_with_day_scoped_ids(monkeypatch):
    fake = _FakeAffairsService([
        _affair("affair-today", due_state="today", due_at="2026-10-19T10:00:00Z", title="和用户复盘"),
        _affair("affair-overdue", due_state="overdue", title="  整理  周报 "),
        _affair("affair-done", status="done", due_state="none", due_at=""),
        _affair("affair-cancelled", status="cancelled"),
        _affair("affair-upcoming", due_state="upcoming", due_at="2026-10-25T00:00:00Z"),
        _affair("affair-nodue", due_state="none", due_at=""),
    ])
    _patch_affairs(monkeypatch, fake)
    monkeypatch.setattr(service, "profile_agent", lambda: {"agentId": "assistant-agent"})
    from core.web.services.personal_affairs_service import (
        collect_affair_reminder_attention,
    )

    rows = collect_affair_reminder_attention()
    assert fake.requested_agent_ids == ["assistant-agent"]
    assert [row["id"].split(":")[1] for row in rows] == ["affair-overdue", "affair-today"]
    assert all(row["kind"] == "affair_reminder" for row in rows)
    assert rows[0]["severity"] == "high"
    assert rows[0]["title"] == "事务提醒：整理 周报"
    assert rows[0]["body"].startswith("截止 ")
    assert rows[0]["targetUrl"] == "/personal-assistant"
    assert rows[1]["severity"] == "medium"
    day_key = rows[0]["id"].rsplit(":", 1)[1]
    assert len(day_key) == 8 and day_key.isdigit()
    assert {row["id"].split(":")[1] for row in rows}.isdisjoint(
        {"affair-done", "affair-cancelled", "affair-upcoming", "affair-nodue"}
    )


def test_affair_reminder_attention_caps_and_degrades_safely(monkeypatch):
    fake = _FakeAffairsService([_affair(f"affair-{index}") for index in range(8)])
    affairs_web = _patch_affairs(monkeypatch, fake)
    monkeypatch.setattr(service, "profile_agent", lambda: {"agentId": "assistant-agent"})

    rows = affairs_web.collect_affair_reminder_attention(limit=3)
    assert len(rows) == 3

    def _boom():
        raise RuntimeError("ledger unavailable")

    monkeypatch.setattr(affairs_web, "get_personal_affairs_service", _boom)
    assert affairs_web.collect_affair_reminder_attention() == []

    def _conflict():
        raise RuntimeError("multiple assistant identities")

    monkeypatch.setattr(service, "profile_agent", _conflict)
    monkeypatch.setattr(affairs_web, "get_personal_affairs_service", lambda: fake)
    assert affairs_web.collect_affair_reminder_attention() == []


def test_overview_attaches_affair_reminders_without_touching_session_attention(monkeypatch):
    monkeypatch.setattr(attention, "collect_knowledge_review_attention", lambda **_kwargs: [])
    monkeypatch.setattr(attention, "collect_anomaly_attention", lambda **_kwargs: [])
    reminder = {
        "id": "affair-reminder:affair-1:20261019",
        "kind": "affair_reminder",
        "severity": "high",
        "title": "事务提醒：整理周报",
        "body": "截止 2026-10-19T02:00:00Z",
        "targetUrl": "/personal-assistant",
    }
    monkeypatch.setattr(attention, "_collect_affair_reminder_attention", lambda: [dict(reminder)])
    payload = {
        "generatedAt": "2026-10-19T00:00:00+00:00",
        "counts": {"agents": 0, "sessions": 0, "running": 0, "waiting": 0, "failed": 0},
        "agents": [],
        "sessions": [],
        "attention": [],
    }
    attached = attention.attach_attention_to_overview(payload)
    assert attached["humanAttention"] == [reminder]
    assert attached["attention"] == []


# -- 研究工作流人工门（ledger pending human tasks → humanAttention） ----------


def _ledger_store_with_human_gate(
    tmp_path,
    *,
    run_status: str = "waiting_human",
    team_id: str = "research-team",
    task_id: str = "ht-gate-1",
):
    """Real ledger: one run + waiting node attempt + pending human task."""
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    definition = build_challenge_cup_workflow_definition()
    identity = register_or_resolve(definition)
    run = dataclasses.replace(
        build_run_record(
            run_id="run-gate",
            team_id=team_id,
            status=run_status,
            last_event_sequence=1,
        ),
        workflow_id=definition.workflowId,
        workflow_version_id=identity.workflowVersionId,
        structure_hash=identity.structureHash,
    )
    attempt = build_attempt_record(
        node_run_id="nr-gate-1",
        run_id="run-gate",
        node_id="problem_understanding",
        status="waiting_human",
    )
    command = build_command_record(
        command_id="cmd-gate-1",
        run_id="run-gate",
        node_id="problem_understanding",
    )
    attempt = dataclasses.replace(attempt, command_id="cmd-gate-1")

    def mutate(uow):
        uow.repository.insert_run(run)
        uow.repository.insert_event(
            build_event_record(1, run_id="run-gate", event_id="evt-created-run-gate")
        )
        uow.repository.insert_command(command)
        uow.repository.insert_attempt(attempt)
        uow.repository.insert_human_task(
            task_id=task_id,
            run_id="run-gate",
            node_run_id="nr-gate-1",
            handoff_id=None,
            task_kind="knowledge_gate",
            prompt_json="{}",
            created_at_ms=FIXED_NOW_MS,
        )

    store.submit(mutate, force_flush=True).result(timeout=10)
    return store


def _patch_read_store(monkeypatch, store) -> None:
    monkeypatch.setattr(formal_read_runtime, "get_formal_read_store", lambda: store)


def test_human_gate_attention_exposes_pending_ledger_gate_rows(
    personal_env, monkeypatch, tmp_path
):
    _patch_formal_root(monkeypatch, tmp_path)
    store = _ledger_store_with_human_gate(tmp_path)
    try:
        _patch_read_store(monkeypatch, store)
        _patch_teams(monkeypatch, _team("research-team"))
        entries = attention._collect_human_gate_attention()
        assert [row["id"] for row in entries] == ["human-gate:ht-gate-1"]
        row = entries[0]
        assert row["kind"] == "human_gate"
        assert row["severity"] == "high"
        assert row["title"] == "研究工作流等待人工审批"
        # run 标题降级链：questionId（SCI-096）优先；节点标签来自固定定义。
        assert row["body"] == "SCI-096 · 问题理解 等待人工确认"
        assert "teamId=research-team" in row["targetUrl"]
        assert "runId=run-gate" in row["targetUrl"]
        assert "node=problem_understanding" in row["targetUrl"]
        assert "panel=node" in row["targetUrl"]
        assert row["actions"] == [
            {"label": "接受", "decision": "accept"},
            {"label": "驳回", "decision": "reject"},
        ]
        assert row["meta"] == {
            "teamId": "research-team",
            "runId": "run-gate",
            "nodeId": "problem_understanding",
            "taskId": "ht-gate-1",
            "decisions": ["accept", "reject", "revise"],
        }
        # id 跨轮询稳定
        assert attention._collect_human_gate_attention() == entries
    finally:
        store.close()


def test_human_gate_attention_disappears_after_resolve(
    personal_env, monkeypatch, tmp_path
):
    _patch_formal_root(monkeypatch, tmp_path)
    store = _ledger_store_with_human_gate(tmp_path)
    try:
        _patch_read_store(monkeypatch, store)
        _patch_teams(monkeypatch, _team("research-team"))
        assert attention._collect_human_gate_attention()

        def resolve(uow):
            assert uow.repository.update_human_task_decision(
                "ht-gate-1", "accepted", FIXED_NOW_MS + 1000
            )

        store.submit(resolve, force_flush=True).result(timeout=10)
        # 行是派生读：决策落账后自动消失，无需任何清理写入。
        assert attention._collect_human_gate_attention() == []
    finally:
        store.close()


def test_human_gate_attention_filters_and_fails_closed(
    personal_env, monkeypatch, tmp_path
):
    _patch_formal_root(monkeypatch, tmp_path)
    _patch_teams(monkeypatch, _team("research-team"))
    # 只收集 waiting_human 停靠：running run 上的 pending task 不投影。
    running = _ledger_store_with_human_gate(tmp_path / "running", run_status="running")
    try:
        _patch_read_store(monkeypatch, running)
        assert attention._collect_human_gate_attention() == []
    finally:
        running.close()
    # 团队不在活动清单：跳过。
    foreign = _ledger_store_with_human_gate(tmp_path / "foreign", team_id="other-team")
    try:
        _patch_read_store(monkeypatch, foreign)
        assert attention._collect_human_gate_attention() == []
    finally:
        foreign.close()
    # read runtime 未配置：fail-closed 为空，绝不抛出。
    def _unavailable():
        raise formal_read_runtime.FormalReadRuntimeUnavailable()

    monkeypatch.setattr(formal_read_runtime, "get_formal_read_store", _unavailable)
    assert attention._collect_human_gate_attention() == []
    # ledger 读取失败（store 已关闭）同样降级为空。
    closed = _ledger_store_with_human_gate(tmp_path / "closed")
    closed.close()
    _patch_read_store(monkeypatch, closed)
    assert attention._collect_human_gate_attention() == []


def test_overview_route_serializes_human_gate_rows_with_actions_and_meta(
    personal_env, monkeypatch, tmp_path
):
    _patch_formal_root(monkeypatch, tmp_path)
    store = _ledger_store_with_human_gate(tmp_path)
    try:
        _patch_read_store(monkeypatch, store)
        _patch_teams(monkeypatch, _team("research-team"))
        monkeypatch.setattr(
            pet_activity_service,
            "get_pet_activity",
            lambda: {
                "generatedAt": "2026-10-18T00:00:00+00:00",
                "sessions": [
                    {"sessionId": "live", "tone": "running", "title": "运行中"},
                ],
            },
        )
        client = TestClient(
            create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()}
        )
        response = client.get("/api/personal-assistant/overview")
        assert response.status_code == 200
        human = response.json()["humanAttention"]
        assert [row["kind"] for row in human] == ["human_gate"]
        row = human[0]
        assert row["id"] == "human-gate:ht-gate-1"
        assert row["severity"] == "high"
        assert row["actions"] == [
            {"label": "接受", "decision": "accept"},
            {"label": "驳回", "decision": "reject"},
        ]
        assert row["meta"]["taskId"] == "ht-gate-1"
        assert row["meta"]["runId"] == "run-gate"
    finally:
        store.close()
