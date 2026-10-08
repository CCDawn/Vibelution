"""Role file layer (workspace shared role library) behavior tests.

Freezes the semantics documented in ``docs/standards/unified-team-format.md``
§5: builtin seeding, version-bump upgrade, user-entry preservation, fail-closed
loading and sourcePath escape rejection.

Isolation follows the repo convention: pin ``VIBELUTION_DATA_HOME`` and the
service ``PROJECT_ROOT`` to a per-test tmp directory so no test can reach the
live operator workspace.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.web.services import team_template_service
from core.web.services.team import role_definition_service, team_format


def _use_tmp_project_root(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(role_definition_service, "PROJECT_ROOT", tmp_path)
    return tmp_path


def _workspace_root(root: Path) -> Path:
    # The routed workspace root: the registry lives at
    # <workspace>/agent_config/role_definitions.json. Derive it from the
    # public path helper instead of hardcoding the data-home layout (the
    # global conftest fixture reroutes resolve_workspace_home per test).
    return role_definition_service.role_registry_path(project_root=root).parent.parent


def _registry_file(root: Path) -> Path:
    return _workspace_root(root) / "agent_config" / "role_definitions.json"


def _registry_payload(root: Path) -> dict:
    path = role_definition_service.role_registry_path(project_root=root)
    assert path.exists()
    return json.loads(path.read_text(encoding="utf-8"))


def _entry_by_key(payload: dict, role_key: str) -> dict:
    return next(entry for entry in payload["roles"] if entry["roleKey"] == role_key)


def _write_user_role(root: Path, role_key: str) -> None:
    roles_root = _workspace_root(root) / "roles"
    roles_root.mkdir(parents=True, exist_ok=True)
    (roles_root / f"{role_key}.md").write_text(
        "---\n"
        f"roleKey: {role_key}\n"
        "role: 数据分析员\n"
        "purpose: 数据分析\n"
        "agentName: 数据分析员 Agent\n"
        "responsibilities:\n"
        "  - 汇总运行数据并输出结论。\n"
        "personaProfile:\n"
        "  personality: 严谨\n"
        "  communicationStyle: 结论先行\n"
        "  background: 数据分析团队成员。\n"
        "  identityNotes: 只做分析，不改数据。\n"
        "  expertise:\n"
        "    - 数据分析\n"
        "taskProfile:\n"
        "  mission: 数据分析\n"
        "  responsibilities: 汇总运行数据并输出结论。\n"
        "  preferredTasks: 数据汇总与趋势分析。\n"
        "  avoidTasks: 不修改原始数据。\n"
        "  successCriteria: 结论附数据依据。\n"
        "  constraints: 只读分析。\n"
        "  deliverables: 分析结论。\n"
        "toolPolicy:\n"
        "  allowedTools: []\n"
        "  preferredTools: []\n"
        "  writeScopes: []\n"
        "---\n\n# 数据分析员\n",
        encoding="utf-8",
    )
    registry_path = _registry_file(root)
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    payload["roles"].append(
        {
            "roleKey": role_key,
            "sourcePath": f"workspace/roles/{role_key}.md",
            "status": "active",
            "metadata": {"builtin": False, "builtinContentVersion": 0, "updatedAt": "2026-10-01T00:00:00+00:00"},
            "createdAt": "2026-10-01T00:00:00+00:00",
            "updatedAt": "2026-10-01T00:00:00+00:00",
        }
    )
    registry_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


# --- builtin golden shape ---------------------------------------------------


def test_builtin_role_files_match_contract_golden_shape():
    keys = role_definition_service.builtin_role_keys()
    assert keys == (
        "dev_team_developer_a",
        "dev_team_developer_b",
        "dev_team_planner",
        "dev_team_reviewer",
        "financial_bear",
        "financial_bull",
        "financial_fundamental",
        "financial_market",
        "financial_news",
    )
    for key in keys:
        role = role_definition_service.builtin_role_definition(key)
        assert set(role) == set(team_format.ROLE_DEFINITION_FIELDS), key
        assert set(role["personaProfile"]) == set(team_format.PERSONA_PROFILE_FIELDS), key
        assert set(role["taskProfile"]) == set(team_format.TASK_PROFILE_FIELDS), key
        assert set(role["toolPolicy"]) == set(team_format.TOOL_POLICY_FIELDS), key
        assert team_format.validate_role_definition(role)["valid"], key


def test_builtin_role_definition_rejects_unknown_key():
    with pytest.raises(role_definition_service.RoleDefinitionError):
        role_definition_service.builtin_role_definition("not_a_builtin_role")


# --- seeding / repair -------------------------------------------------------


def test_repair_seeds_registry_and_role_files_into_workspace(tmp_path, monkeypatch):
    root = _use_tmp_project_root(tmp_path, monkeypatch)

    payload = role_definition_service.repair_role_definitions(project_root=root)

    roles_root = _workspace_root(root) / "roles"
    seeded = sorted(path.name for path in roles_root.glob("*.md"))
    assert seeded == [
        "dev_team_developer_a.md",
        "dev_team_developer_b.md",
        "dev_team_planner.md",
        "dev_team_reviewer.md",
        "financial_bear.md",
        "financial_bull.md",
        "financial_fundamental.md",
        "financial_market.md",
        "financial_news.md",
    ]
    assert len(payload["roles"]) == 9
    for entry in payload["roles"]:
        assert entry["metadata"]["builtin"] is True
        assert entry["metadata"]["builtinContentVersion"] == role_definition_service.BUILTIN_ROLE_CONTENT_VERSION
        assert entry["sourcePath"] == f"workspace/roles/{entry['roleKey']}.md"

    role = role_definition_service.get_role_definition("dev_team_planner", project_root=root)
    assert role == role_definition_service.builtin_role_definition("dev_team_planner")


def test_repair_is_idempotent_and_preserves_user_edits(tmp_path, monkeypatch):
    root = _use_tmp_project_root(tmp_path, monkeypatch)
    role_definition_service.repair_role_definitions(project_root=root)

    planner_file = _workspace_root(root) / "roles" / "dev_team_planner.md"
    user_edit = planner_file.read_text(encoding="utf-8") + "\n<!-- operator edit -->\n"
    planner_file.write_text(user_edit, encoding="utf-8")
    before = _registry_payload(root)

    payload = role_definition_service.repair_role_definitions(project_root=root)

    # No version bump: the operator edit to the builtin file survives and the
    # registry payload is byte-stable apart from nothing at all.
    assert planner_file.read_text(encoding="utf-8") == user_edit
    assert payload["roles"] == before["roles"]
    assert payload["repairWarnings"] == before["repairWarnings"]


def test_builtin_version_bump_overwrites_builtin_but_not_user_roles(tmp_path, monkeypatch):
    root = _use_tmp_project_root(tmp_path, monkeypatch)
    role_definition_service.repair_role_definitions(project_root=root)
    _write_user_role(root, "custom_analyst")

    planner_file = _workspace_root(root) / "roles" / "dev_team_planner.md"
    planner_file.write_text("STALE USER EDIT\n", encoding="utf-8")
    user_file = _workspace_root(root) / "roles" / "custom_analyst.md"
    user_before = user_file.read_text(encoding="utf-8")

    monkeypatch.setattr(role_definition_service, "BUILTIN_ROLE_CONTENT_VERSION", 2)
    payload = role_definition_service.repair_role_definitions(project_root=root)

    # Builtin file is restored to shipped content and its metadata is bumped;
    # the user-created role is untouched.
    assert planner_file.read_text(encoding="utf-8") == role_definition_service.builtin_role_markdown("dev_team_planner")
    planner_entry = _entry_by_key(payload, "dev_team_planner")
    assert planner_entry["metadata"]["builtinContentVersion"] == 2
    assert user_file.read_text(encoding="utf-8") == user_before
    user_entry = _entry_by_key(payload, "custom_analyst")
    assert user_entry["metadata"]["builtin"] is False


def test_list_marks_invalid_roles_without_breaking_the_whole_list(tmp_path, monkeypatch):
    root = _use_tmp_project_root(tmp_path, monkeypatch)
    role_definition_service.repair_role_definitions(project_root=root)

    planner_file = _workspace_root(root) / "roles" / "dev_team_planner.md"
    broken = planner_file.read_text(encoding="utf-8").replace("toolPolicy:", "toolPolicyBroken:")
    planner_file.write_text(broken, encoding="utf-8")

    listed = role_definition_service.list_role_definitions(project_root=root)
    by_key = {item["roleKey"]: item for item in listed["roles"]}
    assert by_key["dev_team_planner"]["valid"] is False
    assert by_key["dev_team_planner"]["issues"]
    assert by_key["dev_team_developer_a"]["valid"] is True

    with pytest.raises(role_definition_service.RoleDefinitionError) as excinfo:
        role_definition_service.get_role_definition("dev_team_planner", project_root=root)
    assert "dev_team_planner.md" in str(excinfo.value)
    with pytest.raises(role_definition_service.RoleDefinitionError):
        role_definition_service.load_role_definitions(role_definition_service.builtin_role_keys(), project_root=root)


# --- fail-closed / safety ---------------------------------------------------


def test_role_file_with_non_slot_model_ref_fails_closed(tmp_path, monkeypatch):
    root = _use_tmp_project_root(tmp_path, monkeypatch)
    role_definition_service.repair_role_definitions(project_root=root)

    planner_file = _workspace_root(root) / "roles" / "dev_team_planner.md"
    poisoned = planner_file.read_text(encoding="utf-8").replace(
        "agentName: 规划师 Agent\n",
        "agentName: 规划师 Agent\nmodelRef: qwen3.5-9b\n",
    )
    planner_file.write_text(poisoned, encoding="utf-8")

    with pytest.raises(role_definition_service.RoleDefinitionError) as excinfo:
        role_definition_service.get_role_definition("dev_team_planner", project_root=root)
    assert "role_model_ref_not_slot" in str(excinfo.value)


def test_role_file_with_model_literal_field_is_rejected_by_loader(tmp_path, monkeypatch):
    root = _use_tmp_project_root(tmp_path, monkeypatch)
    role_definition_service.repair_role_definitions(project_root=root)

    planner_file = _workspace_root(root) / "roles" / "dev_team_planner.md"
    poisoned = planner_file.read_text(encoding="utf-8").replace(
        "agentName: 规划师 Agent\n",
        "agentName: 规划师 Agent\nmodel: qwen3.5-9b\n",
    )
    planner_file.write_text(poisoned, encoding="utf-8")

    # Unknown/unregistered frontmatter keys never silently drop: the loader
    # fails closed before the model-literal validator even runs.
    with pytest.raises(role_definition_service.RoleDefinitionError) as excinfo:
        role_definition_service.get_role_definition("dev_team_planner", project_root=root)
    assert "model" in str(excinfo.value)


def test_registry_source_path_escape_is_dropped(tmp_path, monkeypatch):
    root = _use_tmp_project_root(tmp_path, monkeypatch)
    role_definition_service.repair_role_definitions(project_root=root)

    registry_path = _registry_file(root)
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    payload["roles"].append(
        {
            "roleKey": "evil_escape",
            "sourcePath": "workspace/roles/../../outside.md",
            "metadata": {"builtin": False},
        }
    )
    payload["roles"].append(
        {
            "roleKey": "evil_absolute",
            "sourcePath": "C:/outside/roles/evil.md",
            "metadata": {"builtin": False},
        }
    )
    registry_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    repaired = role_definition_service.repair_role_definitions(project_root=root)

    keys = {entry["roleKey"] for entry in repaired["roles"]}
    assert "evil_escape" not in keys
    assert "evil_absolute" not in keys
    assert any("evil_escape" in warning or "sourcePath" in warning for warning in repaired["repairWarnings"])
    with pytest.raises(role_definition_service.RoleDefinitionError):
        role_definition_service.get_role_definition("evil_escape", project_root=root)


def test_load_role_definitions_preserves_requested_order_and_rejects_duplicates(tmp_path, monkeypatch):
    root = _use_tmp_project_root(tmp_path, monkeypatch)

    keys = list(team_template_service.DEV_TEAM_ROLE_KEYS)
    roles = role_definition_service.load_role_definitions(keys, project_root=root)
    assert [role["roleKey"] for role in roles] == keys

    with pytest.raises(role_definition_service.RoleDefinitionError):
        role_definition_service.load_role_definitions([keys[0], keys[0]], project_root=root)
