import json
import re
from pathlib import Path

import pytest

from tests import conftest as test_conftest
from tests import select_tests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_TYPECHECK_COMMAND = (
    "node web/node_modules/typescript/bin/tsc -b web/tsconfig.json --pretty false"
)


def test_complete_regression_commands_override_project_fail_fast() -> None:
    assert "--maxfail=0" in select_tests.LOCAL_PARALLEL_COMMAND
    assert "--maxfail=0" in select_tests.LOCAL_SERIAL_COMMAND


def test_selector_pytest_commands_override_project_fail_fast() -> None:
    result = select_tests.select_tests(
        ["core/example.py"],
        {
            "rules": [
                {
                    "id": "example",
                    "paths": ["core/example.py"],
                    "commands": [
                        ".\\.venv\\Scripts\\python.exe -m pytest tests/test_example.py -q"
                    ],
                }
            ]
        },
        include_always=False,
    )

    pytest_commands = [
        command for command in result["commands"] if " -m pytest " in command
    ]
    assert pytest_commands
    assert all("--maxfail=0" in command for command in pytest_commands)


def test_pytest_regression_documentation_overrides_project_fail_fast() -> None:
    documentation = (PROJECT_ROOT / "tests" / "README.md").read_text(encoding="utf-8")
    root_documentation = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    package_documentation = (PROJECT_ROOT / "tests" / "__init__.py").read_text(
        encoding="utf-8"
    )

    assert "全量回归命令必须显式追加 `--maxfail=0`" in documentation
    assert "-m pytest tests/ -v -x" not in documentation
    assert "pytest tests -q --maxfail=0" in root_documentation
    assert "pytest tests/ -v --maxfail=0" in package_documentation
    assert "pytest tests/ -v --tb=short --maxfail=0" in package_documentation


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


def test_selector_matches_virtual_human_plugin_to_focused_validation_commands():
    result = select_tests.select_tests(
        [
            "core/agent_plugins/virtual_human_life/service.py",
            "core/web/routes/virtual_human_life.py",
            "tools/virtual_human_life_tools.py",
        ],
        select_tests.load_matrix(),
    )

    plugin_rule = next(
        rule for rule in result["matchedRules"] if rule["id"] == "virtual-human-life-plugin"
    )
    assert plugin_rule["matchedFiles"] == [
        "core/agent_plugins/virtual_human_life/service.py",
        "core/web/routes/virtual_human_life.py",
        "tools/virtual_human_life_tools.py",
    ]
    assert any("tests/test_virtual_human_life_plugin.py" in command for command in result["commands"])
    assert result["coverageGaps"] == []


def test_selector_matches_local_quality_gate_surfaces():
    result = select_tests.select_tests(
        [
            ".github/workflows/ci.yml",
            "scripts/doctor.ps1",
            "scripts/local_quality_gate.py",
            "tests/test_matrix.yaml",
        ],
        select_tests.load_matrix(),
    )

    gate_rule = next(
        rule for rule in result["matchedRules"] if rule["id"] == "local-quality-gate"
    )
    doctor_rule = next(
        rule for rule in result["matchedRules"] if rule["id"] == "environment-doctor"
    )
    assert set(gate_rule["matchedFiles"]) == {
        ".github/workflows/ci.yml",
        "scripts/local_quality_gate.py",
        "tests/test_matrix.yaml",
    }
    assert doctor_rule["matchedFiles"] == ["scripts/doctor.ps1"]
    assert any("tests/test_local_quality_gate.py" in command for command in result["commands"])
    assert any("tests/test_ci_workflow_contract.py" in command for command in result["commands"])
    assert any("tests/test_environment_doctor.py" in command for command in result["commands"])
    assert any("tests/test_select_tests.py" in command for command in result["commands"])
    assert "local-serial" in result["validationLayers"]


