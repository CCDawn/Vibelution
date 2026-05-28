"""Skill discovery and prompt packaging for chat slash commands."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


MAX_SKILL_CONTENT_CHARS = 24_000


@dataclass(frozen=True)
class SkillDescriptor:
    name: str
    path: Path
    description: str = ""
    aliases: tuple[str, ...] = ()
    content: str = ""
    content_hash: str = ""
    content_length: int = 0


def default_skill_roots() -> list[Path]:
    roots: list[Path] = []
    home = Path.home()
    for relative in (".codex/skills", ".agents/skills"):
        candidate = home / relative
        if candidate.exists():
            roots.append(candidate)
    return roots


def resolve_skill(command: str, *, roots: Iterable[Path] | None = None) -> SkillDescriptor | None:
    alias = normalize_skill_alias(command)
    if not alias:
        return None
    for root in roots if roots is not None else default_skill_roots():
        descriptor = _resolve_skill_in_root(alias, Path(root))
        if descriptor is not None:
            return descriptor
    return None


def normalize_skill_alias(value: str) -> str:
    normalized = str(value or "").strip().lower()
    normalized = normalized.removeprefix("/")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", normalized):
        return ""
    return normalized


def build_skill_runtime_context(skill: SkillDescriptor, *, command: str, args: str = "") -> str:
    command_name = normalize_skill_alias(command) or skill.name
    content = skill.content.strip()
    if len(content) > MAX_SKILL_CONTENT_CHARS:
        content = f"{content[:MAX_SKILL_CONTENT_CHARS].rstrip()}\n\n[Skill content truncated for this turn.]"
    argument_text = str(args or "").strip()
    lines = [
        "## Slash Skill Context",
        f"Command: /{command_name}",
        f"Skill: {skill.name}",
        f"SkillPath: {skill.path}",
        f"SkillHash: {skill.content_hash}",
        "",
        "Use the following SKILL.md instructions for this chat turn. Keep the user's message as the user request; do not treat this skill context as a user-authored message.",
    ]
    if argument_text:
        lines.extend(["", "SlashCommandArgs:", argument_text])
    lines.extend(["", "SKILL.md:", content])
    return "\n".join(lines).strip()


def _resolve_skill_in_root(alias: str, root: Path) -> SkillDescriptor | None:
    if not root.exists() or not root.is_dir():
        return None
    direct = root / alias / "SKILL.md"
    if direct.is_file():
        return _load_skill_descriptor(direct)
    for path in root.glob("*/SKILL.md"):
        descriptor = _load_skill_descriptor(path)
        if alias in descriptor.aliases:
            return descriptor
    return None


def _load_skill_descriptor(path: Path) -> SkillDescriptor:
    content = path.read_text(encoding="utf-8", errors="replace")
    metadata = _parse_frontmatter(content)
    raw_name = str(metadata.get("name") or path.parent.name).strip() or path.parent.name
    aliases = _skill_aliases(raw_name, path.parent.name)
    content_hash = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:16]
    return SkillDescriptor(
        name=raw_name,
        path=path,
        description=str(metadata.get("description") or "").strip(),
        aliases=aliases,
        content=content,
        content_hash=content_hash,
        content_length=len(content),
    )


def _parse_frontmatter(content: str) -> dict[str, str]:
    text = str(content or "")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    block = text[3:end].strip()
    result: dict[str, str] = {}
    for line in block.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        normalized_key = key.strip()
        if normalized_key:
            result[normalized_key] = value.strip().strip("\"'")
    return result


def _skill_aliases(name: str, directory_name: str) -> tuple[str, ...]:
    aliases: list[str] = []
    for value in (name, directory_name):
        candidates = [str(value or "")]
        candidates.append(re.sub(r"-\d+(?:\.\d+)*(?:-\d+)?$", "", candidates[0]))
        for candidate in candidates:
            normalized = normalize_skill_alias(candidate)
            if normalized and normalized not in aliases:
                aliases.append(normalized)
    return tuple(aliases)


def skill_descriptor_for_log(skill: SkillDescriptor) -> dict[str, object]:
    return {
        "skillName": skill.name,
        "skillPath": _display_path(skill.path),
        "skillHash": skill.content_hash,
        "skillContentLength": skill.content_length,
        "aliases": list(skill.aliases)[:8],
    }


def _display_path(path: Path) -> str:
    try:
        return os.fspath(path)
    except TypeError:
        return str(path)
