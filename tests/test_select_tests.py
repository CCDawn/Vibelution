import json
import re
from pathlib import Path

import pytest

from tests import conftest as test_conftest
from tests import select_tests


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_matrix_loads_with_builtin_subset_parser():
    matrix = select_tests._parse_yaml_subset(select_tests.DEFAULT_MATRIX.read_text(encoding="utf-8"))

    assert matrix["version"] == 1
    assert matrix["always"]["commands"] == [
        "git diff --check",
    ]
    assert any(rule["id"] == "web-session-chat" for rule in matrix["rules"])


def test_matrix_references_existing_test_files_and_directories():
    matrix = select_tests.load_matrix()
    missing_paths: list[str] = []
    missing_command_tests: list[str] = []
    for rule in matrix["rules"]:
        for pattern in rule.get("paths", []):
            normalized = select_tests.normalize_path(str(pattern))
            if "*" in normalized:
                matches = list(PROJECT_ROOT.glob(normalized))
                if not matches and not normalized.startswith(".docs/"):
                    missing_paths.append(f"{rule['id']}:{normalized}")
            elif normalized.startswith("tests/") and not (PROJECT_ROOT / normalized).exists():
                missing_paths.append(f"{rule['id']}:{normalized}")
            elif (
                normalized.startswith("core/")
                or normalized.startswith("web/")
                or normalized.startswith("scripts/")
                or normalized.startswith("config/")
            ) and "*" not in normalized and not (PROJECT_ROOT / normalized).exists():
                # Non-glob source paths must still exist after package splits.
                missing_paths.append(f"{rule['id']}:{normalized}")

        for command in rule.get("commands", []):
            for match in re.finditer(r"tests/[A-Za-z0-9_./-]+\.py", str(command).replace("\\", "/")):
                test_path = match.group(0)
                if not (PROJECT_ROOT / test_path).exists():
                    missing_command_tests.append(f"{rule['id']}:{test_path}")

    assert missing_paths == []
    assert missing_command_tests == []


def test_team_workflow_aggregate_ignored_when_collecting_tests_tree():
    """Full-suite discovery must prefer domain packs over the aggregate re-export."""
    aggregate = PROJECT_ROOT / "tests" / "test_team_workflow_orchestration_service.py"

    class _Config:
        args = ["tests"]

    assert test_conftest.pytest_ignore_collect(collection_path=aggregate, config=_Config()) is True

    class _ExplicitAggregate:
        args = ["tests/test_team_workflow_orchestration_service.py"]

    assert (
        test_conftest.pytest_ignore_collect(
            collection_path=aggregate, config=_ExplicitAggregate()
        )
        is False
    )

    class _WithDomainPack:
        args = [
            "tests/test_team_workflow_orchestration_service.py",
            "tests/test_team_workflow_source_collection_cases.py",
        ]

    assert (
        test_conftest.pytest_ignore_collect(
            collection_path=aggregate, config=_WithDomainPack()
        )
        is True
    )


def test_team_workflow_collection_modifyitems_drops_aggregate_when_domains_present():
    class _Item:
        def __init__(self, nodeid: str):
            self.nodeid = nodeid

    items = [
        _Item("tests/test_team_workflow_orchestration_service.py::test_a"),
        _Item("tests/test_team_workflow_source_collection_cases.py::test_a"),
        _Item("tests/test_team_workflow_structure_cases.py::test_b"),
        _Item("tests/test_other.py::test_c"),
    ]
    test_conftest.drop_team_workflow_aggregate_duplicates(items)
    assert [item.nodeid for item in items] == [
        "tests/test_team_workflow_source_collection_cases.py::test_a",
        "tests/test_team_workflow_structure_cases.py::test_b",
        "tests/test_other.py::test_c",
    ]

    only_aggregate = [_Item("tests/test_team_workflow_orchestration_service.py::test_a")]
    test_conftest.drop_team_workflow_aggregate_duplicates(only_aggregate)
    assert len(only_aggregate) == 1


