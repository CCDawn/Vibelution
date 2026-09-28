"""e2e arrange 造数：用实例 API 建会话 / Agent / 提交消息，避免为准备数据走 UI。

端点查证（core/web/routes，2026-09-25）：
- ``POST /api/sessions``（SessionCreatePayload: agentId/title）→ SessionCatalogItem（``id``）；
- ``POST /api/sessions/{id}/messages``（SessionMessagePayload: content 必填其余默认）→ 202；
- ``POST /api/agents``（AgentCreatePayload: displayName 必填，其余默认）→ AgentDocument；
- ``GET /api/agents`` / ``GET /api/agents/{id}`` 读回断言用。
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from tests.e2e.helpers.api_write import post_json
from tests.e2e.helpers.instance_registry import InstanceRegistryError, fetch_json


def create_session(port: int, title: str = "", agent_id: str = "") -> str:
    """建一条 chat 会话，返回 sessionId（POST /api/sessions）。"""
    payload = post_json(port, "/api/sessions", {"agentId": agent_id, "title": title})
    session_id = str(payload.get("id") or "").strip()
    if not session_id:
        raise InstanceRegistryError(f"POST /api/sessions 未返回会话 id: {str(payload)[:200]}")
    return session_id


def submit_user_message(port: int, session_id: str, content: str) -> dict[str, Any]:
    """向会话提交一条用户消息（POST /api/sessions/{id}/messages，202 即成功）。"""
    return post_json(
        port,
        f"/api/sessions/{session_id}/messages",
        {
            "content": content,
            "clientSubmissionId": f"e2e-{uuid.uuid4().hex[:12]}",
        },
        timeout_seconds=30.0,
    )


def list_agents(port: int) -> list[dict[str, Any]]:
    """读 Agent 目录（GET /api/agents）。"""
    payload = fetch_json(port, "/api/agents")
    return payload if isinstance(payload, list) else []


def find_agent_by_display_name(port: int, display_name: str) -> dict[str, Any]:
    """按 displayName 精确找 Agent；找不到抛错（含当前目录摘要便于排查）。"""
    for agent in list_agents(port):
        if str(agent.get("displayName") or "") == display_name:
            return agent
    known = ", ".join(
        str(item.get("displayName") or item.get("agentId") or "?") for item in list_agents(port)[:10]
    )
    raise InstanceRegistryError(f"Agent 目录中没有 displayName={display_name!r} 的条目（现有: {known}）")


def get_agent(port: int, agent_id: str) -> dict[str, Any]:
    """读单个 Agent 文档（GET /api/agents/{id}，404 抛错）。"""
    return fetch_json(port, f"/api/agents/{agent_id}")


def create_agent(port: int, display_name: str, *, timeout_seconds: float = 30.0) -> dict[str, Any]:
    """用最小 payload 建一个 Agent（POST /api/agents，displayName 即可）。"""
    agent = post_json(port, "/api/agents", {"displayName": display_name}, timeout_seconds=timeout_seconds)
    if not str(agent.get("agentId") or "").strip():
        raise InstanceRegistryError(f"POST /api/agents 未返回 agentId: {str(agent)[:200]}")
    return agent


_PREFERRED_PROVIDERS = (
    "command_code",
    "dashscope_main",
    "relay_openai",
    "openai_main",
    "deepseek_main",
    "siliconflow_main",
    "minimax_main",
)


def find_working_providers(port: int, *, max_tries: int = 8) -> list[tuple[str, str]]:
    """用后端探测接口找出当前真实可用的 (providerId, modelId) 列表。

    向导的模型步骤必须通过真实连通探测才能继续；直接逐个调
    ``POST /api/config/test-llm``（与 UI 探测同一后端实现）提前筛出可用项，
    避免在 UI 里逐个服务商试错。主流公网 API 优先；找不到返回空列表。
    """
    workspace = fetch_json(port, "/api/agents/config-workspace?includeRuntime=false")
    candidates: dict[str, dict[str, Any]] = {}
    for choice in workspace.get("agentModelChoices") or []:
        provider_id = str(choice.get("providerId") or "")
        lowered = provider_id.lower()
        if not choice.get("apiKeyConfigured") or "local" in lowered or "lan" in lowered:
            continue
        if provider_id not in candidates:
            candidates[provider_id] = choice
    ordered = sorted(
        candidates.items(),
        key=lambda item: (
            0 if item[0] in _PREFERRED_PROVIDERS else 1,
            _PREFERRED_PROVIDERS.index(item[0]) if item[0] in _PREFERRED_PROVIDERS else 99,
            item[0],
        ),
    )
    verified: list[tuple[str, str]] = []
    for provider_id, choice in ordered[:max_tries]:
        try:
            result = post_json(
                port,
                "/api/config/test-llm",
                {"publicConfig": {}, "modelId": choice.get("modelId"), "capability": "text"},
                timeout_seconds=60.0,
            )
        except InstanceRegistryError:
            continue
        if result.get("ok") is True:
            verified.append((provider_id, str(choice.get("modelId") or "")))
    return verified


def wait_for_agent_memory_enabled(
    port: int,
    agent_id: str,
    *,
    expected: bool,
    timeout_seconds: float = 10.0,
) -> bool | None:
    """轮询 GET /api/agents/{id} 直到 memoryPolicy.enabled 达到期望值。

    保存链路是异步落盘（UI 面板先收到 2xx 再刷新 workspace），给一个短轮询窗
    避免刚保存就读到旧值。超时返回最后观测值（可能是 None = 无该字段），由
    调用方断言失败，不静默放行。
    """
    deadline = time.monotonic() + timeout_seconds
    enabled: bool | None = None
    while time.monotonic() < deadline:
        agent = get_agent(port, agent_id)
        policy = agent.get("memoryPolicy") or {}
        value = policy.get("enabled")
        enabled = value if isinstance(value, bool) else None
        if enabled is expected:
            return enabled
        time.sleep(0.5)
    return enabled


def stop_session_turn(port: int, session_id: str) -> None:
    """尽力终止会话在飞 turn（POST /api/sessions/{id}/stop），收尾清理用。

    后端契约：stop 必须带 ``turnId``（SessionStopPayload，min_length=1），先
    GET /api/sessions/{id} 读 ``activeTurnId``，无在飞 turn（字段为空）即无事
    可做。请求失败只吞掉（409/404 竞态），避免用例收尾误报。
    """
    try:
        detail = fetch_json(port, f"/api/sessions/{session_id}")
        turn_id = str(detail.get("activeTurnId") or "").strip()
        if not turn_id:
            return
        post_json(port, f"/api/sessions/{session_id}/stop", {"turnId": turn_id}, timeout_seconds=15.0)
    except InstanceRegistryError:
        return
