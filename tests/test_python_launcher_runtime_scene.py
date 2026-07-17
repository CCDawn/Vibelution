from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_launcher_module():
    script_path = Path(__file__).parents[1] / "scripts" / "vibelution_launcher.py"
    spec = importlib.util.spec_from_file_location("vibelution_launcher_runtime_scene_test", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_python_launcher_rotates_active_runtime_scene_for_each_start(tmp_path, monkeypatch) -> None:
    launcher = _load_launcher_module()
    runtime_dir = tmp_path / ".runtime" / "launcher"
    scene_root = tmp_path / "logs" / "runtime_scenes"
    active_path = runtime_dir / "active-runtime-scene.json"
    monkeypatch.setattr(launcher, "RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(launcher, "RUNTIME_SCENE_ROOT", scene_root)
    monkeypatch.setattr(launcher, "ACTIVE_RUNTIME_SCENE_PATH", active_path)

    first = launcher._start_runtime_scene("python_launcher_start")
    second = launcher._start_runtime_scene("python_launcher_start")

    assert first["runtimeSceneId"] != second["runtimeSceneId"]
    assert first["runtimeSceneDir"] != second["runtimeSceneDir"]
    assert Path(first["runtimeSceneDir"]).is_dir()
    assert Path(second["runtimeSceneDir"]).is_dir()
    assert json.loads(active_path.read_text(encoding="utf-8")) == second
    for relative_dir in ("events", "raw", "conversations", "agent", "artifacts"):
        assert (Path(second["runtimeSceneDir"]) / relative_dir).is_dir()
