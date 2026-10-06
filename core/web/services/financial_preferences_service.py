"""Explicit user preferences over canonical Agent personal memory, no shadow store."""

from __future__ import annotations

import threading
from uuid import UUID

from core.web.services import agent_directory_service as directory
from core.web.services.financial_assistant_service import PROFILE, ROLE

_LOCK = threading.RLock()
_REF_PREFIX = "finance-preference:"


class FinancialPreferenceError(ValueError):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def _agent(agent_id: str) -> dict:
    agent = directory.get_agent(agent_id, include_archived=True)
    metadata = (agent or {}).get("metadata") or {}
    if (
        not agent
        or metadata.get("financialAssistantProfile") != PROFILE
        or agent.get("roleKey") != ROLE
    ):
        raise FinancialPreferenceError("当前金融助手不存在", 404)
    if (
        agent.get("status") != "active"
        or agent.get("primaryMode") != "general"
        or metadata.get("financialAssistantSetup") != "ready"
    ):
        raise FinancialPreferenceError("当前金融助手不可用", 409)
    return agent


def _rows(agent_id: str) -> list[dict]:
    return [
        row
        for row in directory.list_current_episodic_events(agent_id, limit=200)
        if row.get("kind") == "preference"
        and any(
            ref.get("type") == "item"
            and str(ref.get("id") or "").startswith(_REF_PREFIX)
            for ref in row.get("refs") or []
        )
    ]


def _project(row: dict) -> dict:
    return {"id": row["episodeId"], "text": row["text"], "createdAt": row["occurredAt"]}


def list_preferences(agent_id: str) -> dict:
    agent = _agent(agent_id)
    return {
        "agentId": agent_id,
        "memoryEnabled": (agent.get("memoryPolicy") or {}).get("enabled") is not False,
        "items": [_project(row) for row in _rows(agent_id)],
        "limit": 200,
    }


def save_preference(agent_id: str, text: str, client_request_id: str) -> dict:
    text = str(text).strip()
    if (
        not text
        or len(text) > 1000
        or len(text.splitlines()) > 20
        or any(ord(char) < 32 and char not in "\n\t\r" for char in text)
    ):
        raise FinancialPreferenceError("偏好需为1至1000字，最多20行")
    try:
        request_id = str(UUID(client_request_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise FinancialPreferenceError("保存请求标识无效") from exc
    ref_id = _REF_PREFIX + request_id
    with _LOCK:
        agent = _agent(agent_id)
        if (agent.get("memoryPolicy") or {}).get("enabled") is False:
            raise FinancialPreferenceError("此助手的个人记忆已关闭", 409)
        for row in _rows(agent_id):
            if any(
                ref.get("type") == "item" and ref.get("id") == ref_id
                for ref in row.get("refs") or []
            ):
                if row["text"] != text:
                    raise FinancialPreferenceError("此保存标识已用于另一条偏好", 409)
                return _project(row)
        try:
            row = directory.append_episodic_event(
                agent_id,
                kind="preference",
                text=text,
                refs=[{"type": "item", "id": ref_id}],
            )
        except directory.AgentDirectoryError as exc:
            raise FinancialPreferenceError(str(exc), 409) from exc
        return _project(row)


def remove_preference(agent_id: str, preference_id: str) -> dict:
    with _LOCK:
        _agent(agent_id)
        if not any(row.get("episodeId") == preference_id for row in _rows(agent_id)):
            raise FinancialPreferenceError("偏好不存在或不属于当前助手", 404)
        try:
            directory.supersede_episodic_event(agent_id, preference_id)
        except directory.AgentDirectoryError as exc:
            raise FinancialPreferenceError(str(exc), 409) from exc
        return {"id": preference_id, "removed": True}


def get_workspace_settings(agent_id: str) -> dict:
    from .financial_preferences.workspace import get_workspace

    return get_workspace(agent_id)


def update_workspace_settings(agent_id: str, expected_revision: int, patch: dict) -> dict:
    from .financial_preferences.workspace import update_workspace

    return update_workspace(agent_id, expected_revision, patch)
