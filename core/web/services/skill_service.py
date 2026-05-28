"""Read-only skill library service for the web workbench."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.chat.skill_registry import SkillDescriptor, default_skill_roots, resolve_skill


MAX_SKILL_PREVIEW_CHARS = 1_600
MAX_SKILL_CONTENT_CHARS = 80_000


def get_skill_library(*, roots: list[Path] | None = None) -> dict[str, Any]:
    """Return discovered local skills without exposing full instruction bodies."""

    root_paths = [Path(root) for root in roots] if roots is not None else default_skill_roots()
    skills: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for root in root_paths:
        for descriptor in _iter_skill_descriptors(root):
            path_key = str(descriptor.path.resolve())
            if path_key in seen_paths:
                continue
            seen_paths.add(path_key)
            skills.append(_skill_summary(descriptor, root=root))

    skills.sort(key=lambda item: (str(item.get("source") or ""), str(item.get("name") or "").lower()))
    counts = {
        "total": len(skills),
        "codex": sum(1 for item in skills if item.get("source") == "codex"),
        "agents": sum(1 for item in skills if item.get("source") == "agents"),
        "other": sum(1 for item in skills if item.get("source") == "other"),
    }
    _record_skill_library_event("skill.library.listed", counts=counts, skill_name="", skill_hash="")
    return {
        "schemaVersion": 1,
        "mode": "read_only",
        "roots": [_root_payload(root) for root in root_paths],
        "counts": counts,
        "skills": skills,
    }


def get_skill_detail(command: str, *, roots: list[Path] | None = None) -> dict[str, Any]:
    """Return one local skill with bounded SKILL.md content for preview."""

    root_paths = [Path(root) for root in roots] if roots is not None else default_skill_roots()
    descriptor = resolve_skill(command, roots=root_paths)
    if descriptor is None:
        raise FileNotFoundError(f"Unknown skill: {command}")
    root = _matching_root(descriptor.path, root_paths)
    content = descriptor.content
    truncated = len(content) > MAX_SKILL_CONTENT_CHARS
    if truncated:
        content = content[:MAX_SKILL_CONTENT_CHARS].rstrip()
    payload = _skill_summary(descriptor, root=root)
    payload.update(
        {
            "content": content,
            "contentTruncated": truncated,
        }
    )
    _record_skill_library_event(
        "skill.library.detail_viewed",
        counts={},
        skill_name=descriptor.name,
        skill_hash=descriptor.content_hash,
    )
    return payload


def _iter_skill_descriptors(root: Path) -> list[SkillDescriptor]:
    if not root.exists() or not root.is_dir():
        return []
    descriptors: list[SkillDescriptor] = []
    for path in sorted(root.glob("*/SKILL.md"), key=lambda item: item.parent.name.lower()):
        descriptor = resolve_skill(path.parent.name, roots=[root])
        if descriptor is not None:
            descriptors.append(descriptor)
    return descriptors


def _skill_summary(skill: SkillDescriptor, *, root: Path | None) -> dict[str, Any]:
    content = skill.content.strip()
    preview = content[:MAX_SKILL_PREVIEW_CHARS].rstrip()
    if len(content) > MAX_SKILL_PREVIEW_CHARS:
        preview = f"{preview}\n\n..."
    aliases = list(skill.aliases)
    primary_alias = aliases[0] if aliases else str(skill.name or skill.path.parent.name).strip().lower()
    return {
        "name": skill.name,
        "aliases": aliases,
        "command": f"/{primary_alias}",
        "description": skill.description,
        "source": _root_source(root),
        "rootPath": str(root or ""),
        "path": str(skill.path),
        "directoryName": skill.path.parent.name,
        "hash": skill.content_hash,
        "contentLength": skill.content_length,
        "preview": preview,
        "previewTruncated": len(content) > MAX_SKILL_PREVIEW_CHARS,
    }


def _root_payload(root: Path) -> dict[str, Any]:
    return {
        "path": str(root),
        "source": _root_source(root),
        "exists": root.exists() and root.is_dir(),
    }


def _matching_root(path: Path, roots: list[Path]) -> Path | None:
    resolved_path = path.resolve()
    for root in roots:
        try:
            resolved_path.relative_to(root.resolve())
            return root
        except ValueError:
            continue
    return None


def _root_source(root: Path | None) -> str:
    text = str(root or "").replace("\\", "/").lower()
    if text.endswith("/.codex/skills"):
        return "codex"
    if text.endswith("/.agents/skills"):
        return "agents"
    return "other"


def _record_skill_library_event(
    event_code: str,
    *,
    counts: dict[str, Any],
    skill_name: str,
    skill_hash: str,
) -> None:
    try:
        from core.web.services.runtime_scene_service import record_runtime_scene_event

        record_runtime_scene_event(
            "skills",
            "library",
            event_code,
            level="info",
            outcome="succeeded",
            message="Skill library read-only API served.",
            fields={
                "total": int(counts.get("total") or 0),
                "codex": int(counts.get("codex") or 0),
                "agents": int(counts.get("agents") or 0),
                "other": int(counts.get("other") or 0),
                "skillName": str(skill_name or "").strip(),
                "skillHash": str(skill_hash or "").strip(),
            },
            lifecycle=True,
        )
    except Exception:
        pass
