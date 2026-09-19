"""Service-level tests for team bundle export / import."""

from __future__ import annotations

import pytest

from core.web.services import (
    agent_directory_service,
    chat_room_service,
    prompt_template_service,
    session_service,
    team_service,
)
from core.web.services import team_bundle_service
from core.web.services.team_bundle_service import (
    BUNDLE_KIND,
    TeamBundleError,
    export_team_bundle,
    import_team_bundle,
)

MODEL_ID = "model-primary"


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    for module in (
        agent_directory_service,
        chat_room_service,
        prompt_template_service,
        session_service,
        team_service,
        team_bundle_service,
    ):
        monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        agent_directory_service,
        "_configured_model_library_ids",
        lambda *args, **kwargs: {MODEL_ID},
    )


def _create_agent(name: str, *, role_key: str = "research") -> dict:
    session = session_service.create_chat_session(
        title=name,
        llm_bindings=session_service.default_session_llm_bindings(),
        created_by="test",
    )
    return agent_directory_service.update_agent_instance(
        str(session["agentId"]),
        display_name=name,
        primary_mode="chat",
        role_key=role_key,
        llm_bindings={"dialogue": {"modelId": MODEL_ID}},
        persona_profile={"background": f"{name} research background", "expertise": [{"area": "research"}]},
        task_profile={"mission": f"{name} research mission"},
    )


def _create_team(name: str, agents: list[dict]) -> dict:
    return team_service.create_team(
        name=name,
        description="bundle test team",
        purpose="verify roundtrip",
        members=[
            {
                "memberId": f"member-{index}",
                "agentId": agent["agentId"],
                "role": agent["displayName"],
                "purpose": "role purpose",
                "responsibilities": ["gather", "report"],
            }
            for index, agent in enumerate(agents, start=1)
        ],
    )


def _seed_two_agent_team(tmp_path, monkeypatch, name: str = "Bundle 测试团队") -> dict:
    _use_tmp_project_root(tmp_path, monkeypatch)
    agents = [_create_agent("资料调研"), _create_agent("假说评审")]
    return _create_team(name, agents)


def test_export_bundle_contract(tmp_path, monkeypatch):
    team = _seed_two_agent_team(tmp_path, monkeypatch)

    bundle = export_team_bundle(str(team["teamId"]))

    assert bundle["kind"] == BUNDLE_KIND
    assert bundle["schemaVersion"] == 1
    assert bundle["team"]["name"] == "Bundle 测试团队"
    assert bundle["team"]["members"][0]["responsibilities"] == ["gather", "report"]
    assert len(bundle["agents"]) == 2
    for agent in bundle["agents"]:
        assert agent["llmBindings"]["dialogue"]["modelId"] == MODEL_ID
        assert agent["personaProfile"]["background"]
        assert agent["taskProfile"]["mission"]
        assert "agentId" not in agent and "configHash" not in agent and "directSessionId" not in agent
    assert MODEL_ID in bundle["dependencies"]["providers"]


def test_reimport_upserts_instead_of_duplicating(tmp_path, monkeypatch):
    team = _seed_two_agent_team(tmp_path, monkeypatch)
    agents_before = {a["agentId"] for a in agent_directory_service.list_agents()}
    bundle = export_team_bundle(str(team["teamId"]))

    preview = import_team_bundle(bundle, dry_run=True)
    assert preview["status"] == "ready"
    assert preview["agents"]["overwrite"] and not preview["agents"]["create"]

    result = import_team_bundle(bundle, dry_run=False)
    assert result["status"] == "completed"
    actions = {item["action"] for item in result["result"]["agents"]}
    assert actions == {"updated"}
    agents_after = {a["agentId"] for a in agent_directory_service.list_agents()}
    assert agents_before == agents_after
    restored = agent_directory_service.get_agent(str(result["result"]["agents"][0]["agentId"]))
    assert restored["llmBindings"]["dialogue"]["modelId"] == MODEL_ID
    assert restored["metadata"]["teamBundleAgentKey"]