def test_selector_skips_environment_doctor_for_core_gate_only():
    result = select_tests.select_tests(
        ["scripts/task_closeout.py"],
        select_tests.load_matrix(),
    )

    assert [rule["id"] for rule in result["matchedRules"]] == ["local-quality-gate"]
    assert not any(
        "tests/test_environment_doctor.py" in command
        for command in result["commands"]
    )
    assert "local-parallel" in result["validationLayers"]
    assert "local-serial" not in result["validationLayers"]


def test_selector_scopes_pre_commit_hook_to_hook_contract_tests():
    result = select_tests.select_tests(
        [".githooks/pre-commit"],
        select_tests.load_matrix(),
    )

    assert result["matchedRules"] == [
        {
            "id": "pre-commit-hook",
            "description": "Local claim/ref hook adapters and their shared-worktree Python fallback.",
            "matchedFiles": [".githooks/pre-commit"],
        }
    ]
    assert result["commands"] == [
        "git diff --check",
        ".\\.venv\\Scripts\\python.exe -m pytest "
        "tests/test_git_claim_guard.py tests/test_local_quality_gate.py "
        "-k \"claim_guard or pre_commit or reference_transaction or main_permit or real_hook\" "
        "-q --maxfail=0",
    ]
    assert result["validationLayers"] == ["hygiene", "focused", "local-serial"]


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
    assert any("vuiImportBoundary.test.ts" in command for command in result["commands"])
    assert any("vuiSurfaceAlphaPolicy.test.ts" in command for command in result["commands"])
    assert FRONTEND_TYPECHECK_COMMAND in result["commands"]
    assert all(
        command.endswith(select_tests.FRONTEND_TEST_ROOT_ARGUMENT)
        for command in result["commands"]
        if command.startswith(select_tests.FRONTEND_TEST_COMMAND)
    )
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
    assert any("vuiImportBoundary.test.ts" in command for command in result["commands"])
    assert any("vuiSurfaceAlphaPolicy.test.ts" in command for command in result["commands"])
    assert FRONTEND_TYPECHECK_COMMAND in result["commands"]
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
    assert FRONTEND_TYPECHECK_COMMAND in result["commands"]
    assert not any(command == "node web/node_modules/vitest/vitest.mjs run" for command in result["commands"])
    assert not any(command == "npm --prefix web run build" for command in result["commands"])


def test_selector_uses_non_ui_frontend_fallback_without_vui_contracts():
    result = select_tests.select_tests(
        ["web/src/api/types/chat.ts"],
        select_tests.load_matrix(),
    )

    assert {rule["id"] for rule in result["matchedRules"]} == {"frontend-non-ui"}
    assert any("--changed main --passWithNoTests" in command for command in result["commands"])
    assert FRONTEND_TYPECHECK_COMMAND in result["commands"]
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


def test_selector_executes_pure_local_parallel_pytest_rules_with_xdist():
    result = select_tests.select_tests(
        ["core/web/services/agent_directory_service.py"],
        select_tests.load_matrix(),
    )

    pytest_commands = [
        command for command in result["commands"] if " -m pytest " in command
    ]
    assert len(pytest_commands) == 1
    assert "-n 4 --dist loadfile" in pytest_commands[0]
    assert '-m "not serial"' in pytest_commands[0]


def test_selector_keeps_mixed_serial_parallel_rules_serial():
    """The serial rule's own batches stay serial; sibling not-serial batches scale."""
    result = select_tests.select_tests(
        ["config/model_catalog.py"],
        select_tests.load_matrix(),
    )

    pytest_commands = [
        command for command in result["commands"] if " -m pytest " in command
    ]
    assert len(pytest_commands) == 3
    assert all(
        " -n " not in command
        for command in pytest_commands
        if "tests/test_config_panel.py" in command
        or "tests/test_llm_protocol_cache_alignment.py" in command
    )
    # The llm-provider-config-v2 focus rule carries no local-serial layer, so its
    # eight-file batch gets bounded xdist like every other multi-file batch.
    assert any(
        "-q -n 6 --dist loadfile" in command and '-m "not serial"' in command
        for command in pytest_commands
    )


