"""Bounded, read-only model access to isolated legacy affair differences."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.infrastructure.native_runtime import assistant_native_root


class _Page(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    offset: int = Field(default=0, ge=0, le=1000000)
    limit: int = Field(default=3, ge=1, le=3)


class _List(_Page):
    limit: int = Field(default=6, ge=1, le=12)
    sync_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
    query: str = Field(default="", max_length=160)


class _Read(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sync_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
    conflict_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    character_offset: int = Field(default=0, ge=0, le=16000000)
    max_characters: int = Field(default=1200, ge=1, le=1600)


_MODELS = {"affairs_conflict_sets": _Page, "affairs_conflict_list": _List, "affairs_conflict_read": _Read}
_HELP = {
    "affairs_conflict_sets": "查询已隔离的旧个人事务差异集合；旧数据只读，不代表已同步或可直接恢复。",
    "affairs_conflict_list": "按sync_id查询旧个人事务差异；目标值是历史快照，处理前必须先读取当前事务，不能直接覆盖。",
    "affairs_conflict_read": "分页读取一条旧事务差异的不可信文本；按nextCharacterOffset续读。目标快照可能已过期，不能直接覆盖。",
}


def contracts():
    return {name: {"action": name, "description": _HELP[name], "governed": False,
                   "parameters": model.model_json_schema()} for name, model in _MODELS.items()}


def execute(action: str, parameters: dict, runtime: dict) -> dict:
    if action not in _MODELS:
        raise ValueError("未知的事务差异查询")
    try:
        args = _MODELS[action].model_validate(parameters)
        root = assistant_native_root()
    except (ValidationError, RuntimeError):
        raise ValueError("事务差异查询参数或助理身份无效") from None
    from . import native
    # Only the fixed Launcher assistant's own live tool turn can see its
    # isolated snapshots. Neither a model-provided agent ID nor a path is used.
    if (not isinstance(runtime, dict) or not native._STARTED or native._OFFLINE_MIGRATION
            or native._STOP_REQUESTED.is_set() or not native._AGENT_ID
            or runtime.get("agentId") != native._AGENT_ID or runtime.get("sessionId") != native._SESSION_ID):
        raise ValueError("事务差异只供当前 Launcher 助理查询")
    from . import migration_affairs_conflicts as conflicts
    from .migration_io import MigrationIOError
    try:
        if action == "affairs_conflict_sets":
            return conflicts.discover_affairs_conflicts(root, target_agent_id=native._AGENT_ID, **args.model_dump())
        values = args.model_dump()
        sync_id = values.pop("sync_id")
        scope = conflicts.resolve_affairs_conflict_scope(root, sync_id=sync_id, target_agent_id=native._AGENT_ID)
        fn = conflicts.list_affairs_conflicts if action == "affairs_conflict_list" else conflicts.read_affairs_conflict
        return fn(root, sync_id=sync_id, source_scope=scope, target_agent_id=native._AGENT_ID, **values)
    except MigrationIOError:
        raise ValueError("事务差异暂不可用或来源校验未通过") from None