def test_runtime_manager_isolation_hint_skips_pure_test_files(tmp_path: Path):
    pure_test = tmp_path / "test_pure.py"
    pure_test.write_text("def test_value():\n    assert 1 == 1\n", encoding="utf-8")
    web_test = tmp_path / "test_web.py"
    web_test.write_text("from core.web.app import create_app\n", encoding="utf-8")
    team_test = tmp_path / "test_team.py"
    team_test.write_text("from core.web.services import team_workflow_orchestration_service\n", encoding="utf-8")
    chat_state_test = tmp_path / "test_chat_state.py"
    chat_state_test.write_text("from core.ui.chat_state import load_chat_state\n", encoding="utf-8")

    test_conftest._test_file_needs_runtime_manager_isolation.cache_clear()

    assert test_conftest._test_file_needs_runtime_manager_isolation(str(pure_test)) is False
    assert test_conftest._test_file_needs_runtime_manager_isolation(str(web_test)) is True
    assert test_conftest._test_file_needs_runtime_manager_isolation(str(team_test)) is True
    assert test_conftest._test_file_needs_runtime_manager_isolation(str(chat_state_test)) is True


def test_singleton_reset_hint_skips_pure_test_files(tmp_path: Path):
    pure_test = tmp_path / "test_pure.py"
    pure_test.write_text("def test_value():\n    assert 1 == 1\n", encoding="utf-8")
    singleton_test = tmp_path / "test_singleton.py"
    singleton_test.write_text("from core.infrastructure.state import get_state\n", encoding="utf-8")
    string_only_test = tmp_path / "test_string_only.py"
    string_only_test.write_text(
        'def test_contract():\n    assert "session_service" in "core.web.services.session_service"\n',
        encoding="utf-8",
    )
    team_support_test = tmp_path / "test_team_support.py"
    team_support_test.write_text(
        "from tests._support.team_workflow.cases_structure import *\n",
        encoding="utf-8",
    )

    test_conftest._test_file_needs_singleton_reset.cache_clear()
    test_conftest._test_file_needs_runtime_manager_isolation.cache_clear()

    assert test_conftest._test_file_needs_singleton_reset(str(pure_test)) is False
    assert test_conftest._test_file_needs_singleton_reset(str(singleton_test)) is True
    assert test_conftest._test_file_needs_singleton_reset(str(string_only_test)) is False
    assert test_conftest._test_file_needs_runtime_manager_isolation(str(string_only_test)) is False
    assert test_conftest._test_file_needs_runtime_manager_isolation(str(team_support_test)) is True


def test_parallel_safe_web_helpers_are_not_module_serial():
    project_root = Path(__file__).resolve().parents[1]
    parallel_safe = (
        project_root / "tests" / "test_runtime_manager_control_service.py",
        project_root / "tests" / "test_web_misc_routes.py",
        project_root / "tests" / "test_launcher_scripts_contract.py",
    )
    for path in parallel_safe:
        source = path.read_text(encoding="utf-8")
        assert "pytestmark = pytest.mark.serial" not in source
        assert "pytest.mark.serial" not in source.split("pytestmark", 1)[0]
        assert "pytestmark = pytest.mark.slow" not in source


def test_selector_matches_session_service_to_chat_validation_commands():
    result = select_tests.select_tests(
        ["core\\web\\services\\session_service.py"],
        select_tests.load_matrix(),
    )

    assert result["matchedRules"][0]["id"] == "web-session-chat"
    assert "core/web/services/session_service.py" in result["matchedRules"][0]["matchedFiles"]
    assert "git diff --check" in result["commands"]
    assert any("tests/test_web_session_routes.py" in command for command in result["commands"])
    assert not any("ChatCodingRoute.layout.test.ts" in command for command in result["commands"])


def test_selector_matches_local_quality_gate_surfaces():
    result = select_tests.select_tests(
        [
            ".githooks/pre-commit",
            ".github/workflows/ci.yml",
            "scripts/doctor.ps1",
            "scripts/local_quality_gate.py",
            "tests/test_matrix.yaml",
        ],
        select_tests.load_matrix(),
    )

    rule = next(rule for rule in result["matchedRules"] if rule["id"] == "local-quality-gate")
    assert set(rule["matchedFiles"]) == {
        ".githooks/pre-commit",
        ".github/workflows/ci.yml",
        "scripts/doctor.ps1",
        "scripts/local_quality_gate.py",
        "tests/test_matrix.yaml",
    }
    assert any("tests/test_local_quality_gate.py" in command for command in result["commands"])
    assert any("tests/test_ci_workflow_contract.py" in command for command in result["commands"])
    assert any("tests/test_environment_doctor.py" in command for command in result["commands"])
    assert any("tests/test_select_tests.py" in command for command in result["commands"])
    assert "local-serial" in result["validationLayers"]


