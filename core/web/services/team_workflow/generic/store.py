"""Atomic snapshots in the existing active/sandbox Team namespace."""
from __future__ import annotations

import copy
import re
from contextlib import contextmanager
from pathlib import Path

from core.infrastructure.file_lock import cross_process_file_lock
from core.web.services.team import team_store
from core.web.services import team_service


class WorkflowError(ValueError):
    pass


class NotFound(WorkflowError):
    pass


class Conflict(WorkflowError):
    pass


def token(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", value):
        raise WorkflowError("标识无效。")
    return value


def team(team_id: str) -> dict:
    token(team_id)
    # Read the canonical roster without CRUD's repair/bootstrap side effects.
    with team_service._TEAM_LOCK:
        item = team_store._find_team(team_store._load_index(), team_id)
        if item is None:
            raise NotFound("团队不存在。")
        return copy.deepcopy(item)


def root(team_id: str) -> Path:
    team(team_id)
    base = team_store._teams_root().resolve()
    result = (base / token(team_id) / "generic-workflows").resolve()
    if not result.is_relative_to(base):
        raise WorkflowError("团队存储路径无效。")
    return result


def path(team_id: str, kind: str, item_id: str) -> Path:
    if kind not in {"flows", "runs"}:
        raise WorkflowError("存储类型无效。")
    base = root(team_id)
    result = (base / kind / f"{token(item_id)}.json").resolve()
    if not result.is_relative_to(base):
        raise WorkflowError("流程存储路径无效。")
    return result


def read(target: Path) -> dict:
    if not target.exists():
        raise NotFound("流程或运行记录不存在。")
    return team_store._read_json(target)


def write(target: Path, record: dict) -> None:
    team_store._write_json(target, record)


@contextmanager
def locked(target: Path):
    try:
        with cross_process_file_lock(target, timeout=5):
            yield
    except TimeoutError as exc:
        raise Conflict("流程正在更新，请刷新后重试。") from exc


def check_revision(record: dict, expected: int) -> None:
    if int(record.get("revision") or 0) != expected:
        raise Conflict("版本已变化，请刷新后重试。")


def records(team_id: str, kind: str, *, limit: int = 100) -> list[dict]:
    folder = root(team_id) / kind
    paths = sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [read(path(team_id, kind, item.stem)) for item in paths[:limit]]
