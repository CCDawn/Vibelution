"""Actual Key_Tools, executor, runtime identity and HTTP projection integration."""

import json
from io import BytesIO
from unittest.mock import Mock

from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import team_knowledge_service as knowledge
from tests.helpers.tool_authorization import authorized_agent_tool_executor
from tests.test_financial_knowledge_service import (
    EXCERPT,
    evidence,
    review,
)
from tests.test_financial_knowledge_service import (
    finance_env as _finance_env,
)
from tests.test_financial_report_tools import completion
from tools import financial_memory_tools, financial_report_tools
from tools.Key_Tools import create_key_tools

finance_env = _finance_env

STAGE = "financial_evidence_stage_tool"
SEARCH = "financial_evidence_search_tool"
WITHDRAW = "financial_evidence_withdraw_tool"
REPORT = "financial_report_query_tool"


def test_actual_executor_stages_and_searches_only_after_review(finance_env):
    env = finance_env
    meta = evidence()
    meta.pop("excerptSha256")
    with authorized_agent_tool_executor(
        env["owner"], executable_tools=(STAGE, SEARCH, WITHDRAW)
    ) as execute:
        raw, _ = execute(STAGE, {"evidence_json": json.dumps(meta), "excerpt": EXCERPT})
        staged = json.loads(raw)
        assert (
            staged["status"] == "pending_review"
            and staged["formalKnowledgeCreated"] is False
        )
        raw, _ = execute(
            SEARCH, {"query": "营业收入", "ticker": "600519", "report_period": "2025FY"}
        )
        assert raw.startswith("{"), raw
        assert json.loads(raw)["status"] == "insufficient_evidence"
    source = knowledge.list_owner_source_inbox(
        "agent", env["owner"], agent_id=env["owner"]
    )["sources"][0]
    reviewed = review(
        env,
        {
            "source": source,
            "knowledgeBase": {"scopedKnowledgeBaseId": staged["knowledgeBaseId"]},
        },
    )
    item_id = reviewed["directIngestion"]["item"]["knowledgeItemId"]
    with authorized_agent_tool_executor(
        env["owner"], executable_tools=(SEARCH, WITHDRAW)
    ) as execute:
        raw, _ = execute(
            SEARCH, {"query": "营业收入", "ticker": "600519", "report_period": "2025FY"}
        )
        assert raw.startswith("{"), raw
        result = json.loads(raw)
        assert result["status"] == "found"
        assert result["citations"][0]["financialEvidence"][0]["page"] == 7
        raw, _ = execute(
            WITHDRAW, {"knowledge_item_id": item_id, "reason": "Test source withdrawal"}
        )
        assert raw.startswith("{"), raw
        assert json.loads(raw)["status"] == "withdrawn"
        raw, _ = execute(
            SEARCH, {"query": "营业收入", "ticker": "600519", "report_period": "2025FY"}
        )
        assert raw.startswith("{"), raw
        assert json.loads(raw)["status"] == "insufficient_evidence"


def test_executor_denied_stage_cannot_create_a_library(finance_env):
    env = finance_env
    with authorized_agent_tool_executor(env["owner"], executable_tools=()) as execute:
        raw, _ = execute(
            STAGE, {"evidence_json": json.dumps(evidence()), "excerpt": EXCERPT}
        )
    assert (
        "blocked" in str(raw).lower()
        or "拒绝" in str(raw)
        or "权限" in str(raw)
        or "未授权" in str(raw)
        or "未被本回合授权" in str(raw)
    )
    assert (
        knowledge.get_financial_knowledge_base(agent_id=env["owner"])["knowledgeBase"]
        is None
    )


def test_stage_requires_identity_and_honors_memory_policy_without_creating_base(
    finance_env, monkeypatch
):
    env = finance_env
    monkeypatch.setattr(financial_memory_tools, "_current_runtime", dict)
    assert (
        json.loads(
            financial_memory_tools.financial_evidence_stage_tool(
                json.dumps(evidence()), EXCERPT
            )
        )["status"]
        == "blocked"
    )
    monkeypatch.setattr(
        financial_memory_tools,
        "_current_runtime",
        lambda: {
            "agentId": env["owner"],
            "memoryPolicy": {"proposeKnowledgeBaseIds": ["another-base"]},
        },
    )
    assert (
        json.loads(
            financial_memory_tools.financial_evidence_stage_tool(
                json.dumps(evidence()), EXCERPT
            )
        )["status"]
        == "blocked"
    )
    assert (
        knowledge.get_financial_knowledge_base(agent_id=env["owner"])["knowledgeBase"]
        is None
    )


def test_actual_executor_uses_ragflow_adapter_and_keeps_secret_out_of_result(
    finance_env, monkeypatch
):
    env = finance_env
    monkeypatch.setenv(
        financial_report_tools.PREFIX + "BASE_URL", "https://finance.example.test"
    )
    monkeypatch.setenv(financial_report_tools.PREFIX + "CHAT_ID", "test-finance")
    monkeypatch.setenv(financial_report_tools.PREFIX + "API_KEY", "test-only-secret")
    opener = Mock()
    opener.open.return_value = BytesIO(json.dumps(completion()).encode())
    monkeypatch.setattr(
        financial_report_tools, "build_opener", Mock(return_value=opener)
    )
    with authorized_agent_tool_executor(
        env["owner"], executable_tools=(REPORT,)
    ) as execute:
        raw, _ = execute(
            REPORT,
            {"question": "营业收入", "ticker": "600519", "report_period": "2025FY"},
        )
    assert raw.startswith("{"), raw
    result = json.loads(raw)
    assert result["status"] == "answer" and result["citations"][0]["page"] == 7
    assert "test-only-secret" not in raw
    assert opener.open.call_count == 1


