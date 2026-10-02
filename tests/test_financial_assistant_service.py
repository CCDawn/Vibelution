"""Financial entry reuses native identity, policies, session, and evidence store."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import agent_directory_service as directory
from core.web.services import financial_assistant_service as service
from core.web.services import session_service
from core.web.services import team_knowledge_service as knowledge
from tests.helpers.tool_authorization import authorized_agent_tool_executor
from tests.test_financial_knowledge_service import finance_env as _finance_env

finance_env = _finance_env


@pytest.fixture
def entry_env(finance_env, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", finance_env["root"])
    # This phase must never perform provider I/O while creating/listing an identity.
    monkeypatch.setattr(
        service, "financial_report_availability", lambda: {"status": "not_configured"}
    )
    return finance_env


def test_explicit_setup_uses_native_identity_session_and_private_read_policy(entry_env):
    assert service.list_financial_assistants() == []
    result = service.create_financial_assistant()
    row = result["assistant"]
    assert result["created"] is True
    assert row["setupStatus"] == "ready" and row["directSessionId"]
    agent = directory.get_agent(row["agentId"])
    assert agent["primaryMode"] == "general"
    assert agent["roleKey"] == service.ROLE
    assert agent["personaProfile"]["identityNotes"] == service.PERSONA["identityNotes"]
    assert agent["taskProfile"]["constraints"] == service.TASK["constraints"]
    assert set(agent["toolPolicy"]["allowedTools"]) == set(service.READ_TOOLS)
    assert "news_search_tool" in agent["toolPolicy"]["allowedTools"]
    assert "financial_evidence_stage_tool" not in agent["toolPolicy"]["allowedTools"]
    assert "自行判断真伪" in agent["taskProfile"]["constraints"]
    assert agent["toolPolicyId"] == "tool-" + row["agentId"]
    assert agent["memoryPolicy"]["readKnowledgeBaseIds"] == [row["knowledgeBaseId"]]
    for field in (
        "proposeKnowledgeBaseIds",
        "reviewKnowledgeBaseIds",
        "readSharedGroups",
        "writeSharedGroups",
    ):
        assert agent["memoryPolicy"][field] == []
    assert agent["metadata"]["delegationPolicy"]["allowSubagents"] is False
    assert row["newsDelegationStatus"] == "disabled"
    assert row["privateLedgerStatus"] == "not_implemented"
    assert row["marketDataStatus"] == "not_connected" and not row["tradingEnabled"]
    assert not (agent.get("metadata") or {}).get("virtualHumanCompanion")
    detail = session_service.get_session_detail(row["directSessionId"], message_limit=0)
    assert detail["agentId"] == row["agentId"]
    assert (
        knowledge.get_financial_knowledge_base(agent_id=row["agentId"])[
            "knowledgeBase"
        ]["profile"]
        == "financial_reports_v1"
    )


def test_setup_is_idempotent_and_preserves_user_edits(entry_env):
    first = service.create_financial_assistant()["assistant"]
    directory.update_agent_instance(
        first["agentId"], display_name="我的研究助手", tool_policy={"allowedTools": []}
    )
    second = service.create_financial_assistant("新名字不会覆盖")
    assert second["created"] is False
    assert second["assistant"]["displayName"] == "我的研究助手"
    assert second["assistant"]["directSessionId"] == first["directSessionId"]
    assert directory.get_agent(first["agentId"])["toolPolicy"]["allowedTools"] == []
    assert len(service.list_financial_assistants()) == 1


def test_concurrent_setup_creates_one_agent(entry_env):
    with ThreadPoolExecutor(max_workers=3) as pool:
        rows = list(pool.map(lambda _: service.create_financial_assistant(), range(3)))
    assert sum(r["created"] for r in rows) == 1
    assert len({r["assistant"]["agentId"] for r in rows}) == 1


def test_partial_setup_retries_without_duplicate_agent(entry_env, monkeypatch):
    original = session_service.ensure_agent_direct_session
    monkeypatch.setattr(
        session_service,
        "ensure_agent_direct_session",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("injected failure")),
    )
    with pytest.raises(RuntimeError, match="injected"):
        service.create_financial_assistant()
    rows = service.list_financial_assistants()
    assert (
        len(rows) == 1
        and rows[0]["setupStatus"] == "pending"
        and not rows[0]["directSessionId"]
    )
    monkeypatch.setattr(session_service, "ensure_agent_direct_session", original)
    resumed = service.create_financial_assistant()
    assert (
        not resumed["created"] and resumed["assistant"]["agentId"] == rows[0]["agentId"]
    )
    assert resumed["assistant"]["directSessionId"]


def test_archived_identity_is_not_restored_or_recreated(entry_env):
    row = service.create_financial_assistant()["assistant"]
    directory.update_agent_instance(row["agentId"], status="archived")
    assert service.list_financial_assistants()[0]["directSessionId"] == ""
    with pytest.raises(directory.AgentStateConflictError, match="归档"):
        service.create_financial_assistant()
    assert len(service.list_financial_assistants()) == 1


def test_foreign_session_binding_never_opens(entry_env):
    row = service.create_financial_assistant()["assistant"]
    foreign = session_service.create_chat_session(
        title="外部会话", lightweight=True
    )
    # create_chat_session 会把新会话绑到某个活动 Agent 的 directSessionId；
    # 借这个真实存在、归属他人的运行时行，把助手的绑定污染成它（直接改
    # state 绕过 update API 的占用保护——这里模拟的正是被污染的绑定）。
    state = directory.load_state()
    holder = next(
        str(a.get("agentId") or "")
        for a in state["agents"]
        if str(a.get("directSessionId") or "").strip() == foreign["id"]
    )
    assert holder and holder != row["agentId"]
    for agent in state["agents"]:
        if str(agent.get("agentId") or "") == row["agentId"]:
            agent["directSessionId"] = foreign["id"]
    directory.save_state(state)
    assert service.list_financial_assistants()[0]["directSessionId"] == ""


def test_original_agents_policies_and_other_financial_bases_unchanged(entry_env):
    before = directory.get_agent(entry_env["owner"])
    service.create_financial_assistant()
    after = directory.get_agent(entry_env["owner"])
    assert after["toolPolicy"] == before["toolPolicy"]
    assert after["memoryPolicy"] == before["memoryPolicy"]
    assert (
        knowledge.get_financial_knowledge_base(agent_id=entry_env["owner"])[
            "knowledgeBase"
        ]
        is None
    )


def test_native_executor_reads_new_own_library_and_denies_stage(entry_env):
    row = service.create_financial_assistant()["assistant"]
    with authorized_agent_tool_executor(
        row["agentId"],
        session_id=row["directSessionId"],
        executable_tools=service.READ_TOOLS,
    ) as execute:
        raw, _ = execute(
            "financial_evidence_search_tool",
            {"query": "营业收入", "ticker": "000001", "report_period": "2025FY"},
        )
        assert json.loads(raw)["status"] == "insufficient_evidence"
        raw, _ = execute(
            "financial_evidence_stage_tool",
            {"evidence_json": "{}", "excerpt": "unreviewed"},
        )
        assert any(word in str(raw) for word in ("blocked", "拒绝", "权限", "授权"))


def test_http_contract_rejects_unknown_fields_and_requires_control_token(entry_env):
    app = create_app()
    headers = {CONTROL_TOKEN_HEADER: get_control_token()}
    client = TestClient(app, headers=headers)
    assert client.get("/api/financial-assistants").json() == []
    assert TestClient(app).post("/api/financial-assistants", json={}).status_code in {
        401,
        403,
    }
    headers = {CONTROL_TOKEN_HEADER: get_control_token()}
    assert (
        client.post(
            "/api/financial-assistants", headers=headers, json={"tradingEnabled": True}
        ).status_code
        == 422
    )
    created = client.post("/api/financial-assistants", headers=headers, json={})
    assert created.status_code == 200, created.text
    assert created.json()["assistant"]["directSessionId"]
    again = client.post("/api/financial-assistants", headers=headers, json={})
    assert again.status_code == 200 and not again.json()["created"]
    listed = client.get("/api/financial-assistants").json()
    assert len(listed) == 1 and listed[0]["newsDelegationStatus"] == "disabled"


@pytest.mark.parametrize("name", ["", "  ", "a\nb", "a" * 81])
def test_invalid_names_create_nothing(entry_env, name):
    with pytest.raises(directory.AgentDirectoryError):
        service.create_financial_assistant(name)
    assert service.list_financial_assistants() == []


def test_persona_and_boundaries_reach_native_runtime_context(entry_env):
    row = service.create_financial_assistant()["assistant"]
    context = directory.build_agent_runtime_context_block(row["agentId"])
    assert service.TASK["constraints"] in context
    assert service.PERSONA["identityNotes"] in context
    assert row["knowledgeBaseId"] in context


def test_creation_does_not_reset_shared_default_tool_policy(entry_env):
    state = directory.load_state()
    state["toolPolicies"][directory.DEFAULT_TOOL_POLICY_ID] = {
        **directory.default_tool_policy(),
        "allowedTools": ["glob_tool"],
    }
    directory.save_state(state)
    before = directory.load_state()["toolPolicies"][directory.DEFAULT_TOOL_POLICY_ID]
    service.create_financial_assistant()
    after = directory.load_state()["toolPolicies"][directory.DEFAULT_TOOL_POLICY_ID]
    assert after == before


def test_initial_policy_is_already_restricted_before_library_or_session_setup(
    entry_env, monkeypatch
):
    original = knowledge.get_financial_knowledge_base
    seen = []

    def inspect_policy(*, agent_id, create_if_missing=False):
        if create_if_missing:
            policy = directory.resolve_tool_policy_for_agent(agent_id)
            seen.append(policy)
            assert set(policy["allowedTools"]) == set(service.READ_TOOLS)
            assert "agent_message_tool" not in policy["allowedTools"]
            assert "cli_tool" not in policy["allowedTools"]
        return original(agent_id=agent_id, create_if_missing=create_if_missing)

    monkeypatch.setattr(knowledge, "get_financial_knowledge_base", inspect_policy)
    service.create_financial_assistant()
    assert len(seen) == 1


def test_ready_entry_does_not_recreate_a_deleted_library(entry_env):
    from core.web.services import memory_cleanup_service

    row = service.create_financial_assistant()["assistant"]
    target = {
        "targetType": "knowledge_base",
        "scopedKnowledgeBaseId": row["knowledgeBaseId"],
    }
    preview = memory_cleanup_service.preview_memory_cleanup([target])
    memory_cleanup_service.execute_memory_cleanup(
        [target],
        confirmation_phrase=memory_cleanup_service.CONFIRMATION_PHRASE,
        preview_token=preview["previewToken"],
    )
    refreshed = service.create_financial_assistant()["assistant"]
    assert not refreshed["knowledgeBaseId"] and not refreshed["knowledgeReadable"]


_STAGE_ONE_TASK = {
    "responsibilities": "使用财报工具时明确公司证券代码和报告期，保留来源、页码与版本；证据不足则明确说明。",
    "preferredTasks": "财报检索、来源对照、风险因素梳理和投资需求澄清。",
    "avoidTasks": "不得交易、下单、代管账户、承诺收益；不把新闻或模型摘要当公告或财报原文。",
    "constraints": "行情和新闻委派尚未接入，不声称获得实时分钟行情。个人现金流、持仓、目标、投入意愿和风险承受能力未知时不得猜测；不得把这些私密信息发送给搜索工具或公共知识库。",
    "handoffNotes": "财报专库只收经审核的原始 PDF 证据；待审来源和历史生成答案不能作为财报事实。新闻跨团队委派默认关闭，须独立授权。",
}


def _rewind_stage_one(agent_id: str, *, max_calls: int = 8) -> None:
    agent = directory.get_agent(agent_id)
    directory.update_agent_instance(
        agent_id,
        tool_policy={
            "allowedTools": [
                "financial_report_query_tool",
                "financial_evidence_search_tool",
            ],
            "preferredTools": [
                "financial_report_query_tool",
                "financial_evidence_search_tool",
            ],
            "networkAccess": "controlled",
            "mutationAccess": "none",
            "maxCallsPerTurn": max_calls,
        },
        task_profile={**agent["taskProfile"], **_STAGE_ONE_TASK},
        persona_profile={
            **agent["personaProfile"],
            "expertise": ["A股财报证据", "个人投资目标澄清", "风险分析"],
        },
        # 模拟前 marker 时代的 stage-1 存量助手：清掉「迁移已完成」标记，
        # 让写路径迁移重新可用（metadata 合并语义只能覆盖，不能删除）。
        metadata={"financialAssistantNewsReferenceGranted": False},
    )


def test_listing_is_pure_read_and_reads_the_directory_once(entry_env, monkeypatch):
    """GET 变纯读：一次目录读取、零 registry 写，迁移只在写路径发生。"""
    row = service.create_financial_assistant()["assistant"]
    _rewind_stage_one(row["agentId"])

    list_calls: list[int] = []
    real_list_agents = directory.list_agents

    def counting_list_agents(*args, **kwargs):
        list_calls.append(1)
        return real_list_agents(*args, **kwargs)

    monkeypatch.setattr(directory, "list_agents", counting_list_agents)
    writes: list = []
    monkeypatch.setattr(
        directory, "update_agent_instance", lambda *a, **kw: writes.append(kw)
    )

    listed = service.list_financial_assistants()

    assert len(listed) == 1
    assert len(list_calls) == 1
    assert writes == []


def test_stage_one_migration_happens_on_write_path_not_listing(entry_env):
    row = service.create_financial_assistant()["assistant"]
    _rewind_stage_one(row["agentId"], max_calls=3)
    before = directory.get_agent(row["agentId"])["toolPolicy"]["policyVersion"]

    # GET 纯读：stage-1 存量不再在 listing 里迁移。
    listed = service.list_financial_assistants()
    unchanged = directory.get_agent(row["agentId"])
    assert listed[0]["newsDelegationStatus"] == "disabled"
    assert set(unchanged["toolPolicy"]["allowedTools"]) == set(
        service._PREVIOUS_READ_TOOLS
    )
    assert unchanged["toolPolicy"]["policyVersion"] == before

    # create（写路径）完成迁移，语义与旧 list 迁移一致。
    again = service.create_financial_assistant("新名字不会覆盖")
    assert again["created"] is False
    agent = directory.get_agent(row["agentId"])
    assert agent["metadata"]["delegationPolicy"]["allowSubagents"] is False
    assert set(agent["toolPolicy"]["allowedTools"]) == set(service.READ_TOOLS)
    assert set(agent["toolPolicy"]["preferredTools"]) == set(service.READ_TOOLS)
    assert agent["toolPolicy"]["maxCallsPerTurn"] == 3
    assert agent["toolPolicy"]["policyVersion"] == before + 1
    assert agent["taskProfile"]["constraints"] == service.TASK["constraints"]
    assert agent["taskProfile"]["avoidTasks"] == service.TASK["avoidTasks"]
    assert "公开新闻真伪判断" in agent["personaProfile"]["expertise"]

    # 持久标记已落：后续写路径与读取都不再改写（只跑一次）。
    service.create_financial_assistant("名字不影响迁移")
    service.list_financial_assistants()
    assert directory.get_agent(row["agentId"])["toolPolicy"]["policyVersion"] == before + 1


def test_create_upgrades_untouched_ready_assistant_without_renaming(entry_env):
    row = service.create_financial_assistant()["assistant"]
    _rewind_stage_one(row["agentId"])
    again = service.create_financial_assistant("新名字不会覆盖")
    agent = directory.get_agent(row["agentId"])
    assert again["created"] is False
    assert again["assistant"]["displayName"] == row["displayName"]
    assert "news_search_tool" in agent["toolPolicy"]["allowedTools"]
    assert agent["taskProfile"]["handoffNotes"] == service.TASK["handoffNotes"]


def test_cleared_or_custom_policies_do_not_gain_news_search(entry_env):
    cleared = service.create_financial_assistant()["assistant"]
    cleared_agent = directory.get_agent(cleared["agentId"])
    directory.update_agent_instance(
        cleared["agentId"],
        tool_policy={"allowedTools": []},
        task_profile={**cleared_agent["taskProfile"], "constraints": "用户改过的约束"},
    )
    service.list_financial_assistants()
    kept = directory.get_agent(cleared["agentId"])
    assert kept["toolPolicy"]["allowedTools"] == []
    assert kept["taskProfile"]["constraints"] == "用户改过的约束"

    custom = service.create_financial_assistant()["assistant"]
    # The cleared assistant above is the only project assistant; reuse it.
    assert custom["agentId"] == cleared["agentId"]
    directory.update_agent_instance(
        custom["agentId"],
        tool_policy={
            "allowedTools": ["financial_report_query_tool"],
            "preferredTools": ["financial_report_query_tool"],
            "networkAccess": "controlled",
            "mutationAccess": "none",
            "maxCallsPerTurn": 8,
        },
        task_profile={
            **directory.get_agent(custom["agentId"])["taskProfile"],
            "constraints": _STAGE_ONE_TASK["constraints"],
        },
    )
    service.list_financial_assistants()
    refreshed = directory.get_agent(custom["agentId"])
    # GET 是纯读：即使内容长得像 stage-1，只要迁移标记已落，
    # listing 也不改写用户留下的策略与文本（迁移只发生在写路径）。
    assert refreshed["toolPolicy"]["allowedTools"] == ["financial_report_query_tool"]
    assert (
        refreshed["taskProfile"]["constraints"] == _STAGE_ONE_TASK["constraints"]
    )
