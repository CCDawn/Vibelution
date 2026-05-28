from pathlib import Path

import pytest

from core.web.services import skill_service


def _write_skill(root: Path, dirname: str, *, name: str, description: str = "Demo skill", body: str = "Use this workflow.") -> Path:
    skill_dir = root / dirname
    skill_dir.mkdir(parents=True)
    path = skill_dir / "SKILL.md"
    path.write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\n{body}\n",
        encoding="utf-8",
    )
    return path


def test_skill_library_lists_safe_summaries(tmp_path, monkeypatch):
    _write_skill(tmp_path, "ccdawn-brt", name="ccdawn-brt", body="Stop before implementation.")
    events: list[dict] = []
    monkeypatch.setattr(
        "core.web.services.runtime_scene_service.record_runtime_scene_event",
        lambda component, phase, event_code, **kwargs: events.append(
            {"component": component, "phase": phase, "eventCode": event_code, **kwargs}
        ),
    )

    payload = skill_service.get_skill_library(roots=[tmp_path])

    assert payload["mode"] == "read_only"
    assert payload["counts"]["total"] == 1
    skill = payload["skills"][0]
    assert skill["name"] == "ccdawn-brt"
    assert skill["command"] == "/ccdawn-brt"
    assert "Stop before implementation." in skill["preview"]
    assert "content" not in skill
    assert skill["hash"]
    assert events[-1]["eventCode"] == "skill.library.listed"


def test_skill_detail_returns_bounded_content_by_alias(tmp_path):
    _write_skill(tmp_path, "code-1.0.4", name="Code", body="Read the codebase first.")

    payload = skill_service.get_skill_detail("code", roots=[tmp_path])

    assert payload["name"] == "Code"
    assert payload["command"] == "/code"
    assert "Read the codebase first." in payload["content"]
    assert payload["contentTruncated"] is False


def test_skill_detail_rejects_unknown_skill(tmp_path):
    _write_skill(tmp_path, "brt", name="brt")

    with pytest.raises(FileNotFoundError):
        skill_service.get_skill_detail("missing", roots=[tmp_path])
