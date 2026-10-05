"""Finance preferences preserve native Agent memory, scope and explicit-write semantics."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.routes.financial_preferences import router
from core.web.services import agent_directory_service as directory
from core.web.services import financial_preferences_service as service
from core.web.services.financial_assistant_service import PROFILE, ROLE
from tests.test_financial_knowledge_service import finance_env as _finance_env

finance_env = _finance_env


def _agent():
    return directory.create_agent_instance(
        display_name="Preference owner",
        primary_mode="general",
        role_key=ROLE,
        prompt_template_id="prompt-chat-default",
        metadata={
            "financialAssistantProfile": PROFILE,
            "financialAssistantSetup": "ready",
        },
    )


def test_reads_are_pure_and_explicit_save_uses_canonical_personal_memory(
    finance_env, monkeypatch
):
    agent = _agent()
    before = directory.list_current_episodic_events(agent["agentId"])
    assert service.list_preferences(agent["agentId"])["items"] == []
    assert directory.list_current_episodic_events(agent["agentId"]) == before
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=3) as pool:
        rows = list(
            pool.map(
                lambda _: service.save_preference(
                    agent["agentId"], "先看现金流，再核对风险。", key
                ),
                range(3),
            )
        )
    assert len({row["id"] for row in rows}) == 1
    canonical = directory.list_current_episodic_events(agent["agentId"])
    assert canonical[0]["episodeId"] == rows[0]["id"]
    assert (
        canonical[0]["kind"] == "preference" and canonical[0]["text"] == rows[0]["text"]
    )
    assert service.list_preferences(agent["agentId"])["items"] == [rows[0]]
    with pytest.raises(service.FinancialPreferenceError, match="另一条"):
        service.save_preference(agent["agentId"], "不同偏好", key)


def test_only_owned_finance_preferences_can_be_removed(finance_env):
    owner, other = _agent(), _agent()
    saved = service.save_preference(owner["agentId"], "关注公告来源", str(uuid4()))
    unrelated = directory.append_episodic_event(
        owner["agentId"], kind="note", text="ordinary private note"
    )
    for target, item_id in [
        (other["agentId"], saved["id"]),
        (owner["agentId"], unrelated["episodeId"]),
    ]:
        with pytest.raises(service.FinancialPreferenceError) as error:
            service.remove_preference(target, item_id)
        assert error.value.status_code == 404
    assert service.remove_preference(owner["agentId"], saved["id"]) == {
        "id": saved["id"],
        "removed": True,
    }
    assert service.list_preferences(owner["agentId"])["items"] == []
    assert (
        directory.list_current_episodic_events(owner["agentId"])[0]["episodeId"]
        == unrelated["episodeId"]
    )


def test_memory_switch_and_public_contract_are_preserved(finance_env):
    agent = _agent()
    app = FastAPI()
    app.include_router(router, prefix="/api")
    client = TestClient(app)
    path = f"/api/financial-preferences/{agent['agentId']}"
    assert set(client.get(path).json()) == {
        "agentId",
        "memoryEnabled",
        "items",
        "limit",
    }
    assert (
        client.post(
            path,
            json={"text": "x", "clientRequestId": str(uuid4()), "agentId": "other"},
        ).status_code
        == 422
    )
    assert (
        client.post(path, json={"text": "x", "clientRequestId": "invalid"}).status_code
        == 422
    )
    ordinary = directory.create_agent_instance(
        display_name="ordinary",
        primary_mode="general",
        role_key="researcher",
        prompt_template_id="prompt-chat-default",
    )
    assert (
        client.get(f"/api/financial-preferences/{ordinary['agentId']}").status_code
        == 404
    )
    directory.update_agent_instance(
        agent["agentId"], memory_policy={**agent["memoryPolicy"], "enabled": False}
    )
    assert client.get(path).json()["memoryEnabled"] is False
    assert (
        client.post(
            path, json={"text": "x", "clientRequestId": str(uuid4())}
        ).status_code
        == 409
    )