def test_selector_matches_chat_style_map_to_chat_validation_commands():
    result = select_tests.select_tests(
        ["web/src/routes/ChatCodingRoute.styles.ts"],
        select_tests.load_matrix(),
    )

    assert result["matchedRules"][0]["id"] == "web-session-chat-ui"
    assert "web/src/routes/ChatCodingRoute.styles.ts" in result["matchedRules"][0]["matchedFiles"]
    assert not any("tests/test_web_session_routes.py" in command for command in result["commands"])
    assert any("ChatCodingRoute.layout.test.ts" in command for command in result["commands"])
    assert any("vuiShadcnRouteContract.test.ts" in command for command in result["commands"])
    assert any("vuiComponentDesignContract.test.ts" in command for command in result["commands"])
    assert any("tsc -b --pretty false" in command for command in result["commands"])
    assert not any(command == "node web/node_modules/vitest/vitest.mjs run" for command in result["commands"])
    assert not any(command == "npm --prefix web run build" for command in result["commands"])


def test_selector_matches_teams_style_map_to_teams_validation_commands():
    result = select_tests.select_tests(
        ["web/src/routes/TeamsRoute.styles.ts"],
        select_tests.load_matrix(),
    )

    assert result["matchedRules"][0]["id"] == "teams-knowledge-ui"
    assert "web/src/routes/TeamsRoute.styles.ts" in result["matchedRules"][0]["matchedFiles"]
    assert not any("tests/test_team_workflow_facade_contract.py" in command for command in result["commands"])
    assert not any("tests/test_team_workflow_source_collection_cases.py" in command for command in result["commands"])
    assert any("TeamsRoute.layout.test.ts" in command for command in result["commands"])
    assert any("src/routes/teams" in command for command in result["commands"])
    assert any("vuiShadcnRouteContract.test.ts" in command for command in result["commands"])
    assert any("tsc -b --pretty false" in command for command in result["commands"])
    assert not any("npm --prefix web run build" in command for command in result["commands"])
    assert not any("挑战杯/" in command for command in result["commands"])
    assert "frontend" in result["validationLayers"]
    assert "local-parallel" not in result["validationLayers"]
    assert "remote-distributed" not in result["validationLayers"]


def test_selector_matches_team_workflows_package_routes():
    result = select_tests.select_tests(
        [
            "core/web/routes/team_workflows/source_collection.py",
            "core/web/services/team_workflow/experiment_api/plan.py",
        ],
        select_tests.load_matrix(),
    )

    assert any(rule["id"] == "teams-knowledge" for rule in result["matchedRules"])
    assert any("tests/test_team_workflow_facade_contract.py" in command for command in result["commands"])
    assert any("tests/test_team_workflow_structure_packs.py" in command for command in result["commands"])


def test_selector_matches_large_file_split_extracted_paths():
    result = select_tests.select_tests(
        [
            "web/src/routes/teams/TeamsSourceCollectionPanel.tsx",
            "web/src/api/types/chat.ts",
            "core/web/services/session/detail_window.py",
            "core/web/services/team_workflow/source_collection_context.py",
        ],
        select_tests.load_matrix(),
    )

    rule_ids = {rule["id"] for rule in result["matchedRules"]}
    assert {"web-session-chat", "teams-knowledge", "teams-knowledge-ui", "frontend-non-ui"}.issubset(rule_ids)
    assert any("tests/test_web_session_routes.py" in command for command in result["commands"])
    assert any("tests/test_team_workflow_source_collection_cases.py" in command for command in result["commands"])
    assert any("ChatCodingRoute" not in command and "--changed main" in command for command in result["commands"])
    assert any("tsc -b --pretty false" in command for command in result["commands"])
    assert not any(command == "node web/node_modules/vitest/vitest.mjs run" for command in result["commands"])
    assert not any(command == "npm --prefix web run build" for command in result["commands"])


