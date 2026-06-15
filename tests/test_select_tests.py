import json
from pathlib import Path

import pytest

from tests import select_tests


def test_matrix_loads_with_builtin_subset_parser():
    matrix = select_tests._parse_yaml_subset(select_tests.DEFAULT_MATRIX.read_text(encoding="utf-8"))

    assert matrix["version"] == 1
    assert matrix["always"]["commands"] == ["git diff --check"]
    assert any(rule["id"] == "web-session-chat" for rule in matrix["rules"])


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


def test_selector_matches_web_config_routes_to_config_validation_commands():
    result = select_tests.select_tests(
        ["tests/test_web_config_routes.py"],
        select_tests.load_matrix(),
    )

    assert result["matchedRules"][0]["id"] == "config-models"
    assert "tests/test_web_config_routes.py" in result["matchedRules"][0]["matchedFiles"]
    assert any("tests/test_web_config_routes.py" in command for command in result["commands"])
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
