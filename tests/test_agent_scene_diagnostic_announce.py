#!/usr/bin/env python3
import types
from pathlib import Path

import agent as agent_module
from agent import SelfEvolvingAgent


class _FakeUi:
    def __init__(self):
        self.logs = []

    def add_log(self, message, level):
        self.logs.append((message, level))


def _bound_agent(scene_dir) -> tuple:
    fake = types.SimpleNamespace()
    fake._resolve_current_scene_dir_for_diagnostic = lambda: scene_dir
    method = types.MethodType(SelfEvolvingAgent._announce_scene_diagnostic_package, fake)
    return fake, method


def test_announce_prints_scene_package_path(tmp_path, monkeypatch):
    scene_dir = tmp_path / "logs" / "runtime_scenes" / "20260812T000000Z__cli-diag"
    scene_dir.mkdir(parents=True)
    fake_ui = _FakeUi()
    monkeypatch.setattr(agent_module, "get_ui", lambda: fake_ui)

    fake, method = _bound_agent(scene_dir)
    method()

    assert len(fake_ui.logs) == 1
    message, level = fake_ui.logs[0]
    assert level == "ERROR"
    assert "20260812T000000Z__cli-diag" in message
    assert "package_index.json" in message


def test_announce_skips_without_scene(tmp_path, monkeypatch):
    fake_ui = _FakeUi()
    monkeypatch.setattr(agent_module, "get_ui", lambda: fake_ui)

    fake = types.SimpleNamespace()
    fake._resolve_current_scene_dir_for_diagnostic = lambda: None
    method = types.MethodType(SelfEvolvingAgent._announce_scene_diagnostic_package, fake)
    method()

    assert fake_ui.logs == []


def test_announce_swallows_resolution_failure(tmp_path, monkeypatch):
    fake_ui = _FakeUi()
    monkeypatch.setattr(agent_module, "get_ui", lambda: fake_ui)

    def _boom():
        raise RuntimeError("scene root unavailable")

    fake = types.SimpleNamespace()
    fake._resolve_current_scene_dir_for_diagnostic = _boom
    method = types.MethodType(SelfEvolvingAgent._announce_scene_diagnostic_package, fake)
    method()

    assert fake_ui.logs == []