def test_selector_uses_non_ui_frontend_fallback_without_vui_contracts():
    result = select_tests.select_tests(
        ["web/src/api/types/chat.ts"],
        select_tests.load_matrix(),
    )

    assert {rule["id"] for rule in result["matchedRules"]} == {"frontend-non-ui"}
    assert any("--changed main --passWithNoTests" in command for command in result["commands"])
    assert any("tsc -b --pretty false" in command for command in result["commands"])
    assert not any("vuiShadcnRouteContract.test.ts" in command for command in result["commands"])
    assert not any("vuiComponentDesignContract.test.ts" in command for command in result["commands"])


def test_selector_matches_real_session_route_files_to_chat_validation_commands():
    result = select_tests.select_tests(
        [
            "core/web/routes/sessions.py",
            "core/web/routes/chat_rooms.py",
        ],
        select_tests.load_matrix(),
    )

    assert result["matchedRules"][0]["id"] == "web-session-chat"
    assert result["matchedRules"][0]["matchedFiles"] == [
        "core/web/routes/sessions.py",
        "core/web/routes/chat_rooms.py",
    ]
    assert any("tests/test_web_session_routes.py" in command for command in result["commands"])
    assert not any("ChatCodingRoute.layout.test.ts" in command for command in result["commands"])


def test_selector_matches_web_config_routes_to_config_validation_commands():
    result = select_tests.select_tests(
        ["tests/test_web_config_routes.py"],
        select_tests.load_matrix(),
    )

    assert result["matchedRules"][0]["id"] == "config-models"
    assert "tests/test_web_config_routes.py" in result["matchedRules"][0]["matchedFiles"]
    assert any("tests/test_web_config_routes.py" in command for command in result["commands"])
    assert not any("tests/test_web_app.py" in command for command in result["commands"])


def test_selector_matches_agent_directory_services_to_focused_commands():
    result = select_tests.select_tests(
        [
            "core/web/services/agent_directory_service.py",
            "core/web/services/model_reference_service.py",
        ],
        select_tests.load_matrix(),
    )

    assert {rule["id"] for rule in result["matchedRules"]} == {"agent-directory-config"}
    assert any("tests/test_agent_config_workspace_service.py" in command for command in result["commands"])
    assert any("tests/test_model_reference_service.py" in command for command in result["commands"])
    assert not any("tests/ --collect-only" in command for command in result["commands"])


def test_selector_matches_memory_cleanup_and_tool_registry_services():
    result = select_tests.select_tests(
        [
            "core/web/services/memory_cleanup_service.py",
            "core/web/services/tool_registry_service.py",
        ],
        select_tests.load_matrix(),
    )

    rule_ids = {rule["id"] for rule in result["matchedRules"]}
    assert rule_ids == {"memory-cleanup", "tool-registry"}
    assert any("tests/test_memory_cleanup_service.py" in command for command in result["commands"])
    assert any("tests/test_tool_registry_service.py" in command for command in result["commands"])
    assert any(
        "tests/prompt_debugger.py" in command
        and "--suite" in command
        and "--quick" in command
        for command in result["commands"]
    )
    assert len(result["commands"]) == len(set(result["commands"]))


def test_selector_matches_web_runtime_routes_to_runtime_validation_commands():
    result = select_tests.select_tests(
        ["tests/test_web_runtime_routes.py"],
        select_tests.load_matrix(),
    )

    assert result["matchedRules"][0]["id"] == "web-runtime-launcher"
    assert "tests/test_web_runtime_routes.py" in result["matchedRules"][0]["matchedFiles"]
    assert any("tests/test_web_runtime_routes.py" in command for command in result["commands"])
    assert not any("tests/test_web_app.py" in command for command in result["commands"])
    assert "local-serial" in result["validationLayers"]
    assert result["executionPlan"]["localSerial"]["required"] is True
    assert result["executionPlan"]["remoteDistributed"]["recommended"] is False