def test_selector_never_touches_serial_layer_batches_even_with_many_files():
    result = select_tests.select_tests(
        ["core/web/routes/runtime.py"],
        select_tests.load_matrix(),
    )

    pytest_commands = [
        command for command in result["commands"] if " -m pytest " in command
    ]
    four_file_command = next(
        command for command in pytest_commands if "tests/test_launcher_service.py" in command
    )
    assert " -n " not in four_file_command


def test_selector_does_not_duplicate_existing_xdist_arguments():
    result = select_tests.select_tests(
        ["core/web/services/team_workflow/command_service.py"],
        select_tests.load_matrix(),
    )

    pytest_commands = [
        command for command in result["commands"] if " -m pytest " in command
    ]
    assert len(pytest_commands) == 2
    assert all(command.count(" -n ") == 1 for command in pytest_commands)
    assert all(command.count(" --dist ") == 1 for command in pytest_commands)


def test_selector_bounds_workers_by_test_files_and_keeps_single_file_serial():
    result = select_tests.select_tests(
        ["scripts/remote_test_runner.py"],
        select_tests.load_matrix(),
    )

    pytest_commands = [
        command for command in result["commands"] if " -m pytest " in command
    ]
    two_file_command = next(
        command for command in pytest_commands if "tests/test_runner.py" in command
    )
    single_file_command = next(
        command
        for command in pytest_commands
        if "tests/test_remote_test_runner.py" in command
    )
    assert "-n 2 --dist loadfile" in two_file_command
    assert " -n " not in single_file_command


def test_selector_bounds_auto_appended_workers_at_six(tmp_path: Path):
    (tmp_path / "tests").mkdir()
    names = [f"test_pack_{index:02d}.py" for index in range(1, 10)]
    for name in names:
        (tmp_path / "tests" / name).write_text(
            "def test_value():\n    assert True\n",
            encoding="utf-8",
        )

    result = select_tests.select_tests(
        [f"tests/{name}" for name in names],
        {"rules": []},
        include_always=False,
        project_root=tmp_path,
    )

    assert result["commands"] == [
        ".\\.venv\\Scripts\\python.exe -m pytest "
        + " ".join(f"tests/{name}" for name in names)
        + ' -q -n 6 --dist loadfile -m "not serial" --maxfail=0'
    ]
    assert result["validationLayers"] == ["focused", "local-parallel"]


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
    assert FRONTEND_TYPECHECK_COMMAND in result["commands"]
    assert not any(command == "node web/node_modules/vitest/vitest.mjs run" for command in result["commands"])
    assert not any(command == "npm --prefix web run build" for command in result["commands"])


def test_selector_includes_global_vui_policy_gates_for_visible_ui():
    result = select_tests.select_tests(
        [
            "web/src/routes/companions/CompanionChatRails.styles.ts",
            "web/src/routes/companions/CompanionConversationHeader.tsx",
        ],
        select_tests.load_matrix(),
    )

    assert result["matchedRules"][0]["id"] == "frontend-workbench"
    assert any("vuiImportBoundary.test.ts" in command for command in result["commands"])
    assert any("vuiSurfaceAlphaPolicy.test.ts" in command for command in result["commands"])


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
    assert not any("test-tool-authorization" == rule["id"] for rule in ordinary_test["matchedRules"])
    assert not any("test_tool_authorization_test_contract.py" in command for command in ordinary_test["commands"])

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
        ".\\.venv\\Scripts\\python.exe -m pytest tests/test_runner.py -q --maxfail=0",
    ]
    assert result["validationLayers"] == ["hygiene", "focused"]


