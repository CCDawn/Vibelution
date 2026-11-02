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


def test_skill_library_lists_legacy_ccdawn_alias_as_compatible_skill(tmp_path, monkeypatch):
    """Expose the old skill id for compatibility without making it the default route."""

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


def _write_same_command_under_both_roots(tmp_path: Path) -> tuple[Path, Path]:
    """Install one slash command under a codex root and an agents root.

    The directory suffixes matter: ``_root_source`` classifies a root by its
    ``/.codex/skills`` / ``/.agents/skills`` tail, which is what the ``source``
    filter keys on.
    """

    codex_root = tmp_path / ".codex" / "skills"
    agents_root = tmp_path / ".agents" / "skills"
    _write_skill(codex_root, "router", name="router", body="Codex copy of the router.")
    _write_skill(agents_root, "router", name="router", body="Agents copy of the router.")
    return codex_root, agents_root


def test_skill_detail_without_source_keeps_registry_first_match(tmp_path):
    codex_root, agents_root = _write_same_command_under_both_roots(tmp_path)

    first_codex = skill_service.get_skill_detail("router", roots=[codex_root, agents_root])
    first_agents = skill_service.get_skill_detail("router", roots=[agents_root, codex_root])

    assert first_codex["source"] == "codex"
    assert "Codex copy of the router." in first_codex["content"]
    assert first_agents["source"] == "agents"
    assert "Agents copy of the router." in first_agents["content"]


@pytest.mark.parametrize(
    ("source", "expected_source", "expected_body"),
    [
        ("agents", "agents", "Agents copy of the router."),
        ("codex", "codex", "Codex copy of the router."),
        # The filter is tolerant of surrounding whitespace and casing.
        (" Agents ", "agents", "Agents copy of the router."),
    ],
)
def test_skill_detail_source_filter_resolves_requested_root(tmp_path, source, expected_source, expected_body):
    codex_root, agents_root = _write_same_command_under_both_roots(tmp_path)

    payload = skill_service.get_skill_detail("router", roots=[codex_root, agents_root], source=source)

    assert payload["source"] == expected_source
    assert payload["command"] == "/router"
    assert expected_body in payload["content"]
    assert Path(payload["path"]).resolve().is_relative_to((codex_root if expected_source == "codex" else agents_root).resolve())


def test_skill_detail_source_filter_does_not_fall_back_to_other_roots(tmp_path):
    """A source that has no matching root, or no matching skill, is a miss."""

    codex_root = tmp_path / ".codex" / "skills"
    agents_root = tmp_path / ".agents" / "skills"
    _write_skill(codex_root, "only-codex", name="only-codex")
    agents_root.mkdir(parents=True)

    assert skill_service.get_skill_detail("only-codex", roots=[codex_root, agents_root])["source"] == "codex"
    with pytest.raises(FileNotFoundError):
        skill_service.get_skill_detail("only-codex", roots=[codex_root, agents_root], source="agents")
    with pytest.raises(FileNotFoundError):
        skill_service.get_skill_detail("only-codex", roots=[codex_root, agents_root], source="other")
