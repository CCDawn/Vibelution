"""Launcher-assigned short names for branch instances and window titles.

Main stays 「主」. Other checkouts take the last branch/path segment, drop
noise tokens, and keep the longest remaining token so the taskbar still
distinguishes windows after Windows elides the rest.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

MAIN_SHORT_NAME = "主"
WORKBENCH_TITLE_SUFFIX = "台"
LAUNCHER_TITLE_SUFFIX = "控"
MAX_SHORT_NAME_LEN = 12
_SEGMENT_SPLIT = re.compile(r"[-_./]+")
_STOP_TOKENS = frozenset(
    {
        "slot",
        "s1",
        "s1s8",
        "s1s8b",
        "codex",
        "feat",
        "fix",
        "test",
        "impl",
        "implementation",
        "registry",
        "runtime",
        "worktree",
        "electron",
        "desktop",
        "launcher",
        "web",
        "src",
        "app",
        "vibelution",
    }
)


def workbench_window_title(short_name: str) -> str:
    return f"{_clean_short_name(short_name) or MAIN_SHORT_NAME} {WORKBENCH_TITLE_SUFFIX}"


def launcher_window_title(short_name: str) -> str:
    return f"{_clean_short_name(short_name) or MAIN_SHORT_NAME} {LAUNCHER_TITLE_SUFFIX}"


def instance_short_name_base(
    *,
    kind: str = "",
    branch: str = "",
    slug: str = "",
    path_name: str = "",
) -> str:
    if str(kind or "").strip().lower() == "main":
        return MAIN_SHORT_NAME
    raw = _last_segment(branch) or _last_segment(slug) or _last_segment(path_name)
    tokens = [token for token in _SEGMENT_SPLIT.split(raw.lower()) if token]
    kept = [token for token in tokens if token not in _STOP_TOKENS and len(token) > 1]
    if kept:
        longest = max(len(token) for token in kept)
        # Tie-break toward the last token so "close-fail-open-fetch" prefers fetch.
        chosen = next(token for token in reversed(kept) if len(token) == longest)
        return chosen[:MAX_SHORT_NAME_LEN]
    if raw:
        return raw[:MAX_SHORT_NAME_LEN]
    return "branch"


def assign_instance_display_names(items: Iterable[dict[str, Any]]) -> None:
    used: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").replace("\\", "/").rstrip("/")
        path_name = path.rsplit("/", 1)[-1] if path else ""
        base = instance_short_name_base(
            kind=str(item.get("kind") or ""),
            branch=str(item.get("branch") or ""),
            slug=_slug_from_id(str(item.get("id") or "")),
            path_name=path_name,
        )
        name = base
        suffix = 2
        while name in used:
            name = f"{base}-{suffix}"
            suffix += 1
        used.add(name)
        item["shortName"] = name
        item["workbenchTitle"] = workbench_window_title(name)
        item["launcherTitle"] = launcher_window_title(name)


def current_instance_display(items: Iterable[dict[str, Any]]) -> dict[str, str]:
    current = next((item for item in items if isinstance(item, dict) and item.get("current")), None)
    if current and current.get("shortName"):
        return {
            "shortName": str(current["shortName"]),
            "workbenchTitle": str(current.get("workbenchTitle") or workbench_window_title(str(current["shortName"]))),
            "launcherTitle": str(current.get("launcherTitle") or launcher_window_title(str(current["shortName"]))),
        }
    return {
        "shortName": MAIN_SHORT_NAME,
        "workbenchTitle": workbench_window_title(MAIN_SHORT_NAME),
        "launcherTitle": launcher_window_title(MAIN_SHORT_NAME),
    }


def _last_segment(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return ""
    return text.rsplit("/", 1)[-1]


def _slug_from_id(instance_id: str) -> str:
    if ":" not in instance_id:
        return instance_id
    return instance_id.split(":", 1)[1]


def _clean_short_name(value: str) -> str:
    return str(value or "").strip()
