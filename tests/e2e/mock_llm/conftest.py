# -*- coding: utf-8 -*-
"""mock_llm 车道挂载：会话级 aimock + provider 注册/注销 + 每用例 journal 重置。

依赖父级 ``tests/e2e/conftest.py`` 的 ``e2e_instance``（Launcher 分支实例）与
``page`` fixture，本目录不重复起实例、不修改父级文件。

teardown 顺序（pytest 按实例化逆序执行）：先注销 provider 并核对注册前快照
（此时实例仍在服务），再停 aimock 进程并断言零残留；之后父级 fixture 才停实例。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import time

from tests.e2e.mock_llm import aimock_runtime, config_center

SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"
SCENARIOS_RUNNER = SCENARIOS_DIR / "runner.mjs"
SCENARIOS_FIXTURES_DIR = SCENARIOS_DIR / "fixtures"


@dataclass
class MockLlmHandle:
    """会话级 mock LLM 句柄：实例端口 + aimock 服务器 + 配置中心会话。"""

    instance_port: int
    server: aimock_runtime.AimockServer
    center: config_center.ConfigCenterSession

    @property
    def provider_base_url(self) -> str:
        # 产品 provider base_url 必须指向 /v1（models 探活口径，见 config_center）。
        return f"{self.server.base_url}/v1"

    # -- Agent arrange --------------------------------------------------------

    def create_agent(self, model_key: str, display_name: str) -> dict:
        """经实例 API 建 Agent，并把 dialogue 槽绑到 e2e-mock/<model_key>。"""
        from tests.e2e.helpers.instance_registry import fetch_json

        def _post(path: str, payload: dict) -> dict:
            from tests.e2e.mock_llm.config_center import (
                ConfigCenterError,
                _api_request,
            )

            # 冷实例首个建 Agent 请求实测可能 >30s（run9 读超时），放宽超时并
            # 对瞬态网络错误（超时/连接失败，_api_request 对不可达抛
            # ConfigCenterError）限次重试。
            last_exc: Exception | None = None
            status: int | None = None
            result: Any = None
            for _attempt in range(3):
                try:
                    status, result = _api_request(
                        self.instance_port, "POST", path, payload, timeout_seconds=90.0
                    )
                    break
                except (TimeoutError, OSError, ConfigCenterError) as exc:
                    last_exc = exc
                    time.sleep(2.0)
            else:
                raise RuntimeError(f"POST {path} 连续失败（瞬态重试耗尽）: {last_exc}")
            if status is None or status < 200 or status >= 300 or not isinstance(result, dict):
                raise RuntimeError(f"POST {path} 失败: HTTP {status} {str(result)[:300]}")
            return result

        agent = _post(
            "/api/agents",
            {
                "displayName": display_name,
                # 工作会话（primaryMode=chat）只要求 功能名/对话模型/使用位置/提示词。
                "primaryMode": "chat",
                "promptTemplateId": self._first_prompt_template_id(),
                "llmBindings": {
                    "dialogue": {"modelId": config_center.model_ref(model_key)},
                },
            },
        )
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id:
            raise RuntimeError(f"agent 创建响应缺 agentId: {str(agent)[:300]}")
        session_id = str(agent.get("directSessionId") or "").strip()
        if not session_id:
            catalog = fetch_json(self.instance_port, f"/api/sessions/query?agentId={agent_id}")
            items = catalog.get("items") or catalog.get("sessions") or []
            if items:
                session_id = str(items[0].get("id") or "")
        if not session_id:
            raise RuntimeError(f"agent {agent_id} 未找到关联会话")
        return {"agentId": agent_id, "sessionId": session_id}

    def _first_prompt_template_id(self) -> str:
        from tests.e2e.helpers.instance_registry import fetch_json

        catalog = fetch_json(self.instance_port, "/api/prompt-templates")
        templates = catalog.get("templates") or []
        for item in templates:
            template_id = str((item or {}).get("templateId") or "").strip()
            if template_id:
                return template_id
        raise RuntimeError(f"实例无可用提示词模板，无法创建 Agent: {str(catalog)[:200]}")

    def delete_agent(self, agent_id: str, *, timeout_seconds: float = 60.0) -> None:
        """teardown 用：归档 + purge 测试 Agent（硬删，连带会话），让 provider 注销
        不被 agent llmBindings 的 live model reference 挡住。

        归档可能因在飞 turn 收尾返回 409/422，带限次重试；重试耗尽才放弃并打印
        （后续 restore 的 409 详情会带上 agent 证据）。
        """
        from tests.e2e.mock_llm.config_center import (
            ConfigCenterError,
            _api_request,
        )

        def _delete(path: str) -> tuple[int, Any]:
            # 拆机请求也可能撞上瞬态超时/不可达（实例忙于收尾 turn）；异常按未成功
            # 处理，交给外层重试循环，不让 teardown 直接炸。
            try:
                return _api_request(
                    self.instance_port, "DELETE", path, timeout_seconds=90.0
                )
            except (TimeoutError, OSError, ConfigCenterError) as exc:
                print(f"[mock_llm] DELETE {path} 瞬态失败，重试: {exc}")
                return 0, None

        def _agent_present() -> bool:
            # 实测（run19）：archive/purge 都可能 2xx 而 agent 仍在 registry
            # （带 live llmBinding 引用挡住 provider 注销），所以删除后必须回读
            # 核对，不能只看单次响应码。
            try:
                status, result = _api_request(
                    self.instance_port,
                    "GET",
                    "/api/agents?includeArchived=true",
                    timeout_seconds=30.0,
                )
            except (TimeoutError, OSError, ConfigCenterError):
                return True  # 读不到就当还在，继续重试整链
            if status != 200 or not isinstance(result, list):
                return True
            return any(
                str((item or {}).get("agentId") or "") == agent_id for item in result
            )

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            _delete(f"/api/agents/{agent_id}")  # 归档（404 视为已完成）
            _delete(f"/api/agents/{agent_id}/purge")  # 硬删（404 视为已完成）
            if not _agent_present():
                return
            time.sleep(2.0)
        print(
            f"[mock_llm] 测试 Agent 删除未闭环（归档+purge 后仍在 registry，"
            f"live 引用会挡 provider 注销）: {agent_id}"
        )


@pytest.fixture(scope="session")
def mock_llm(e2e_instance):
    """起 aimock runner → 注册 e2e-mock provider → 测试 → 注销恢复 → 停进程（零残留）。

    用 runner（程序化剧本）而非 ``--fixtures``：产品主聊天调用的末条 user 消息是
    Turn Status Bar 遥测尾巴，JSON 剧本的 userMessage（末条匹配）路由不到主调用；
    runner 在完整 messages 上找标记（见 scenarios/runner.mjs 头注释）。
    """
    server = aimock_runtime.start_aimock(SCENARIOS_FIXTURES_DIR, script=SCENARIOS_RUNNER)
    center = config_center.ConfigCenterSession(e2e_instance.port, base_url=server.base_url)
    try:
        center.snapshot()
        center.register()
    except Exception:
        # 注册失败不泄漏 aimock 进程（apply 失败的现场在异常信息里保出）。
        try:
            server.stop()
            server.assert_stopped()
        except Exception as stop_exc:  # noqa: BLE001 - 不掩盖注册失败原始错误
            print(f"[mock_llm] 注册失败后的 aimock 补停未闭环: {stop_exc}")
        raise
    handle = MockLlmHandle(instance_port=e2e_instance.port, server=server, center=center)
    print(f"[mock_llm] 会话就绪: aimock={server.base_url} provider_base_url={handle.provider_base_url}")
    yield handle
    teardown_error: Exception | None = None
    try:
        center.restore_and_verify()
    except Exception as exc:  # noqa: BLE001 - 恢复失败要报告并保现场
        teardown_error = exc
        print(f"[mock_llm] provider 注销/恢复失败（保现场）: {exc}")
    try:
        server.stop()
        server.assert_stopped()
    except Exception as exc:  # noqa: BLE001 - 进程零残留是硬指标
        print(f"[mock_llm] aimock 拆机异常: {exc}")
        if teardown_error is None:
            teardown_error = exc
    if teardown_error is not None:
        raise teardown_error


@pytest.fixture(autouse=True)
def reset_mock_llm_journal(mock_llm: MockLlmHandle):
    """每条用例前清空 journal（保留 fixture 与 sequence 计数，见 aimock_runtime 注释）。"""
    mock_llm.server.reset_journal()
    yield
