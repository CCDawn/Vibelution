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


def test_foreign_session_binding_never_opens(entry_env, monkeypatch):
    service.create_financial_assistant()
    monkeypatch.setattr(
        session_service,
        "get_session_detail",
        lambda *a, **kw: {"agentId": entry_env["other"]},
    )
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
