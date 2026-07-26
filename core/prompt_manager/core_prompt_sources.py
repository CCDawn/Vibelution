# -*- coding: utf-8 -*-
"""Canonical COMMON / SOUL / AGENTS prompt sources.

The three files are the stable base for every Vibelution Agent.  This module
owns their order, source paths, and snapshot metadata so PromptManager and
session prompt snapshots cannot drift into parallel definitions.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CORE_PROMPT_SCHEMA_VERSION = 1
_FRONT_MATTER_RE = re.compile(r"^---\s*\n.*?\n---(\n)?", re.DOTALL)


@dataclass(frozen=True)
class CorePromptSpec:
    name: str
    relative_path: str
    priority: int
    description: str


CORE_PROMPT_SPECS = (
    CorePromptSpec(
        name="COMMON",
        relative_path="core/core_prompt/COMMON.md",
        priority=8,
        description="统一 Agent 通用认知与执行纪律",
    ),
    CorePromptSpec(
        name="SOUL",
        relative_path="core/core_prompt/SOUL.md",
        priority=10,
        description="稳定身份、价值倾向与自我进化动力",
    ),
    CorePromptSpec(
        name="AGENTS",
        relative_path="AGENTS.md",
        priority=12,
        description="项目级最高规则与规范路由中枢",
    ),
)
CORE_PROMPT_NAMES = tuple(spec.name for spec in CORE_PROMPT_SPECS)


class CorePromptSourceError(ValueError):
    """Raised when a required core prompt source is missing or empty."""

    def __init__(self, missing_names: list[str]):
        self.missing_names = tuple(missing_names)
        super().__init__(f"Missing required core prompt sources: {', '.join(self.missing_names)}")


def strip_prompt_front_matter(content: str) -> str:
    """Return model-facing Markdown without optional file metadata."""

    match = _FRONT_MATTER_RE.match(str(content or ""))
    return (content[match.end():] if match else content).strip()


def core_prompt_path(project_root: Path, spec: CorePromptSpec) -> Path:
    return Path(project_root) / Path(spec.relative_path)


def _content_hash(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def load_core_prompt_bundle(project_root: Path) -> dict[str, Any]:
    """Load the required core sources with bounded, content-free metadata."""

    sources: list[dict[str, Any]] = []
    missing_names: list[str] = []
    for spec in CORE_PROMPT_SPECS:
        path = core_prompt_path(project_root, spec)
        try:
            content = strip_prompt_front_matter(path.read_text(encoding="utf-8"))
        except OSError:
            content = ""
        if not content:
            missing_names.append(spec.name)
            continue
        sources.append(
            {
                "name": spec.name,
                "sourcePath": spec.relative_path,
                "content": content,
                "contentHash": _content_hash(content),
                "contentLength": len(content),
            }
        )
    if missing_names:
        raise CorePromptSourceError(missing_names)

    content = "\n\n".join(
        f"## Core Prompt: {source['name']}\n\n{source['content']}"
        for source in sources
    ).strip()
    return {
        "schemaVersion": CORE_PROMPT_SCHEMA_VERSION,
        "content": content,
        "contentHash": _content_hash(content),
        "contentLength": len(content),
        "sources": sources,
    }


def public_core_prompt_sources(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """Project content-free source metadata for logs and public snapshot DTOs."""

    return [
        {
            "name": str(source.get("name") or "").strip(),
            "sourcePath": str(source.get("sourcePath") or "").strip(),
            "contentHash": str(source.get("contentHash") or "").strip(),
            "contentLength": max(0, int(source.get("contentLength") or 0)),
        }
        for source in list(bundle.get("sources") or [])
        if isinstance(source, dict)
    ]


__all__ = [
    "CORE_PROMPT_NAMES",
    "CORE_PROMPT_SCHEMA_VERSION",
    "CORE_PROMPT_SPECS",
    "CorePromptSourceError",
    "core_prompt_path",
    "load_core_prompt_bundle",
    "public_core_prompt_sources",
    "strip_prompt_front_matter",
]