def test_existing_tool_and_knowledge_http_projections_include_finance(
    finance_env, monkeypatch
):
    env = finance_env
    for name in financial_report_tools.REQUIRED_CONFIG:
        monkeypatch.delenv(name, raising=False)
    knowledge.get_financial_knowledge_base(
        agent_id=env["owner"], create_if_missing=True
    )["knowledgeBase"]
    client = TestClient(
        create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()}
    )
    tools_response = client.get("/api/tools")
    assert tools_response.status_code == 200
    registered = {row["name"]: row for row in tools_response.json()["tools"]}
    assert {REPORT, STAGE, SEARCH, WITHDRAW}.issubset(registered)
    assert registered[REPORT]["dependencyStatus"]["status"] == "not_configured"
    assert registered[REPORT]["llmVisible"] is False
    assert all(
        registered[name]["permissionPolicy"]["requiresExplicitAllow"]
        for name in [REPORT, STAGE, SEARCH, WITHDRAW]
    )
    response = client.get(
        f"/api/agents/{env['owner']}/knowledge-bases",
        params={"actorAgentId": env["owner"]},
    )
    assert response.status_code == 200
    assert response.json()["knowledgeBases"][0]["profile"] == "financial_reports_v1"
    other = client.get(
        f"/api/agents/{env['owner']}/knowledge-bases",
        params={"actorAgentId": env["other"]},
    )
    assert other.status_code == 200 and other.json()["knowledgeBases"] == []


def test_memory_tool_schema_never_accepts_target_agent_or_raw_paths():
    for definition in create_key_tools():
        if definition.name in {STAGE, SEARCH, WITHDRAW}:
            properties = definition.args_schema.model_json_schema()["properties"]
            assert "agent_id" not in properties and "owner_id" not in properties
            assert "file_path" not in properties and "url" not in properties


def test_canonical_schema_preserves_numeric_identifiers_and_verbatim_excerpts():
    from core.infrastructure.llm_utils import parse_tool_args
    from core.orchestration.tool_lifecycle import _tool_call_args

    args = {
        "query": "true",
        "ticker": "600519",
        "report_period": "2025FY",
        "limit": "5",
    }
    parsed = parse_tool_args(args, tool_name=SEARCH)
    assert parsed == {**args, "limit": 5}
    assert parse_tool_args({"ticker": "000001"}, tool_name=REPORT)["ticker"] == "000001"
    assert (
        parse_tool_args({"excerpt": " 1.00 "}, tool_name=STAGE)["excerpt"] == " 1.00 "
    )
    assert (
        _tool_call_args({"function": {"name": SEARCH, "arguments": json.dumps(args)}})
        == parsed
    )
    assert parse_tool_args({"limit": "5", "flag": "false"}) == {
        "limit": 5,
        "flag": False,
    }


def test_financial_writes_respect_existing_readonly_subagent_guard(
    finance_env, monkeypatch
):
    from core.infrastructure.tool_executor import ToolExecutor

    monkeypatch.setenv("VIBELUTION_SUBAGENT_MODE", "readonly")
    assert ToolExecutor._check_readonly_subagent_block(STAGE)
    assert ToolExecutor._check_readonly_subagent_block(WITHDRAW)
    assert ToolExecutor._check_readonly_subagent_block(SEARCH) is None
    assert STAGE in ToolExecutor._RUNTIME_GOAL_WRITE_BLOCKED_TOOLS
    assert WITHDRAW in ToolExecutor._RUNTIME_GOAL_WRITE_BLOCKED_TOOLS


def test_financial_evidence_citations_survive_native_model_result_budget(finance_env):
    from core.infrastructure.tool_result import (
        package_tool_result_facts,
        render_tool_result_for_model,
    )
    from tests.test_financial_knowledge_service import stage

    env = finance_env
    for page in range(1, 7):
        staged = stage(env, page=page)
        review(env, staged)
    with authorized_agent_tool_executor(
        env["owner"], executable_tools=(SEARCH,)
    ) as execute:
        raw, _ = execute(
            SEARCH,
            {
                "query": "营业收入",
                "ticker": "600519",
                "report_period": "2025FY",
                "limit": 6,
            },
        )
    result = json.loads(raw)
    assert result["status"] == "found"
    assert result["omittedResultCount"] > 0
    assert len(result["citations"]) == len(result["results"])
    assert all(
        c["financialEvidence"][0]["documentSha256"] == "a" * 64
        for c in result["citations"]
    )
    facts = package_tool_result_facts(raw, tool_name=SEARCH)
    assert facts.truncated is False
    rendered = render_tool_result_for_model(facts)
    assert "模型上下文已限长" not in rendered
    assert "financialEvidence" in rendered and "documentSha256" in rendered


def test_invalid_memory_policy_fails_closed(finance_env, monkeypatch):
    monkeypatch.setattr(
        financial_memory_tools,
        "_current_runtime",
        lambda: {
            "agentId": finance_env["owner"],
            "memoryPolicy": {"proposeKnowledgeBaseIds": True},
        },
    )
    result = json.loads(
        financial_memory_tools.financial_evidence_stage_tool(
            json.dumps(evidence()), EXCERPT
        )
    )
    assert result["status"] == "blocked"
    assert (
        knowledge.get_financial_knowledge_base(agent_id=finance_env["owner"])[
            "knowledgeBase"
        ]
        is None
    )
