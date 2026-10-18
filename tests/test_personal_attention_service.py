"""Attention aggregation sources feed the assistant overview without side effects."""


import json


from fastapi.testclient import TestClient


from core.research.workflow.contracts.anomaly_inbox import (

    AnomalyInbox,

    AnomalyInboxItem,

    AnomalyInboxScope,

)

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

    hypothesis_first_chain,

    hypothesis_first_state_v2,

)

from tests.test_personal_assistant_service import (

    finance_env as _finance_env,

)

from tests.test_personal_assistant_service import personal_env as _personal_env


finance_env = _finance_env

personal_env = _personal_env


_NEW_ENTRY_FIELDS = {"id", "kind", "severity", "title", "targetUrl", "body"}



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

    assert len(rows) == 5

    assert rows[0] == {"id": "approval", "kind": "approval", "title": "等待批准", "sessionId": "approval"}

    assert rows[1] == {"id": "failed", "kind": "error", "title": "执行失败", "sessionId": "failed"}

    assert [row["kind"] for row in rows[2:]] == ["knowledge_review", "anomaly", "anomaly"]

    assert all(set(row) == _NEW_ENTRY_FIELDS for row in rows[2:])

    # counts/pagination 语义不被新源改写

    assert body["counts"]["waiting"] == 1 and body["counts"]["failed"] == 1

    assert body["pagination"]["nextOffset"] is None

    # 翻页页不再重复扩展条目（扩展只进第一页概览）

    assert client.get("/api/personal-assistant/overview?offset=1").json()["attention"] == [

        {"id": "failed", "kind": "error", "title": "执行失败", "sessionId": "failed"}

    ]



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