def test_selector_matches_current_evolution_service_layout():
    result = select_tests.select_tests(
        [
            "core/evaluation/supervised_evolution.py",
            "core/web/services/self_evolution_control_service.py",
            "core/web/services/supervised_worktree_evolution_service.py",
        ],
        select_tests.load_matrix(),
    )

    assert {rule["id"] for rule in result["matchedRules"]} == {"web-evolution"}
    assert any("tests/test_web_evolution_routes.py" in command for command in result["commands"])
    assert any("tests/test_evolution_harness.py" in command for command in result["commands"])


def test_selector_matches_desktop_electron_to_vitest_commands():
    result = select_tests.select_tests(
        ["desktop/electron/src/tray/desktopTray.ts"],
        select_tests.load_matrix(),
    )

    assert result["matchedRules"][0]["id"] == "desktop-electron-shell"
    assert "desktop/electron/src/tray/desktopTray.ts" in result["matchedRules"][0]["matchedFiles"]
    assert any("npm --prefix desktop/electron test" in command for command in result["commands"])
    assert "local-serial" in result["validationLayers"]


def test_selector_matches_real_runtime_route_to_runtime_validation_commands():
    result = select_tests.select_tests(
        ["core/web/routes/runtime.py"],
        select_tests.load_matrix(),
    )

    assert result["matchedRules"][0]["id"] == "web-runtime-launcher"
    assert "core/web/routes/runtime.py" in result["matchedRules"][0]["matchedFiles"]
    assert any("tests/test_web_runtime_routes.py" in command for command in result["commands"])
    assert not any("tests/test_web_app.py" in command for command in result["commands"])
    assert "local-serial" in result["validationLayers"]
    assert result["executionPlan"]["localSerial"]["required"] is True
    assert result["executionPlan"]["remoteDistributed"]["recommended"] is False


def test_selector_recommends_remote_distributed_only_for_parallel_safe_python_rules():
    result = select_tests.select_tests(
        ["core/web/services/agent_directory_service.py"],
        select_tests.load_matrix(),
    )

    assert result["matchedRules"][0]["id"] == "agent-directory-config"
    assert "local-parallel" in result["validationLayers"]
    assert "remote-distributed" in result["validationLayers"]
    assert result["executionPlan"]["localParallel"]["recommended"] is True
    assert result["executionPlan"]["remoteDistributed"]["recommended"] is True
    assert result["executionPlan"]["remoteDistributed"]["isCompleteGate"] is False
    assert "scripts/remote_test_runner.py --backend docker --distributed" in (
        result["executionPlan"]["remoteDistributed"]["command"]
    )
    assert result["executionPlan"]["localSerial"]["required"] is False


def test_selector_keeps_frontend_validation_separate_from_remote_distributed():
    result = select_tests.select_tests(
        ["web/src/app/router.tsx"],
        select_tests.load_matrix(),
    )

    assert result["matchedRules"][0]["id"] == "frontend-workbench"
    assert "frontend" in result["validationLayers"]
    assert result["executionPlan"]["frontend"]["required"] is True
    assert result["executionPlan"]["remoteDistributed"]["recommended"] is False
    assert any("--changed main --passWithNoTests" in command for command in result["commands"])
    assert any("tsc -b --pretty false" in command for command in result["commands"])
    assert not any(command == "node web/node_modules/vitest/vitest.mjs run" for command in result["commands"])
    assert not any(command == "npm --prefix web run build" for command in result["commands"])


def test_selector_suppresses_frontend_fallback_when_chat_rule_covers_file():
    result = select_tests.select_tests(
        ["web/src/routes/ChatCodingRoute.styles.ts"],
        select_tests.load_matrix(),
    )

    assert {rule["id"] for rule in result["matchedRules"]} == {"web-session-chat-ui"}
    assert not any("--changed main" in command for command in result["commands"])
    assert not any(command == "node web/node_modules/vitest/vitest.mjs run" for command in result["commands"])


def test_selector_keeps_frontend_fallback_for_uncovered_mixed_file():
    result = select_tests.select_tests(
        [
            "web/src/routes/ChatCodingRoute.styles.ts",
            "web/src/app/router.tsx",
        ],
        select_tests.load_matrix(),
    )

    fallback = next(rule for rule in result["matchedRules"] if rule["id"] == "frontend-workbench")
    assert fallback["matchedFiles"] == ["web/src/app/router.tsx"]
    assert any("--changed main --passWithNoTests" in command for command in result["commands"])


