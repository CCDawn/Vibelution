# -*- coding: utf-8 -*-
"""Deterministic starter examples for the empty composer.

Port of Claude Code's ``exampleCommands.ts``: pick up to five frequently
modified core files from git history (preferring the operator's own commits),
cache them per project for a week, and sample short starter commands for the
empty-composer cards. The helper never opens a console window: all git access
goes through the shared no-console git runner.
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

# (heading, template) pairs: the heading labels the starter card, the template
# renders the command prefilled into the composer.
_EXAMPLE_STARTERS: tuple[tuple[str, str], ...] = (
    ("修复问题", "修复 lint 报错"),
    ("修复问题", "修复类型检查报错"),
    ("理解代码", "{file} 是怎么工作的？"),
    ("重构改进", "重构 {file}"),
    ("工程实践", "怎么记录错误日志？"),
    ("迭代开发", "改一下 {file}，让它……"),
    ("编写测试", "给 {file} 写个测试"),
    ("从头创建", "创建一个工具函数，用于……"),
)

_DEFAULT_STARTER_COUNT = 3

_CACHE_LOCK = threading.RLock()
_CACHE: dict[str, tuple[float, list[dict[str, str]]]] = {}


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


def _render_starter_command(template: str, file_name: str) -> str:
    if "{file}" not in template:
        return template
    if not file_name:
        return "修复 lint 报错"
    return template.format(file=file_name)


def build_example_command(files: list[str]) -> str:
    _heading, template = random.choice(_EXAMPLE_STARTERS)
    file_name = random.choice(files) if files else ""
    return _render_starter_command(template, file_name)


def build_example_starters(
    files: list[str],
    want: int = _DEFAULT_STARTER_COUNT,
) -> list[dict[str, str]]:
    """Build up to ``want`` distinct heading+command starter cards.

    Spreads headings first (no two cards with the same label while fresh ones
    remain) and never reuses a file or an identical command across cards.
    """

    if want <= 0:
        return []
    templates = list(_EXAMPLE_STARTERS)
    random.shuffle(templates)
    file_pool = [name for name in (str(item or "").strip() for item in files) if name]
    random.shuffle(file_pool)
    starters: list[dict[str, str]] = []
    used_files: set[str] = set()
    used_commands: set[str] = set()
    # Pass 1 prefers unique headings; pass 2 relaxes the cap so ``want`` is met.
    for heading_cap in (1, max(1, want)):
        if len(starters) >= want:
            break
        heading_tally: dict[str, int] = {}
        file_index = 0
        for heading, template in templates:
            if len(starters) >= want:
                break
            if heading_tally.get(heading, 0) >= heading_cap:
                continue
            file_name = ""
            if "{file}" in template:
                while file_index < len(file_pool):
                    candidate = file_pool[file_index]
                    file_index += 1
                    if candidate not in used_files:
                        file_name = candidate
                        break
                if not file_name:
                    # No fresh file left for a file-backed template; skip it so
                    # cards never repeat the same filler command.
                    continue
            command = _render_starter_command(template, file_name)
            if command in used_commands:
                continue
            starters.append({"heading": heading, "command": command})
            used_commands.add(command)
            if file_name:
                used_files.add(file_name)
            heading_tally[heading] = heading_tally.get(heading, 0) + 1
    return starters


def get_composer_starter_commands(
    project_root: Path | str | None = None,
    want: int = _DEFAULT_STARTER_COUNT,
) -> list[dict[str, str]]:
    """Return cached starter cards for the project (may be empty)."""

    root = Path(project_root).resolve() if project_root else None
    if root is None:
        return []
    cache_key = str(root)
    now = time.time()
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached is not None:
            computed_at, starters = cached
            ttl = _EXAMPLE_TTL_SECONDS if starters else _FAILURE_TTL_SECONDS
            if now - computed_at <= ttl:
                return starters[: max(0, want)]
    starters: list[dict[str, str]] = []
    if root.is_dir():
        files = frequently_modified_core_files(root)
        starters = build_example_starters(files)
    with _CACHE_LOCK:
        _CACHE[cache_key] = (now, starters)
    return starters[: max(0, want)]


def get_composer_example_command(project_root: Path | str | None = None) -> str | None:
    """Return one cached starter command for the project, or None when unavailable."""

    starters = get_composer_starter_commands(project_root, want=1)
    command = starters[0]["command"] if starters else ""
    return command or None


def reset_composer_example_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


__all__ = [
    "build_example_command",
    "build_example_starters",
    "frequently_modified_core_files",
    "get_composer_example_command",
    "get_composer_starter_commands",
    "pick_diverse_core_files",
    "reset_composer_example_cache",
]
