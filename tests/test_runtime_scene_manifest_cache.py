"""Pin the scene-manifest parse cache used by turn telemetry.

Every lifecycle event on the turn-preparation path resolved manifest.json
again (read_text + json.loads). Seven of them run back to back before the
first LLM request, so the repeated parse showed up directly in
postPrepareEventsMs.
"""

import json
from pathlib import Path

from core.web.services.runtime_scene import record as scene_record


def _write_manifest(scene_dir: Path, payload: dict) -> None:
    scene_dir.mkdir(parents=True, exist_ok=True)
    (scene_dir / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")


def test_reuses_the_parse_while_the_manifest_is_unchanged(tmp_path, monkeypatch):
    scene_dir = tmp_path / "scene"
    _write_manifest(scene_dir, {"runtime_scene_id": "scene-1"})

    reads = {"count": 0}
    original = Path.read_text

    def counting_read_text(self, *args, **kwargs):
        if self.name == "manifest.json":
            reads["count"] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)

    first = scene_record._load_scene_manifest(scene_dir)
    second = scene_record._load_scene_manifest(scene_dir)

    assert first == {"runtime_scene_id": "scene-1"}
    assert second == first
    assert reads["count"] == 1, "the second call must come from the stamp cache"


def test_rereads_after_the_manifest_changes(tmp_path):
    scene_dir = tmp_path / "scene"
    _write_manifest(scene_dir, {"runtime_scene_id": "scene-1"})
    assert scene_record._load_scene_manifest(scene_dir)["runtime_scene_id"] == "scene-1"

    _write_manifest(scene_dir, {"runtime_scene_id": "scene-2", "extra": "rewritten"})
    assert scene_record._load_scene_manifest(scene_dir)["runtime_scene_id"] == "scene-2"


def test_missing_manifest_returns_empty_mapping(tmp_path):
    assert scene_record._load_scene_manifest(tmp_path / "absent") == {}


def test_returned_mapping_is_a_copy(tmp_path):
    scene_dir = tmp_path / "scene"
    _write_manifest(scene_dir, {"runtime_scene_id": "scene-1"})

    first = scene_record._load_scene_manifest(scene_dir)
    first["runtime_scene_id"] = "mutated"

    assert scene_record._load_scene_manifest(scene_dir)["runtime_scene_id"] == "scene-1"
