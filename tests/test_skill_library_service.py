from __future__ import annotations

import json
from pathlib import Path

from core.web.services import skill_library_service


def _write_skill(root: Path, name: str, description: str, body: str = "") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f"description: {description}",
                "---",
                "",
                body or f"# {name}\n\nUse this skill for searchable work.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return root


def test_initializes_external_skill_library_structure(tmp_path):
    payload = skill_library_service.initialize_skill_library(root=tmp_path / "skills")

    assert payload["root"].endswith("skills")
    assert (tmp_path / "skills" / "managed" / "shared").is_dir()
    assert (tmp_path / "skills" / "managed" / "teams").is_dir()
    assert (tmp_path / "skills" / "managed" / "agents").is_dir()
    assert (tmp_path / "skills" / "system_index" / "indexes").is_dir()
    assert (tmp_path / "skills" / "indexes").is_dir()


def test_imports_managed_skill_and_searches_external_index(tmp_path):
    source = _write_skill(
        tmp_path / "source" / "brt",
        "ccdawn-brt",
        "Behavior Review Test gate",
        "# BRT\n\nUse for behavior review and test planning.",
    )

    imported = skill_library_service.import_managed_skill(source, root=tmp_path / "skills")
    payload = skill_library_service.search_skill_library(query="behavior review", source="managed", root=tmp_path / "skills")

    assert imported["status"] == "imported"
    assert payload["retrievalPolicy"]["fallsBackToCodexSkills"] is False
    assert payload["summary"]["resultCount"] == 1
    result = payload["results"][0]
    assert result["skillId"] == "ccdawn-brt"
    assert result["sourceKind"] == "managed"
    assert result["readOnly"] is False
    assert result["executionBoundary"] == "manifest_allowlist"


def test_indexes_system_skills_as_read_only_without_copying(tmp_path):
    system_skill = _write_skill(
        tmp_path / "system" / "openai-docs",
        "openai-docs",
        "Search official OpenAI docs",
        "# OpenAI Docs\n\nUse official documentation and cite sources.",
    )

    payload = skill_library_service.rebuild_skill_indexes(root=tmp_path / "skills", system_roots=[tmp_path / "system"])
    result = skill_library_service.search_skill_library(query="official documentation", source="system_index", root=tmp_path / "skills")

    assert payload["summary"]["systemIndexCount"] == 1
    assert result["summary"]["resultCount"] == 1
    item = result["results"][0]
    assert item["sourceKind"] == "system_index"
    assert item["readOnly"] is True
    assert item["executionAllowed"] is False
    assert item["sourcePath"] == str(system_skill.resolve())
    assert not (tmp_path / "skills" / "managed" / "shared" / "openai-docs").exists()


def test_managed_import_preserves_existing_system_index(tmp_path):
    _write_skill(tmp_path / "system" / "system-tool", "system-tool", "Native system skill", "system native")
    managed_source = _write_skill(tmp_path / "source" / "managed-tool", "managed-tool", "Managed skill", "managed native")
    skill_library_service.rebuild_skill_indexes(root=tmp_path / "skills", system_roots=[tmp_path / "system"])

    skill_library_service.import_managed_skill(managed_source, root=tmp_path / "skills")
    result = skill_library_service.search_skill_library(query="native", root=tmp_path / "skills")
    source_kinds = {item["sourceKind"] for item in result["results"]}

    assert source_kinds == {"managed", "system_index"}


def test_agent_and_team_scoped_managed_skills_are_isolated(tmp_path):
    team_source = _write_skill(tmp_path / "source" / "team", "team-skill", "Team-only skill", "challenge cup workflow")
    agent_source = _write_skill(tmp_path / "source" / "agent", "agent-skill", "Agent-only skill", "private reflection")
    skill_library_service.import_managed_skill(team_source, scope_type="team", owner_id="team-a", root=tmp_path / "skills")
    skill_library_service.import_managed_skill(agent_source, scope_type="agent", owner_id="agent-a", root=tmp_path / "skills")

    team_visible = skill_library_service.search_skill_library(
        query="workflow",
        scope="team",
        team_id="team-a",
        root=tmp_path / "skills",
    )
    team_hidden = skill_library_service.search_skill_library(
        query="workflow",
        scope="team",
        team_id="team-b",
        root=tmp_path / "skills",
    )
    agent_visible = skill_library_service.search_skill_library(
        query="reflection",
        scope="agent",
        actor_agent_id="agent-a",
        root=tmp_path / "skills",
    )
    agent_hidden = skill_library_service.search_skill_library(
        query="reflection",
        scope="agent",
        actor_agent_id="agent-b",
        root=tmp_path / "skills",
    )

    assert team_visible["summary"]["resultCount"] == 1
    assert team_hidden["summary"]["resultCount"] == 0
    assert agent_visible["summary"]["resultCount"] == 1
    assert agent_hidden["summary"]["resultCount"] == 0


def test_script_execution_requires_managed_manifest_allowlist(tmp_path):
    source = _write_skill(tmp_path / "source" / "runner", "runner-skill", "Runs allowed scripts", "script runner")
    scripts_dir = source / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "run.py").write_text("print('ok')\n", encoding="utf-8")
    skill_library_service.import_managed_skill(source, root=tmp_path / "skills")
    manifest_path = tmp_path / "skills" / "managed" / "shared" / "runner-skill" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["execution"] = {"enabled": True, "allowedScripts": ["scripts/run.py"], "requiresManifestAllowlist": True}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    skill_library_service.rebuild_skill_indexes(root=tmp_path / "skills", system_roots=[])

    allowed = skill_library_service.validate_skill_script_execution("runner-skill", "scripts/run.py", root=tmp_path / "skills")
    blocked = skill_library_service.validate_skill_script_execution("runner-skill", "scripts/other.py", root=tmp_path / "skills")

    assert allowed["executionAllowed"] is True
    assert allowed["reason"] == "allowed_by_manifest"
    assert blocked["executionAllowed"] is False
    assert blocked["reason"] == "script_not_in_manifest_allowlist"


def test_system_index_skills_cannot_be_executed_by_library(tmp_path):
    _write_skill(tmp_path / "system" / "system-tool", "system-tool", "Native system skill", "system native")
    skill_library_service.rebuild_skill_indexes(root=tmp_path / "skills", system_roots=[tmp_path / "system"])
    result = skill_library_service.search_skill_library(query="native", source="system_index", root=tmp_path / "skills")

    skill_id = result["results"][0]["skillId"]
    execution = skill_library_service.validate_skill_script_execution(skill_id, "scripts/run.py", root=tmp_path / "skills")

    assert execution["executionAllowed"] is False
    assert execution["reason"] == "system_index_is_read_only"
    assert execution["skillId"] == skill_id
