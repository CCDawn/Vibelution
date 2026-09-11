# -*- coding: utf-8 -*-
"""Deterministic starter example for the empty composer.

Port of Claude Code's ``exampleCommands.ts``: pick up to five frequently
modified core files from git history (preferring the operator's own commits),
cache them per project for a week, and sample one short starter command. The
helper never opens a console window: all git access goes through the shared
no-console git runner.
"""

from __future__ import annotations

import random
import re
import threading
import time
from pathlib import Path
from typing import Iterable

from core.infrastructure.no_console_git import run_git

_EXAMPLE_TTL_SECONDS = 7 * 24 * 60 * 60
_FAILURE_TTL_SECONDS = 10 * 60
_GIT_TIMEOUT_SECONDS = 10.0
_MAX_HISTORY_COMMITS = 1000
_MAX_EXAMPLE_FILES = 5

# Patterns that mark a file as non-core (auto-generated, dependency or config),
# mirrored from the upstream deterministic filter (no LLM involved).
NON_CORE_PATTERNS = (
    re.compile(
        r"(?:^|/)(?:package-lock\.json|yarn\.lock|bun\.lock|bun\.lockb|pnpm-lock\.yaml|"
        r"Pipfile\.lock|poetry\.lock|Cargo\.lock|Gemfile\.lock|go\.sum|composer\.lock|uv\.lock)$"
    ),
    re.compile(r"\.generated\."),
    re.compile(r"(?:^|/)(?:dist|build|out|target|node_modules|\.next|__pycache__)/"),
    re.compile(r"\.(?:min\.js|min\.css|map|pyc|pyo)$"),
    re.compile(
        r"\.(?:json|ya?ml|toml|xml|ini|cfg|conf|env|lock|txt|md|mdx|rst|csv|log|svg)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|/)\.?(?:eslintrc|prettierrc|babelrc|editorconfig|gitignore|gitattributes|"
        r"dockerignore|npmrc)"
    ),
    re.compile(
        r"(?:^|/)(?:tsconfig|jsconfig|biome|vitest\.config|jest\.config|webpack\.config|"
        r"vite\.config|rollup\.config)\.[a-z]+$"
    ),
    re.compile(r"(?:^|/)\.(?:github|vscode|idea|claude)/"),
    re.compile(
        r"(?:^|/)(?:CHANGELOG|LICENSE|CONTRIBUTING|CODEOWNERS|README)(?:\.[a-z]+)?$",
        re.IGNORECASE,
    ),
)

_EXAMPLE_TEMPLATES = (
    "修复 lint 报错",
    "修复类型检查报错",
    "{file} 是怎么工作的？",
    "重构 {file}",
    "怎么记录错误日志？",
    "改一下 {file}，让它……",
    "给 {file} 写个测试",
    "创建一个工具函数，用于……",
)

_CACHE_LOCK = threading.RLock()
_CACHE: dict[str, tuple[float, str]] = {}


def _is_core_file(path: str) -> bool:
    normalized = str(path or "").replace("\\", "/")
    return not any(pattern.search(normalized) for pattern in NON_CORE_PATTERNS)


def pick_diverse_core_files(sorted_paths: Iterable[str], want: int) -> list[str]:
    """Pick up to ``want`` basenames, skipping non-core files and spreading dirs."""

    picked: list[str] = []
    seen_basenames: set[str] = set()
    dir_tally: dict[str, int] = {}
    paths = [str(item or "") for item in sorted_paths]
    for cap in range(1, want + 1):
        if len(picked) >= want:
            break
        for path in paths:
            if len(picked) >= want:
                break
            if not _is_core_file(path):
                continue
            last_sep = max(path.rfind("/"), path.rfind("\\"))
            base = path[last_sep + 1 :] if last_sep >= 0 else path
            if not base or base in seen_basenames:
                continue
            directory = path[:last_sep] if last_sep >= 0 else "."
            if dir_tally.get(directory, 0) >= cap:
                continue
            picked.append(base)
            seen_basenames.add(base)
            dir_tally[directory] = dir_tally.get(directory, 0) + 1
    return picked if len(picked) >= want else []


def _tally_name_only(stdout: str, counts: dict[str, int]) -> None:
    for line in str(stdout or "").splitlines():
        candidate = line.strip()
        if candidate:
            counts[candidate] = counts.get(candidate, 0) + 1


def _run_git_text(project_root: Path, args: list[str]) -> str:
    try:
        completed = run_git(args, cwd=project_root, timeout=_GIT_TIMEOUT_SECONDS)
    except Exception:
        return ""
    if completed.returncode != 0:
        return ""
    return str(completed.stdout or "")


def frequently_modified_core_files(project_root: Path) -> list[str]:
    """Return up to five frequently modified core file basenames (may be empty)."""

    log_args = [
        "log",
        "-n",
        str(_MAX_HISTORY_COMMITS),
        "--pretty=format:",
        "--name-only",
        "--diff-filter=M",
    ]
    counts: dict[str, int] = {}
    user_email = _run_git_text(project_root, ["config", "user.email"]).strip()
    if user_email:
        _tally_name_only(
            _run_git_text(project_root, [*log_args, f"--author={user_email}"]),
            counts,
        )
    if len(counts) < 10:
        _tally_name_only(_run_git_text(project_root, log_args), counts)
    if not counts:
        return []
    sorted_paths = [
        path for path, _count in sorted(counts.items(), key=lambda item: item[1], reverse=True)
    ]
    return pick_diverse_core_files(sorted_paths, _MAX_EXAMPLE_FILES)


def build_example_command(files: list[str]) -> str:
    template = random.choice(_EXAMPLE_TEMPLATES)
    file_name = random.choice(files) if files else ""
    if "{file}" in template:
        if not file_name:
            return "修复 lint 报错"
        return template.format(file=file_name)
    return template


def get_composer_example_command(project_root: Path | str | None = None) -> str | None:
    """Return one cached starter command for the project, or None when unavailable."""

    root = Path(project_root).resolve() if project_root else None
    if root is None:
        return None
    cache_key = str(root)
    now = time.time()
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached is not None:
            computed_at, command = cached
            ttl = _EXAMPLE_TTL_SECONDS if command else _FAILURE_TTL_SECONDS
            if now - computed_at <= ttl:
                return command or None
    command = ""
    if root.is_dir():
        files = frequently_modified_core_files(root)
        command = build_example_command(files)
    with _CACHE_LOCK:
        _CACHE[cache_key] = (now, command)
    return command or None


def reset_composer_example_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


__all__ = [
    "build_example_command",
    "frequently_modified_core_files",
    "get_composer_example_command",
    "pick_diverse_core_files",
    "reset_composer_example_cache",
]
