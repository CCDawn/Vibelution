"""Slash command parsing for chat turns."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from core.chat.skill_registry import SkillDescriptor, resolve_skill


@dataclass(frozen=True)
class SkillSlashCommand:
    command: str
    args: str
    skill: SkillDescriptor


def parse_skill_slash_command(content: str, *, skill_roots: Iterable[Path] | None = None) -> SkillSlashCommand | None:
    text = str(content or "").lstrip()
    if not text.startswith("/"):
        return None
    parts = text.split(maxsplit=1)
    first = parts[0] if parts else ""
    rest = parts[1] if len(parts) > 1 else ""
    command = first[1:].strip()
    if not command:
        return None
    skill = resolve_skill(command, roots=skill_roots)
    if skill is None:
        return None
    return SkillSlashCommand(command=command, args=rest.strip(), skill=skill)