def test_selector_uses_static_python_imports_for_unmapped_product_sources(
    tmp_path: Path,
):
    (tmp_path / "core").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "core" / "direct.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "core" / "package_child.py").write_text("VALUE = 2\n", encoding="utf-8")
    (tmp_path / "tests" / "test_static_imports.py").write_text(
        "import core.direct\nfrom core import package_child\n",
        encoding="utf-8",
    )

    result = select_tests.select_tests(
        ["core/direct.py", "core/package_child.py"],
        {"rules": []},
        include_always=False,
        project_root=tmp_path,
    )

    fallback = result["matchedRules"][0]
    assert fallback["id"] == "python-import-fallback"
    assert fallback["matchedFiles"] == ["core/direct.py", "core/package_child.py"]
    assert fallback["selectedTests"] == ["tests/test_static_imports.py"]
    assert result["commands"] == [
        ".\\.venv\\Scripts\\python.exe -m pytest tests/test_static_imports.py -q --maxfail=0"
    ]
    assert result["coverageGaps"] == []
    assert result["validationLayers"] == ["focused"]


def test_selector_stops_at_nearest_tested_python_import_frontier(
    tmp_path: Path,
):
    (tmp_path / "core").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "core" / "leaf.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "core" / "internal.py").write_text(
        "from core import leaf\n",
        encoding="utf-8",
    )
    (tmp_path / "core" / "service.py").write_text(
        "from core import internal\n",
        encoding="utf-8",
    )
    (tmp_path / "core" / "outer.py").write_text(
        "from core import service\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_service.py").write_text(
        "from core import service\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_outer.py").write_text(
        "from core import outer\n",
        encoding="utf-8",
    )

    result = select_tests.select_tests(
        ["core/leaf.py"],
        {"rules": []},
        include_always=False,
        project_root=tmp_path,
    )

    fallback = result["matchedRules"][0]
    assert fallback["id"] == "python-import-fallback"
    assert fallback["matchedFiles"] == ["core/leaf.py"]
    assert fallback["selectedTests"] == ["tests/test_service.py"]
    assert result["coverageGaps"] == []


def test_selector_follows_relative_imports_to_the_nearest_tested_frontier(
    tmp_path: Path,
):
    package = tmp_path / "core" / "package"
    package.mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (package / "__init__.py").write_text("\n", encoding="utf-8")
    (package / "leaf.py").write_text("VALUE = 1\n", encoding="utf-8")
    (package / "internal.py").write_text("from . import leaf\n", encoding="utf-8")
    (package / "service.py").write_text("from . import internal\n", encoding="utf-8")
    (tmp_path / "tests" / "test_service.py").write_text(
        "from core.package import service\n",
        encoding="utf-8",
    )

    result = select_tests.select_tests(
        ["core/package/leaf.py"],
        {"rules": []},
        include_always=False,
        project_root=tmp_path,
    )

    assert result["matchedRules"][0]["selectedTests"] == ["tests/test_service.py"]
    assert result["coverageGaps"] == []


def test_selector_selects_real_pet_storage_nearest_tested_frontier():
    result = select_tests.select_tests(
        ["core/pet_system/utils/storage.py"],
        select_tests.load_matrix(),
    )

    fallback = next(
        rule
        for rule in result["matchedRules"]
        if rule["id"] == "python-import-fallback"
    )
    assert fallback["selectedTests"] == [
        "tests/test_config_sync.py",
        "tests/test_pet_system_tokens.py",
        "tests/test_pet_web_actions.py",
        "tests/test_tool_executor.py",
    ]
    assert result["coverageGaps"] == []