def test_import_creates_team_agents_and_members(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    bundle = {
        "kind": BUNDLE_KIND,
        "schemaVersion": 1,
        "team": {
            "name": "导入挑战杯团队",
            "description": "from bundle",
            "purpose": "reproduce",
            "members": [
                {"bundleAgentKey": "search", "role": "搜索", "purpose": "检索", "responsibilities": ["搜索", "筛选"]},
                {"bundleAgentKey": "review", "role": "评估", "purpose": "评审", "responsibilities": ["评审"]},
            ],
            "chatRoom": {"mode": "round_robin", "purpose": "meeting"},
        },
        "agents": [
            {
                "bundleAgentKey": "search",
                "displayName": "搜索",
                "llmBindings": {"dialogue": {"modelId": MODEL_ID}},
                "personaProfile": {"background": "searcher"},
            },
            {
                "bundleAgentKey": "review",
                "displayName": "评估",
                "llmBindings": {"dialogue": {"modelId": MODEL_ID}},
                "personaProfile": {"background": "reviewer"},
            },
        ],
    }

    preview = import_team_bundle(bundle, dry_run=True)
    assert preview["team"]["action"] == "create"
    assert sorted(preview["agents"]["create"]) == ["搜索", "评估"]

    result = import_team_bundle(bundle, dry_run=False)
    assert result["status"] == "completed"
    imported = team_service.get_team(str(result["result"]["teamId"]))
    assert imported["name"] == "导入挑战杯团队"
    assert len(imported["members"]) == 2
    member_roles = sorted(member["role"] for member in imported["members"])
    assert member_roles == ["搜索", "评估"]
    for member in imported["members"]:
        agent = agent_directory_service.get_agent(str(member["agentId"]))
        assert agent["llmBindings"]["dialogue"]["modelId"] == MODEL_ID
        assert agent["metadata"]["teamBundleAgentKey"]
        assert agent["metadata"]["teamBundleSource"] == "team_bundle"


def test_future_schema_major_requires_confirm(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    bundle = {
        "kind": BUNDLE_KIND,
        "schemaVersion": 99,
        "team": {"name": "未来团队", "members": []},
        "agents": [{"displayName": "角色", "llmBindings": {"dialogue": {"modelId": MODEL_ID}}}],
    }

    blocked = import_team_bundle(bundle, dry_run=False)
    assert blocked["status"] == "pending"
    assert blocked["agents"]["create"] == []

    confirmed = import_team_bundle(bundle, dry_run=False, confirm=True)
    assert confirmed["status"] == "completed"


@pytest.mark.parametrize(
    "mutate, code",
    [
        (lambda b: b.update(kind="other-kind"), "unsupported_kind"),
        (lambda b: b.update(agents=[]), "invalid_agents"),
        (lambda b: b.update(team={"name": ""}), "invalid_team"),
        (lambda b: b.update(schemaVersion=None), "invalid_schema_version"),
    ],
)
def test_rejects_invalid_bundles(tmp_path, monkeypatch, mutate, code):
    _use_tmp_project_root(tmp_path, monkeypatch)
    bundle = {
        "kind": BUNDLE_KIND,
        "schemaVersion": 1,
        "team": {"name": "团队", "members": []},
        "agents": [{"displayName": "角色"}],
    }
    mutate(bundle)
    with pytest.raises(TeamBundleError) as error:
        import_team_bundle(bundle, dry_run=True)
    assert error.value.code == code


def test_dependency_report_lists_provider_gaps(tmp_path, monkeypatch):
    team = _seed_two_agent_team(tmp_path, monkeypatch)
    bundle = export_team_bundle(str(team["teamId"]))

    monkeypatch.setattr(team_bundle_service, "_load_local_provider_index", lambda: {})
    preview = import_team_bundle(bundle, dry_run=True)
    assert preview["dependencies"]["missingProviders"] == [MODEL_ID]
    assert any("Missing providers" in warning for warning in preview["warnings"])