def test_selector_scopes_authorization_contract_to_authorization_changes():
    docs = select_tests.select_tests(["docs/ops/config/README.md"], select_tests.load_matrix())
    assert not any("test_tool_authorization_test_contract.py" in command for command in docs["commands"])

    ordinary_test = select_tests.select_tests(["tests/test_runner.py"], select_tests.load_matrix())
    assert any("test-tool-authorization" == rule["id"] for rule in ordinary_test["matchedRules"])
    assert any("test_tool_authorization_test_contract.py" in command for command in ordinary_test["commands"])

    auth = select_tests.select_tests(
        ["tests/test_tool_authorization_contract.py"], select_tests.load_matrix()
    )
    assert any(rule["id"] == "test-tool-authorization" for rule in auth["matchedRules"])
    assert any("test_tool_authorization_test_contract.py" in command for command in auth["commands"])


def test_selector_routes_pure_docs_to_docs_only_without_test_tooling():
    result = select_tests.select_tests(["tests/README.md"], select_tests.load_matrix())

    assert {rule["id"] for rule in result["matchedRules"]} == {"docs-only"}
    assert result["commands"] == ["git diff --check"]


def test_selector_uses_default_when_no_rule_matches():
    result = select_tests.select_tests(["workspace/runtime-cache/example.json"], select_tests.load_matrix())

    assert result["matchedRules"] == []
    assert result["commands"] == [
        "git diff --check",
        ".\\.venv\\Scripts\\python.exe -m pytest tests/test_runner.py -q",
    ]
    assert result["validationLayers"] == ["hygiene", "focused"]


def test_selector_deduplicates_commands_across_rules():
    result = select_tests.select_tests(
        [
            "tests/select_tests.py",
            "tests/README.md",
        ],
        select_tests.load_matrix(),
    )

    assert result["commands"].count("git diff --check") == 1
    assert len(result["commands"]) == len(set(result["commands"]))


def test_path_matches_directory_glob_and_root_markdown():
    assert select_tests.path_matches("web/src/routes/**", "web\\src\\routes\\TeamsRoute.tsx")
    assert select_tests.path_matches("*.md", "README.md")
    assert not select_tests.path_matches("*.md", "docs/README.md")


def test_changed_files_from_file(tmp_path: Path):
    changed = tmp_path / "changed.txt"
    changed.write_text("tests/select_tests.py\n\nweb/src/routes/TeamsRoute.tsx\n", encoding="utf-8")

    assert select_tests.changed_files_from_file(changed) == [
        "tests/select_tests.py",
        "web/src/routes/TeamsRoute.tsx",
    ]


def test_changed_files_from_git_includes_untracked_by_default(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, ...]] = []

    class FakeResult:
        def __init__(self, stdout: str):
            self.stdout = stdout

    def fake_run(command: list[str], **_kwargs):
        calls.append(tuple(command))
        if command[1:4] == ["diff", "--name-only", "main"]:
            return FakeResult("tests/README.md\n")
        if command[1:] == ["ls-files", "--others", "--exclude-standard"]:
            return FakeResult("tests/select_tests.py\ntests/README.md\n")
        raise AssertionError(f"unexpected git command: {command}")

    monkeypatch.setattr(select_tests.subprocess, "run", fake_run)

    assert select_tests.changed_files_from_git("main") == [
        "tests/README.md",
        "tests/select_tests.py",
    ]
    assert calls == [
        ("git", "diff", "--name-only", "main"),
        ("git", "ls-files", "--others", "--exclude-standard"),
    ]


def test_cli_json_output(capsys: pytest.CaptureFixture[str]):
    exit_code = select_tests.main(
        [
            "--changed-file",
            "tests/select_tests.py",
            "--json",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["matchedRules"][0]["id"] == "test-tooling"
    assert "git diff --check" in payload["commands"]
    assert "local-parallel" in payload["validationLayers"]
    assert payload["executionPlan"]["remoteDistributed"]["isCompleteGate"] is False