def test_selector_caps_and_ranks_import_fallback_tests_by_direct_boundary(
    tmp_path: Path,
):
    """Over-cap fallback selections keep the tests closest to the change."""
    core = tmp_path / "core"
    tests_root = tmp_path / "tests"
    core.mkdir()
    tests_root.mkdir()
    (core / "zone_leaf.py").write_text("VALUE = 1\n", encoding="utf-8")
    for index in range(1, 6):
        (tests_root / f"test_zone_{index:02d}.py").write_text(
            "import core.zone_leaf\n",
            encoding="utf-8",
        )
    (core / "alpha_chain.py").write_text("VALUE = 2\n", encoding="utf-8")
    (core / "alpha_mid.py").write_text(
        "from core import alpha_chain\n",
        encoding="utf-8",
    )
    (core / "alpha_top.py").write_text(
        "from core import alpha_mid\n",
        encoding="utf-8",
    )
    for index in range(1, 21):
        (tests_root / f"test_alpha_{index:02d}.py").write_text(
            "from core import alpha_top\n",
            encoding="utf-8",
        )

    result = select_tests.select_tests(
        ["core/zone_leaf.py", "core/alpha_chain.py"],
        {"rules": []},
        include_always=False,
        project_root=tmp_path,
    )

    assert len(result["matchedRules"]) == 1
    fallback = result["matchedRules"][0]
    kept = [f"tests/test_alpha_{index:02d}.py" for index in range(1, 8)]
    kept += [f"tests/test_zone_{index:02d}.py" for index in range(1, 6)]
    dropped = [f"tests/test_alpha_{index:02d}.py" for index in range(8, 21)]
    assert fallback["selectedTests"] == kept
    assert fallback["truncatedFrom"] == 25
    assert fallback["droppedTests"] == dropped
    assert any("exceeding the 12-file cap" in note for note in result["notes"])
    assert result["commands"] == [
        ".\\.venv\\Scripts\\python.exe -m pytest "
        + " ".join(kept)
        + ' -q -n 6 --dist loadfile -m "not serial" --maxfail=0'
    ]
    assert result["coverageGaps"] == []


def test_selector_runs_unmapped_changed_python_test_file_itself(tmp_path: Path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_unmapped.py").write_text(
        "def test_value():\n    assert True\n",
        encoding="utf-8",
    )

    result = select_tests.select_tests(
        ["tests/test_unmapped.py"],
        {"rules": []},
        include_always=False,
        project_root=tmp_path,
    )

    assert result["matchedRules"][0]["id"] == "changed-python-test-fallback"
    assert result["commands"] == [
        ".\\.venv\\Scripts\\python.exe -m pytest tests/test_unmapped.py -q --maxfail=0"
    ]
    assert result["coverageGaps"] == []


def test_selector_parallelizes_multiple_unmapped_changed_python_tests(tmp_path: Path):
    (tmp_path / "tests").mkdir()
    for name in ("test_alpha.py", "test_beta.py", "test_gamma.py"):
        (tmp_path / "tests" / name).write_text(
            "def test_value():\n    assert True\n",
            encoding="utf-8",
        )

    result = select_tests.select_tests(
        ["tests/test_alpha.py", "tests/test_beta.py", "tests/test_gamma.py"],
        {"rules": []},
        include_always=False,
        project_root=tmp_path,
    )

    assert result["commands"] == [
        ".\\.venv\\Scripts\\python.exe -m pytest tests/test_alpha.py "
        "tests/test_beta.py tests/test_gamma.py -q -n 3 --dist loadfile -m \"not serial\" --maxfail=0"
    ]
    assert result["validationLayers"] == ["focused", "local-parallel"]


def test_selector_separates_serial_changed_python_tests(tmp_path: Path):
    (tmp_path / "tests").mkdir()
    for name in ("test_alpha.py", "test_beta.py"):
        (tmp_path / "tests" / name).write_text(
            "def test_value():\n    assert True\n",
            encoding="utf-8",
        )
    (tmp_path / "tests" / "test_serial.py").write_text(
        "import pytest\npytestmark = pytest.mark.serial\n",
        encoding="utf-8",
    )

    result = select_tests.select_tests(
        ["tests/test_alpha.py", "tests/test_beta.py", "tests/test_serial.py"],
        {"rules": []},
        include_always=False,
        project_root=tmp_path,
    )

    assert result["commands"] == [
        ".\\.venv\\Scripts\\python.exe -m pytest tests/test_alpha.py "
        "tests/test_beta.py -q -n 2 --dist loadfile -m \"not serial\" --maxfail=0",
        ".\\.venv\\Scripts\\python.exe -m pytest tests/test_serial.py -q --maxfail=0",
    ]
    assert result["validationLayers"] == ["focused", "local-parallel", "local-serial"]


