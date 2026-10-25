"""Compatibility wrapper for the approved PA tool; identity stays native."""
from __future__ import annotations

from core.web.services import agent_directory_service as directory
from core.web.services import (
    team_template_service,  # noqa: F401 -- legacy fixture/plugin module seam
)
from core.web.services.team_workflow import one_shot

_ROLES = one_shot._ROLES
_resolve_team_id = one_shot._resolve_team_id


def _runtime() -> dict:
    runtime = directory.current_agent_runtime()
    if any(not isinstance(runtime.get(key), str) or not runtime[key].strip() or len(runtime[key]) > 160
           for key in ("agentId", "sessionId")):
        raise ValueError("缺少有效的个人助理会话身份。")
    return runtime


def team_run(name: str, goal: str, request_id: str, template_id: str = "dev-team") -> dict:
    try:
        runtime = _runtime()
    except Exception:  # noqa: BLE001 -- preserve bounded legacy errors and unknown native outcomes
        return one_shot._failure("invalid_input", "请提供有效会话身份、团队名称、目标、request_id 和内置 dev-team 模板。")
    return one_shot.run_legacy(runtime, name, goal, request_id, template_id)


def team_run_status(team_id: str | int = "", run_id: str = "", wait_seconds: int = 0) -> dict:
    try:
        runtime = _runtime()
    except Exception:  # noqa: BLE001 -- preserve bounded legacy errors and unknown native outcomes
        return one_shot._failure("status_unavailable", "无法读取该团队运行，请核对身份与对象标识。")
    return one_shot.status_legacy(runtime, team_id, run_id, wait_seconds)
