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
    assert matrix["always"]["commands"] == ["git diff --check"]
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

        for command in rule.get("commands", []):
            for match in re.finditer(r"tests/[A-Za-z0-9_./-]+\.py", str(command).replace("\\", "/")):
                test_path = match.group(0)
                if not (PROJECT_ROOT / test_path).exists():
                    missing_command_tests.append(f"{rule['id']}:{test_path}")

    assert missing_paths == []
    assert missing_command_tests == []


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

    test_conftest._test_file_needs_singleton_reset.cache_clear()

    assert test_conftest._test_file_needs_singleton_reset(str(pure_test)) is False
    assert test_conftest._test_file_needs_singleton_reset(str(singleton_test)) is True


def test_selector_matches_session_service_to_chat_validation_commands():
    result = select_tests.select_tests(
        ["core\\web\\services\\session_service.py"],
        select_tests.load_matrix(),
    )

    assert result["matchedRules"][0]["id"] == "web-session-chat"
    assert "core/web/services/session_service.py" in result["matchedRules"][0]["matchedFiles"]
    assert "git diff --check" in result["commands"]
    assert any("tests/test_web_session_routes.py" in command for command in result["commands"])
    assert any("ChatCodingRoute.layout.test.ts" in command for command in result["commands"])


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
    assert any("ChatCodingRoute.layout.test.ts" in command for command in result["commands"])


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


def test_selector_matches_real_runtime_route_to_runtime_validation_commands():
    result = select_tests.select_tests(
        ["core/web/routes/runtime.py"],
        select_tests.load_matrix(),
    )

    assert result["matchedRules"][0]["id"] == "web-runtime-launcher"
    assert "core/web/routes/runtime.py" in result["matchedRules"][0]["matchedFiles"]
    assert any("tests/test_web_runtime_routes.py" in command for command in result["commands"])
    assert not any("tests/test_web_app.py" in command for command in result["commands"])


def test_selector_uses_default_when_no_rule_matches():
    result = select_tests.select_tests(["workspace/runtime-cache/example.json"], select_tests.load_matrix())

    assert result["matchedRules"] == []
    assert result["commands"] == [
        "git diff --check",
        ".\\.venv\\Scripts\\python.exe -m pytest tests/test_runner.py -q",
        ".\\.venv\\Scripts\\python.exe -m pytest tests/ --collect-only -q",
    ]


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