def test_selector_ignores_serial_marker_text_below_module_scope(tmp_path: Path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_alpha.py").write_text(
        "def test_fixture_text():\n    value = 'pytestmark = pytest.mark.serial'\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_beta.py").write_text(
        "def test_value():\n    assert True\n",
        encoding="utf-8",
    )

    result = select_tests.select_tests(
        ["tests/test_alpha.py", "tests/test_beta.py"],
        {"rules": []},
        include_always=False,
        project_root=tmp_path,
    )

    assert result["commands"] == [
        ".\\.venv\\Scripts\\python.exe -m pytest tests/test_alpha.py "
        "tests/test_beta.py -q -n 2 --dist loadfile -m \"not serial\" --maxfail=0"
    ]


def test_selector_separates_serial_static_import_tests(tmp_path: Path):
    (tmp_path / "core").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "core" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_parallel.py").write_text(
        "import core.module\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_serial.py").write_text(
        "import core.module\npytestmark = pytest.mark.serial\n",
        encoding="utf-8",
    )

    result = select_tests.select_tests(
        ["core/module.py"],
        {"rules": []},
        include_always=False,
        project_root=tmp_path,
    )

    assert result["commands"] == [
        ".\\.venv\\Scripts\\python.exe -m pytest tests/test_parallel.py -q --maxfail=0",
        ".\\.venv\\Scripts\\python.exe -m pytest tests/test_serial.py -q --maxfail=0",
    ]
    assert result["validationLayers"] == ["focused", "local-serial"]


def test_selector_reports_unmapped_python_source_as_coverage_gap(tmp_path: Path):
    (tmp_path / "core").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "core" / "orphan.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_unrelated.py").write_text(
        "def test_value():\n    assert True\n",
        encoding="utf-8",
    )

    result = select_tests.select_tests(
        ["core/orphan.py"],
        {"rules": []},
        include_always=False,
        project_root=tmp_path,
    )

    assert result["matchedRules"] == []
    assert result["commands"] == []
    assert result["coverageGaps"] == [
        {"path": "core/orphan.py", "reason": "no-static-test-import"}
    ]
    assert any("No static test import" in note for note in result["notes"])


def test_selector_keeps_explicit_matrix_rule_ahead_of_static_import_fallback():
    result = select_tests.select_tests(
        ["core/web/services/session_service.py"],
        select_tests.load_matrix(),
    )

    assert [rule["id"] for rule in result["matchedRules"]] == ["web-session-chat"]
    assert result["coverageGaps"] == []


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


def test_cli_import_fallback_cap_hint_is_explicit_on_commands_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    payload = {
        "changedFiles": ["core/example.py"],
        "matchedRules": [
            {
                "id": "python-import-fallback",
                "description": "Tests at the nearest statically provable Python import frontier.",
                "matchedFiles": ["core/example.py"],
                "selectedTests": [f"tests/test_kept_{index:02d}.py" for index in range(12)],
                "truncatedFrom": 25,
                "droppedTests": [f"tests/test_far_{index:02d}.py" for index in range(13)],
            }
        ],
        "commands": [],
        "notes": ["Python import fallback matched 25 test files."],
        "coverageGaps": [],
        "validationLayers": ["focused", "local-parallel"],
        "executionPlan": {},
    }
    monkeypatch.setattr(select_tests, "select_tests", lambda *_args, **_kwargs: payload)

    exit_code = select_tests.main(
        ["--changed-file", "core/example.py", "--commands-only"]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    hint = next(
        line for line in captured.err.splitlines() if "Import fallback cap" in line
    )
    assert "python-import-fallback" in hint
    assert "exceeding the 12-file cap" in hint
    assert "Add focused matrix entries" in hint
