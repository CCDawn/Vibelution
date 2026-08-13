"""Launcher-assigned names for branch instances and window titles.

Main stays ``main``. Other checkouts keep the full Git branch as
``branch+<name>`` so Launcher, tray, and status bar stay recognizable.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

MAIN_SHORT_NAME = "main"
BRANCH_NAME_PREFIX = "branch+"
RETIRED_NAME_PREFIX = "retired+"
WORKBENCH_TITLE_SUFFIX = "台"
LAUNCHER_TITLE_SUFFIX = "控"


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
    normalized_kind = str(kind or "").strip().lower()
    if normalized_kind == "main":
        return MAIN_SHORT_NAME
    label = _branch_label(branch)
    if not label or label.lower() == "detached":
        label = _branch_label(slug) or _branch_label(path_name) or "detached"
    if normalized_kind == "retired":
        return f"{RETIRED_NAME_PREFIX}{label}"
    return f"{BRANCH_NAME_PREFIX}{label}"


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


def _branch_label(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if text.startswith("refs/heads/"):
        text = text.removeprefix("refs/heads/")
    return text.strip("/")


def _slug_from_id(instance_id: str) -> str:
    if ":" not in instance_id:
        return instance_id
    return instance_id.split(":", 1)[1]


def _clean_short_name(value: str) -> str:
    return str(value or "").strip()
