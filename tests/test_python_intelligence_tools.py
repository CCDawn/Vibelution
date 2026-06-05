#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
from types import SimpleNamespace

from tools import python_intelligence_tools as pit


def test_python_symbol_query_degrades_cleanly_without_jedi(monkeypatch, tmp_path):
    source = tmp_path / "demo.py"
    source.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(pit, "_module_available", lambda name: False if name == "jedi" else True)
    monkeypatch.setattr(pit, "_project_root", lambda: tmp_path)

    payload = json.loads(pit.python_symbol_query(str(source), 1, 0))

    assert payload["status"] == "unavailable"
    assert payload["missing_dependency"] == "jedi"


def test_python_lint_tool_degrades_cleanly_without_ruff(monkeypatch, tmp_path):
    monkeypatch.setattr(pit, "_module_available", lambda name: False if name == "ruff" else True)
    monkeypatch.setattr(pit, "_project_root", lambda: tmp_path)

    payload = json.loads(pit.python_lint_tool("."))

    assert payload["status"] == "unavailable"
    assert payload["missing_dependency"] == "ruff"


def test_python_lint_tool_parses_ruff_json(monkeypatch, tmp_path):
    source = tmp_path / "demo.py"
    source.write_text("import os\n", encoding="utf-8")
    monkeypatch.setattr(pit, "_module_available", lambda name: True)
    monkeypatch.setattr(pit, "_project_root", lambda: tmp_path)

    def fake_run(command, cwd, capture_output, text, timeout):
        return SimpleNamespace(
            returncode=1,
            stdout=json.dumps(
                [
                    {
                        "filename": str(source),
                        "code": "F401",
                        "message": "`os` imported but unused",
                        "location": {"row": 1, "column": 8},
                        "end_location": {"row": 1, "column": 10},
                    }
                ]
            ),
            stderr="",
        )

    monkeypatch.setattr(pit.subprocess, "run", fake_run)

    payload = json.loads(pit.python_lint_tool(str(source)))

    assert payload["status"] == "ok"
    assert payload["issue_count"] == 1
    assert payload["issues"][0]["code"] == "F401"


def test_code_symbol_tool_v2_rejects_deprecated_modes():
    payload = json.loads(pit.code_symbol_tool(mode="outline", file_path="agent.py"))

    assert payload["status"] == "error"
    assert payload["error"] == "deprecated_mode"
    assert "inspect/search/references/explore/impact/affected_tests" in payload["message"]


def test_code_symbol_tool_v2_indexes_searches_and_inspects_project(tmp_path, monkeypatch):
    from core.code_context_graph import service as graph_service

    (tmp_path / "core").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "web" / "src").mkdir(parents=True)
    (tmp_path / "workspace" / "prompts").mkdir(parents=True)
    (tmp_path / "workspace" / "chat").mkdir(parents=True)
    (tmp_path / "agent.py").write_text("from core.demo import helper\n", encoding="utf-8")
    (tmp_path / "core" / "demo.py").write_text(
        '"""demo module"""\n\n'
        "def helper():\n"
        "    return 1\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_demo.py").write_text("from core.demo import helper\n\ndef test_helper():\n    assert helper() == 1\n", encoding="utf-8")
    (tmp_path / "web" / "src" / "Demo.tsx").write_text("export function DemoView() { return null }\n", encoding="utf-8")
    (tmp_path / "workspace" / "prompts" / "CODEBASE_MAP.md").write_text("# Codebase Map\n", encoding="utf-8")
    (tmp_path / "workspace" / "chat" / "chat_state.json").write_text('{"noise": true}', encoding="utf-8")

    monkeypatch.setattr(graph_service, "project_root", lambda: tmp_path)

    indexed = json.loads(pit.code_symbol_tool(mode="index"))
    search = json.loads(pit.code_symbol_tool(mode="search", query="helper"))
    inspected = json.loads(pit.code_symbol_tool(mode="inspect", file_path="core/demo.py"))
    impact = json.loads(pit.code_symbol_tool(mode="impact", file_path="core/demo.py"))
    tests = json.loads(pit.code_symbol_tool(mode="affected_tests", file_path="core/demo.py"))

    assert indexed["status"] == "ok"
    assert indexed["summary"]["fileCount"] >= 5
    assert not any(item["path"].startswith("workspace/chat/") for item in indexed["files"])
    assert any(item["path"] == "workspace/prompts/CODEBASE_MAP.md" for item in indexed["files"])
    assert search["count"] >= 1
    assert inspected["file"]["path"] == "core/demo.py"
    assert any(item["qualifiedName"] == "helper" for item in inspected["symbols"])
    assert "agent.py" in impact["directDependents"]
    assert any(item["path"] == "tests/test_demo.py" for item in tests["tests"])


def test_python_symbol_query_parses_jedi_results(monkeypatch, tmp_path):
    source = tmp_path / "demo.py"
    source.write_text("value = 1\nprint(value)\n", encoding="utf-8")
    monkeypatch.setattr(pit, "_module_available", lambda name: True)
    monkeypatch.setattr(pit, "_project_root", lambda: tmp_path)

    class DummySymbol:
        name = "value"
        type = "statement"
        description = "value = 1"
        module_name = "demo"
        module_path = source
        line = 1
        column = 0

        def docstring(self):
            return "demo doc"

    class DummyScript:
        def __init__(self, path):
            self.path = path

        def goto(self, line, column, follow_imports=True):
            return [DummySymbol()]

        def get_references(self, line, column, include_builtins=False):
            return [DummySymbol()]

        def infer(self, line, column):
            return [DummySymbol()]

    fake_jedi = SimpleNamespace(Script=DummyScript)
    monkeypatch.setitem(__import__("sys").modules, "jedi", fake_jedi)

    payload = json.loads(pit.python_symbol_query(str(source), 2, 6, action="hover"))

    assert payload["status"] == "ok"
    assert payload["action"] == "hover"
    assert payload["results"][0]["name"] == "value"
    assert payload["results"][0]["docstring"] == "demo doc"
