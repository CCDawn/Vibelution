# -*- coding: utf-8 -*-
"""e2e P1：SSE 断流与失败轮的用户可见性（钉 0916/0917 修复的 UX，此前零 e2e 守卫）。

钉住的产品契约（真实分支实例 + aimock + headless chromium）：

- 断流可见（1010ec9cf 部分流发射后的传输失败重试 + 53c4418aa 失败呈现对齐）：
  LLM 上游流中途被截断（本车道剧本 1 ``E2E-SFV-DROP-V1``：truncateAfterChunks=3
  + tps=8，每次调用都截断）后，产品不允许整轮静默吞掉，可见性证据按强弱分级：
  1. 自动重试过程投影：active-turn 状态条 ``data-active-turn-stage`` 出现
     retrying/model_retry，第 3 次尝试起 ``data-active-turn-retry-attempt`` 可见
     （conversationActiveTurnStatusPresentation.MIN_VISIBLE_API_RETRY_ATTEMPT=3）；
  2. 最终失败态投影：时间线内联失败卡 ``div.turnErrorNotice[role="status"]``
     （53c4418aa 后的低位失败行）与/或实时横幅 ``div.turnError[role="status"]``。
  剧本每次调用都截断——产品自动重试也无法成功。硬闸门是第 1 级（重试投影，
  干净实测必现 model_retry）；终态失败可见性在观察窗（360s，实测自愈链路分钟
  级）内收敛时追加断言；窗内不收敛则降级为用户终止（composer「终止」按钮）
  收口 + 会话仍可用，并把「自愈链路过长」如实写进汇报。
- 失败轮可重试（09b53abfa per-turn retry + 53c4418aa）：不可重试 4xx（剧本 2
  ``E2E-SFV-400-V1`` 返回真参数错误 "Invalid parameter: messages"，
  error_classification 的 bad_request 分支 fail-closed，4f7c0a490 的网关瞬态
  400 短语不命中）让 turn 快速失败；时间线出现失败态且提供「重试此轮」入口
  （hover 行内 ``data-conversation-hover-actions`` 容器 + 按钮 aria-label 结构
  锚，非文案模糊匹配）；点重试走 branch-aware regenerate 管线重跑原 user 消息，
  剧本第 2 次尝试返回成功正文，新轮收口——journal 见 400→200 两次主调用。

车道自持性（2026-09-26 实测教训，与共享 mock_llm 车道的关键差异）：

- mock_llm 车道的 provider 注册落在**共享 operator config**，provider id 固定
  ``e2e-mock``。同机并行的另一 e2e 会话会在 snapshot 自愈/teardown 时把该
  provider 注销，双向互踩（本任务 run2/3/5 三次失败均源于此）。本文件用自己的
  runner（``scenarios/sfv_runner.mjs``）+ 独立 provider id（``e2e-mock-sfv``），
  与并行车道完全解耦；config_center 仅复用其 HTTP/entry 形状（只读 import）。
- 模块级同名 fixture ``reset_mock_llm_journal`` 影蔽 conftest 的 autouse 同名
  fixture：后者依赖共享 ``mock_llm``（会注册 e2e-mock），本车道不需要；影蔽后
  共享注册链在本模块测试中不再实例化。共享文件本身零修改。
- 共享 runner.mjs / conftest.py 只读复用；不 import test_mock_llm_flow.py 代码
  （另一任务正在改该文件，避免耦合）。

其余车道约束（与 test_mock_llm_flow.py 同口径）：

- ``serial`` + ``skipif`` 环境门（严禁模块级 skip 导致零收集、pytest 退出码 5）；
- Agent 经 API arrange（dialogue 槽绑本车道模型），消息走 UI composer；
- 已知产品缺陷嫌疑④：同实例累计第 6 个 Agent 起 turn 可能被静默丢弃（乐观态
  冻结、重发也丢）。本文件两用例各自建 1 个 Agent（实例第 1-2 个），单独运行
  或排在前部落在安全区；完整套件联跑时若本文件之前已累计 5 个 Agent，静默
  丢弃属已知缺陷嫌疑而非本用例回归（报告口径）。
"""

from __future__ import annotations

import copy
import os
import time
from typing import Any

import pytest

from tests.e2e.mock_llm import aimock_runtime, config_center
from tests.e2e.mock_llm.conftest import SCENARIOS_DIR, SCENARIOS_FIXTURES_DIR

pytestmark = [
    pytest.mark.serial,
    pytest.mark.timeout(0),
    # skipif 而非模块级 skip：模块级 skip 会「零收集」，closeout 选择器直跑
    # 本文件时 pytest 退出码 5（NO_TESTS_COLLECTED）判失败；skipif 逐条跳过退出码 0。
    pytest.mark.skipif(
        os.environ.get("VIBELUTION_E2E") != "1",
        reason="e2e 手动车道：设 VIBELUTION_E2E=1 后运行（见 docs/guides/e2e-mock-llm.md）",
    ),
]

# ---------------------------------------------------------------------------
# 锚点（web/src 对话流组件实测定位；结构 data 属性/class 锚，不用文案当唯一锚）
# ---------------------------------------------------------------------------

TURN_STATUS_NOTE = '[role="status"][data-active-turn-stage]'
THREAD_ROOT = "div[data-agent-thread-message-count]"

# ① 失败呈现结构锚（web/src/components/conversation/ConversationView.tsx）：
# - div.turnError：turn 失败实时「请求错误」横幅；
# - div.turnErrorNotice：时间线内持久化失败行（53c4418aa 后的低位失败呈现）。
# 两者均为 ConversationView.styles.ts 字面量 class token + role="status"。
TURN_ERROR_BANNER = 'div.turnError[role="status"]'
TURN_ERROR_NOTICE = 'div.turnErrorNotice[role="status"]'

# ② 失败轮重试入口（两条路径，任一在场即算重试入口可见）：
# - 实时 banner 路径（当前活跃 UX）：div.turnError[role="status"] 内 VButton
#   aria-label「重试这一轮」（onRetryTurn，ConversationView.tsx turnErrorActions）；
# - 历史行内路径：hover 行内动作容器 data-conversation-hover-actions="1" + VButton
#   aria-label「重试此轮」（onRegenerateAssistantMessage，branch-aware regenerate）。
# 均为结构 data 属性/class + aria-label 锚，非文案模糊匹配。
RETRY_BUTTON_BANNER = 'div.turnError[role="status"] button[aria-label="重试这一轮"]'
RETRY_BUTTON_HOVER = 'div[data-conversation-hover-actions="1"] button[aria-label="重试此轮"]'

# ③ 断流自动重试的可见性锚（ConversationActiveTurnStatusNote.tsx）：第 3 次尝试起
# 心跳条携带 data-active-turn-retry-attempt；SSE 会话流断连咨询 chip 为
# data-active-turn-disconnected。
RETRY_STAGE_NAMES = ("model_retry", "retrying")

# 用户主动终止锚（与 test_conversation_flow.py 同锚）：长重试链的用户收口手段。
STOP_BUTTON = 'button[aria-label="终止"]'

TURN_COMPLETE_TIMEOUT_MS = 120_000
# 断流轮自然收敛观察窗。实测（2026-09-26 干净环境两轮）：truncate 每次命中时产品
# 走「内层 5 次传输重试 × 阶梯降级/续跑」的链路，180s 未见终态；终态会到达但
# 总时长可能到分钟级。窗内收敛 → 断言终态失败可见性；窗内不收敛 → 降级为用户
# 终止收口并把「自愈链路过长」如实写进汇报（产品 UX 缺口证据，不落假闸门）。
STREAM_SETTLE_WINDOW_MS = 360_000
# 断流后的恢复轮可能撞上 litellm 路由对故障 deployment 的冷却期（实测：风暴后
# 首调被兜底路由代答、时长分钟级），起调等待放宽；恢复轮以「可起调 + 可终止」
# 为收口契约，不等兜底轮自然结束（时长不可控）。
CLOSE_START_TIMEOUT_MS = 90_000

DROP_MARKER = "E2E-SFV-DROP-V1"
DROP_TEXT = f"{DROP_MARKER} 验证断流可见性"
RETRY_MARKER = "E2E-SFV-400-V1"
RETRY_TEXT = f"{RETRY_MARKER} 验证失败轮重试"
RETRY_SUCCESS_TEXT = "SFV 失败轮重试成功：这是重试后的回复。"
CLOSE_MARKER = "E2E-SFV-CLOSE-V1"
CLOSE_TEXT = f"{CLOSE_MARKER} 断流后收口"
CLOSE_SUCCESS_TEXT = "SFV 收口回复：断流后会话照常可用。"

# 本车道独立 provider id：共享 operator config 上不与并行车道共享命名空间。
SFV_PROVIDER_ID = "e2e-mock-sfv"
SFV_CHAT_MODEL_KEY = "e2e-mock-chat"
SFV_RUNNER = SCENARIOS_DIR / "sfv_runner.mjs"


def sfv_model_ref() -> str:
    return f"{SFV_PROVIDER_ID}/{SFV_CHAT_MODEL_KEY}"


# ---------------------------------------------------------------------------
# 自持 mock 基础设施（provider 注册/注销，独立 id；链路口径同 config_center）
# ---------------------------------------------------------------------------


class SfvProviderSession:
    """独立 provider（e2e-mock-sfv）在共享 operator config 上的注册/注销。

    draft → apply 链路与 config_center.ConfigCenterSession 一致；恢复核对放宽
    一处：快照中的 ``e2e-mock``（并行车道的 id）被其会话正常注销不算本车道
    失败——两车道共享 config 但 provider 命名空间独立。
    """

    def __init__(self, port: int, *, base_url: str) -> None:
        self.port = port
        self.provider_base_url = f"{base_url.rstrip('/').removesuffix('/v1')}/v1"
        self.snapshot_providers: dict[str, Any] = {}

    def _current_providers(self) -> dict[str, Any]:
        status, result = config_center._api_request(self.port, "GET", "/api/config/workspace")
        workspace = config_center._require_ok(status, result, "GET /api/config/workspace")
        llm = (workspace.get("publicConfig") or {}).get("llm", {})
        providers = llm.get("providers", {})
        return providers if isinstance(providers, dict) else {}

    def snapshot(self) -> None:
        self.snapshot_providers = copy.deepcopy(self._current_providers())
        # 本车道 provider 的上次会话残留由 register() 的自愈注销清理，不进快照
        # 基线——否则自愈删除会触发「快照 provider 被外部改动删除」的误报
        # （实测 run9）。
        self.snapshot_providers.pop(SFV_PROVIDER_ID, None)

    def _entry(self) -> dict[str, Any]:
        entry = config_center.mock_provider_entry(self.provider_base_url)
        entry["label"] = "E2E Mock LLM SFV (aimock)"
        return entry

    def _purge_orphan_agents(self) -> None:
        """清掉上次会话残留的本车道测试 Agent（live 模型引用会挡 provider 注销）。

        实测（run6→run8）：teardown 被 active work 挡住的会话会在实例数据里留下
        绑定 e2e-mock-sfv 的 Agent；下次会话 provider 自愈注销时被 409 live
        reference 挡死。注册前按模型引用/固定 displayName 双条件清场。

        删除必须**回读验证 + 限次重试**（实验实测：单次 archive+purge 可能都没
        生效，残留直接把 provider 自愈注销 409 堵死）；整体尽力而为，实例未就绪
        时跳过不阻塞注册。
        """
        agents: list[Any] | None = None
        for attempt in range(3):
            try:
                status, result = config_center._api_request(
                    self.port, "GET", "/api/agents?includeArchived=true", timeout_seconds=30.0
                )
            except (TimeoutError, OSError, config_center.ConfigCenterError) as exc:
                print(f"[sfv] 残留 Agent 清场读取失败（第 {attempt + 1} 次）: {exc}")
                time.sleep(2.0)
                continue
            if status == 200 and isinstance(result, list):
                agents = result
            break
        if agents is None:
            print("[sfv] 残留 Agent 清场跳过（实例未就绪或无清单）")
            return

        def _is_orphan(item: Any) -> bool:
            if not isinstance(item, dict):
                return False
            agent_id = str(item.get("agentId") or "").strip()
            if not agent_id:
                return False
            bindings = item.get("llmBindings") or {}
            dialogue = bindings.get("dialogue") if isinstance(bindings, dict) else None
            model_id = str((dialogue or {}).get("modelId") or "")
            display_name = str(item.get("displayName") or "")
            return bool(
                model_id.startswith(f"{SFV_PROVIDER_ID}/") or display_name == "E2E SFV Agent"
            )

        orphans = [item for item in agents if _is_orphan(item)]
        if not orphans:
            return
        # 强杀/中断的会话其在飞 turn 会被 startup-recovery 复活，持续占住 live
        # 引用（run15→16 实测）——删除前先对孤儿 Agent 的会话做 turn stop。
        from tests.e2e.helpers.agent_factory import stop_session_turn
        from tests.e2e.helpers.instance_registry import fetch_json

        for item in orphans:
            agent_id = str(item.get("agentId") or "")
            try:
                catalog = fetch_json(
                    self.port, f"/api/sessions/query?agentId={agent_id}", timeout_seconds=20.0
                )
                for session in (catalog.get("items") or catalog.get("sessions") or [])[:3]:
                    session_id = str((session or {}).get("id") or "")
                    if session_id:
                        stop_session_turn(self.port, session_id)
            except Exception as exc:  # noqa: BLE001 - stop 尽力而为
                print(f"[sfv] 孤儿 Agent {agent_id} 的 turn stop 未完成: {exc}")
        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline:
            for item in orphans:
                agent_id = str(item.get("agentId") or "")
                if item.get("_purged"):
                    continue
                print(f"[sfv] 清理残留测试 Agent: {agent_id} ({item.get('displayName')})")
                try:
                    config_center._api_request(
                        self.port, "DELETE", f"/api/agents/{agent_id}", timeout_seconds=90.0
                    )
                    config_center._api_request(
                        self.port, "DELETE", f"/api/agents/{agent_id}/purge", timeout_seconds=90.0
                    )
                except (TimeoutError, OSError, config_center.ConfigCenterError) as exc:
                    print(f"[sfv] 残留 Agent {agent_id} 删除瞬态失败: {exc}")
            try:
                status, result = config_center._api_request(
                    self.port, "GET", "/api/agents?includeArchived=true", timeout_seconds=30.0
                )
            except (TimeoutError, OSError, config_center.ConfigCenterError):
                time.sleep(2.0)
                continue
            if status == 200 and isinstance(result, list):
                remaining = [item for item in result if _is_orphan(item)]
                if not remaining:
                    print("[sfv] 残留测试 Agent 已清空")
                    return
                orphans = remaining
            time.sleep(2.0)
        print("[sfv] 残留测试 Agent 清场未闭环（继续注册，注销可能被 live 引用挡）")

    def register(self) -> None:
        self._purge_orphan_agents()
        last_error: Exception | None = None
        for attempt in range(1, config_center.APPLY_CONFLICT_RETRIES + 1):
            try:
                self._register_once()
                return
            except config_center.ConfigCenterError as exc:
                if not config_center._is_conflict(exc):
                    raise
                last_error = exc
                print(f"[sfv] apply 基线冲突（第 {attempt} 次），重读配置重试: {exc}")
                time.sleep(1.0)
        raise last_error  # type: ignore[misc]

    def _register_once(self) -> None:
        providers = self._current_providers()
        if SFV_PROVIDER_ID in providers:
            print(f"[sfv] {SFV_PROVIDER_ID} 已在配置中（上次会话残留），先走注销再注册")
            self.restore_and_verify()
        workspace_status, workspace = config_center._api_request(
            self.port, "GET", "/api/config/workspace"
        )
        workspace = config_center._require_ok(
            workspace_status, workspace, "GET /api/config/workspace"
        )
        base_hash = str(workspace.get("hash") or "")
        if not base_hash:
            raise config_center.ConfigCenterError("workspace 未返回 hash，无法作为 baseHash")
        draft_status, draft = config_center._api_request(
            self.port,
            "POST",
            "/api/config/draft/providers",
            {
                "publicConfig": workspace.get("publicConfig") or {},
                "draftMeta": {"source": "e2e-sfv-mock-llm"},
                "baseHash": base_hash,
                "providerId": SFV_PROVIDER_ID,
                "provider": self._entry(),
            },
        )
        draft = config_center._require_ok(
            draft_status, draft, "POST /api/config/draft/providers"
        )
        drafted_config = draft.get("publicConfig")
        if not isinstance(drafted_config, dict):
            raise config_center.ConfigCenterError(f"草稿响应缺 publicConfig: {str(draft)[:300]}")
        apply_status, applied = config_center._api_request(
            self.port,
            "PUT",
            "/api/config/apply",
            {
                "publicConfig": drafted_config,
                "draftMeta": {"source": "e2e-sfv-mock-llm"},
                "baseHash": base_hash,
                "baseConfig": None,
            },
        )
        applied = config_center._require_ok(apply_status, applied, "PUT /api/config/apply")
        llm = (applied.get("publicConfig") or {}).get("llm", {})
        providers = llm.get("providers", {}) if isinstance(llm, dict) else {}
        entry = providers.get(SFV_PROVIDER_ID)
        if not isinstance(entry, dict):
            raise config_center.ConfigCenterError(
                f"apply 后回读未见 {SFV_PROVIDER_ID}（保现场）：providers={sorted(providers)}"
            )
        actual_base = str(entry.get("base_url") or "")
        if actual_base != self.provider_base_url:
            raise config_center.ConfigCenterError(
                f"apply 后 base_url 不符: {actual_base!r} != {self.provider_base_url!r}"
            )
        print(f"[sfv] provider {SFV_PROVIDER_ID} 已注册: base_url={actual_base}")

    def restore_and_verify(self) -> None:
        last_error: Exception | None = None
        for attempt in range(1, config_center.APPLY_CONFLICT_RETRIES + 1):
            try:
                self._restore_once()
                self._verify_restored()
                return
            except config_center.ConfigCenterError as exc:
                if not config_center._is_conflict(exc):
                    raise
                last_error = exc
                print(f"[sfv] 恢复 apply 基线冲突（第 {attempt} 次），重试: {exc}")
                time.sleep(1.0)
        raise last_error  # type: ignore[misc]

    def _restore_once(self) -> None:
        workspace_status, workspace = config_center._api_request(
            self.port, "GET", "/api/config/workspace"
        )
        workspace = config_center._require_ok(
            workspace_status, workspace, "GET /api/config/workspace"
        )
        base_hash = str(workspace.get("hash") or "")
        providers = self._current_providers()
        entry = providers.get(SFV_PROVIDER_ID)
        if not isinstance(entry, dict):
            print(f"[sfv] {SFV_PROVIDER_ID} 已不在配置中，跳过注销")
            return
        drafted = workspace.get("publicConfig") or {}
        models = entry.get("models") or {}
        for model_key in sorted(models):
            model_status, model_draft = config_center._api_request(
                self.port,
                "DELETE",
                f"/api/config/draft/providers/{SFV_PROVIDER_ID}/models/{model_key}",
                {
                    "publicConfig": drafted,
                    "draftMeta": {"source": "e2e-sfv-mock-llm"},
                    "baseHash": base_hash,
                    "providerId": SFV_PROVIDER_ID,
                    "upstreamId": str((models.get(model_key) or {}).get("upstream_id") or ""),
                    "modelKey": model_key,
                },
            )
            drafted = (
                config_center._require_ok(model_status, model_draft, f"DELETE draft models/{model_key}")
                .get("publicConfig")
            )
        del_status, del_draft = config_center._api_request(
            self.port,
            "DELETE",
            f"/api/config/draft/providers/{SFV_PROVIDER_ID}",
            {
                "publicConfig": drafted,
                "draftMeta": {"source": "e2e-sfv-mock-llm"},
                "baseHash": base_hash,
                "providerId": SFV_PROVIDER_ID,
            },
        )
        drafted = (
            config_center._require_ok(del_status, del_draft, f"DELETE draft providers/{SFV_PROVIDER_ID}")
            .get("publicConfig")
        )
        apply_status, _applied = config_center._api_request(
            self.port,
            "PUT",
            "/api/config/apply",
            {
                "publicConfig": drafted,
                "draftMeta": {"source": "e2e-sfv-mock-llm"},
                "baseHash": base_hash,
                "baseConfig": None,
            },
        )
        config_center._require_ok(apply_status, _applied, "PUT /api/config/apply (sfv restore)")

    def _verify_restored(self) -> None:
        providers = self._current_providers()
        if SFV_PROVIDER_ID in providers:
            raise config_center.ConfigCenterError(
                f"恢复后仍存在 {SFV_PROVIDER_ID}（注销失败，保现场待排查）"
            )
        # 并行车道共享 config：其 e2e-mock 命名空间（含产品弹性阶梯派生的
        # e2e-mock-recovery 临时 provider，run11 实测进过 config 又消失）的出没
        # 不算本车道失败，只核对快照中真实 operator provider 未被误删。
        missing = sorted(
            key
            for key in self.snapshot_providers
            if not key.startswith("e2e-mock") and key not in providers
        )
        if missing:
            raise config_center.ConfigCenterError(
                f"快照中的 provider 被外部改动删除: {missing}，需要人工核查 config.toml"
            )
        print(f"[sfv] {SFV_PROVIDER_ID} 已注销；快照核心 provider 全部在位")


class SfvMockHandle:
    """会话级自持 mock 句柄：实例端口 + 本车道 aimock 服务器 + provider 会话。"""

    def __init__(self, instance_port: int, server: aimock_runtime.AimockServer) -> None:
        self.instance_port = instance_port
        self.server = server
        self.provider = SfvProviderSession(instance_port, base_url=server.base_url)

    # -- Agent arrange（口径同 MockLlmHandle，绑定本车道模型） -----------------

    def create_agent(self, display_name: str) -> dict:
        def _post(path: str, payload: dict) -> dict:
            last_exc: Exception | None = None
            status: int | None = None
            result: Any = None
            for _attempt in range(3):
                try:
                    status, result = config_center._api_request(
                        self.instance_port, "POST", path, payload, timeout_seconds=90.0
                    )
                    break
                except (TimeoutError, OSError, config_center.ConfigCenterError) as exc:
                    last_exc = exc
                    time.sleep(2.0)
            else:
                raise RuntimeError(f"POST {path} 连续失败（瞬态重试耗尽）: {last_exc}")
            if status is None or status < 200 or status >= 300 or not isinstance(result, dict):
                raise RuntimeError(f"POST {path} 失败: HTTP {status} {str(result)[:300]}")
            return result

        template_catalog_status, template_catalog = config_center._api_request(
            self.instance_port, "GET", "/api/prompt-templates", timeout_seconds=30.0
        )
        templates = (template_catalog or {}).get("templates") or []
        template_id = next(
            (str((t or {}).get("templateId") or "").strip() for t in templates
             if str((t or {}).get("templateId") or "").strip()),
            "",
        )
        if not template_id:
            raise RuntimeError(f"实例无可用提示词模板: {str(template_catalog)[:200]}")
        agent = _post(
            "/api/agents",
            {
                "displayName": display_name,
                "primaryMode": "chat",
                "promptTemplateId": template_id,
                "llmBindings": {"dialogue": {"modelId": sfv_model_ref()}},
            },
        )
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id:
            raise RuntimeError(f"agent 创建响应缺 agentId: {str(agent)[:300]}")
        session_id = str(agent.get("directSessionId") or "").strip()
        if not session_id:
            catalog_status, catalog = config_center._api_request(
                self.instance_port,
                "GET",
                f"/api/sessions/query?agentId={agent_id}",
                timeout_seconds=30.0,
            )
            items = (catalog or {}).get("items") or (catalog or {}).get("sessions") or []
            if items:
                session_id = str(items[0].get("id") or "")
        if not session_id:
            raise RuntimeError(f"agent {agent_id} 未找到关联会话")
        return {"agentId": agent_id, "sessionId": session_id}

    def delete_agent(self, agent_id: str, *, timeout_seconds: float = 60.0) -> None:
        """归档 + purge + 回读核对（口径同 MockLlmHandle.delete_agent）。"""

        def _delete(path: str) -> None:
            try:
                config_center._api_request(self.instance_port, "DELETE", path, timeout_seconds=90.0)
            except (TimeoutError, OSError, config_center.ConfigCenterError) as exc:
                print(f"[sfv] DELETE {path} 瞬态失败，重试: {exc}")

        def _agent_present() -> bool:
            try:
                status, result = config_center._api_request(
                    self.instance_port,
                    "GET",
                    "/api/agents?includeArchived=true",
                    timeout_seconds=30.0,
                )
            except (TimeoutError, OSError, config_center.ConfigCenterError):
                return True
            if status != 200 or not isinstance(result, list):
                return True
            return any(
                str((item or {}).get("agentId") or "") == agent_id for item in result
            )

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            _delete(f"/api/agents/{agent_id}")
            _delete(f"/api/agents/{agent_id}/purge")
            if not _agent_present():
                return
            time.sleep(2.0)
        print(f"[sfv] 测试 Agent 删除未闭环（live 引用会挡 provider 注销）: {agent_id}")


@pytest.fixture(scope="session")
def sfv_mock(e2e_instance):
    """起本车道 aimock（sfv_runner.mjs）→ 注册 e2e-mock-sfv → 测试 → 注销 → 停进程。

    runner 模式（程序化剧本）：产品主聊天调用的末条 user 消息是 Turn Status Bar
    遥测尾巴，JSON fixture 的 userMessage（末条匹配）路由不到主调用。
    """
    server = aimock_runtime.start_aimock(SCENARIOS_FIXTURES_DIR, script=SFV_RUNNER)
    handle = SfvMockHandle(instance_port=e2e_instance.port, server=server)
    try:
        handle.provider.snapshot()
        handle.provider.register()
    except Exception:
        try:
            server.stop()
            server.assert_stopped()
        except Exception as stop_exc:  # noqa: BLE001 - 不掩盖注册失败原始错误
            print(f"[sfv] 注册失败后的 aimock 补停未闭环: {stop_exc}")
        raise
    print(f"[sfv] 会话就绪: aimock={server.base_url} provider={SFV_PROVIDER_ID}")
    yield handle
    teardown_error: Exception | None = None
    try:
        handle.provider.restore_and_verify()
    except Exception as exc:  # noqa: BLE001 - 恢复失败要报告并保现场
        teardown_error = exc
        print(f"[sfv] provider 注销/恢复失败（保现场）: {exc}")
    try:
        server.stop()
        server.assert_stopped()
    except Exception as exc:  # noqa: BLE001 - 进程零残留是硬指标
        print(f"[sfv] aimock 拆机异常: {exc}")
        if teardown_error is None:
            teardown_error = exc
    if teardown_error is not None:
        raise teardown_error


@pytest.fixture(autouse=True)
def reset_mock_llm_journal():
    """影蔽 conftest 的同名 autouse fixture（口径见模块 docstring「车道自持性」）。

    共享版依赖 session 级 ``mock_llm``（注册共享 provider id e2e-mock）；本车道
    用独立 provider 与独立 aimock，journal 隔离由「每用例独立 marker + aimock
    journal 仅作证据」保证，无需清空。no-op 仅为占住名字阻止共享注册链实例化。
    """
    yield


# ---------------------------------------------------------------------------
# 共享步骤（自包含实现，语义与 test_mock_llm_flow.py 同口径）
# ---------------------------------------------------------------------------


def open_agent_chat(page: Any, e2e_instance: Any, session_id: str) -> None:
    from tests.e2e.helpers.page_anchors import wait_route_ready

    page.goto(
        f"{e2e_instance.base_url}/chat?session={session_id}",
        wait_until="domcontentloaded",
    )
    wait_route_ready(page)
    thread = page.locator(THREAD_ROOT).first
    thread.wait_for(state="visible", timeout=20_000)


def send_message(page: Any, text: str) -> None:
    composer = page.locator('textarea[aria-label="发送消息"]').first
    composer.wait_for(state="visible", timeout=15_000)
    composer.click()
    composer.fill(text)
    composer.press("Enter")


def _attr(holder: Any, name: str, *, timeout_ms: int = 800) -> str:
    """读元素属性；元素瞬时分离（turn 收口竞态）时返回空串而不是挂死。"""
    try:
        return holder.get_attribute(name, timeout=timeout_ms) or ""
    except Exception:  # noqa: BLE001 - playwright 定位失败即视为元素已消失
        return ""


def thread_count(page: Any) -> int:
    raw = _attr(page.locator(THREAD_ROOT).first, "data-agent-thread-message-count")
    try:
        return int(raw)
    except ValueError:
        return 0


def wait_turn_closed(page: Any, *, expected_messages: int, timeout_ms: int = 60_000) -> str:
    """等 thread 回到 idle 且消息数达到预期；返回最终 thread status。"""
    deadline = time.monotonic() + timeout_ms / 1000
    thread = page.locator(THREAD_ROOT).first
    while time.monotonic() < deadline:
        status = _attr(thread, "data-agent-thread-status")
        if status == "idle" and thread_count(page) >= expected_messages:
            return status
        page.wait_for_timeout(200)
    raise AssertionError(
        f"thread 未收口（status={thread.get_attribute('data-agent-thread-status')} "
        f"count={thread.get_attribute('data-agent-thread-message-count')}，"
        f"预期 count>={expected_messages}）"
    )


def wait_thread_idle(page: Any, *, timeout_ms: int = 60_000) -> str:
    """等 thread 回 idle（不设消息数要求：被终止/失败的轮次投影形态不定）。"""
    deadline = time.monotonic() + timeout_ms / 1000
    thread = page.locator(THREAD_ROOT).first
    while time.monotonic() < deadline:
        status = _attr(thread, "data-agent-thread-status")
        if status == "idle":
            return status
        page.wait_for_timeout(200)
    raise AssertionError(
        f"thread 未回 idle（status={thread.get_attribute('data-agent-thread-status')}）"
    )


def thread_text(page: Any) -> str:
    return page.locator(THREAD_ROOT).first.inner_text()


def wait_thread_text(page: Any, needle: str, *, timeout_ms: int = 15_000) -> str:
    """等指定文本上屏后再返回时间线文本（idle 投影可能晚一拍）。"""
    deadline = time.monotonic() + timeout_ms / 1000
    texts = thread_text(page)
    while needle not in texts and time.monotonic() < deadline:
        page.wait_for_timeout(200)
        texts = thread_text(page)
    return texts


def wait_turn_started(
    page: Any,
    sfv_mock: Any,
    *,
    submit_text: str,
    timeout_ms: int = 8_000,
    baseline_entries: int = 0,
) -> bool:
    """等 turn 真正启动：journal 超过基线出现新请求，或 stage 推进到 user_submit。

    乐观态 stage 条不是启动证据（已知缺陷嫌疑④冻结在 user_submit）；journal
    必须相对 ``baseline_entries`` 增长——同一用例内第二轮起，前一轮条目仍在
    journal 里，绝对非空检查会把陈旧条目误当本轮启动。超时重发一次。返回是否
    最终启动。
    """
    def _started() -> bool:
        if len(sfv_mock.server.journal(path="/v1/chat/completions")) > baseline_entries:
            return True
        notes = page.locator(TURN_STATUS_NOTE)
        for i in range(min(notes.count(), 3)):
            stage = _attr(notes.nth(i), "data-active-turn-stage")
            if stage and stage != "user_submit":
                return True
        return False

    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if _started():
            return True
        page.wait_for_timeout(250)
    print(f"[sfv] 提交未真正启动 turn（乐观态冻结嫌疑），重发一次: {submit_text[:40]!r}")
    send_message(page, submit_text)
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if _started():
            return True
        page.wait_for_timeout(250)
    return False


def stop_active_turn(page: Any) -> None:
    """用户终止在飞 turn：点 composer 终止按钮，等终止请求收口回 idle。

    若按钮已消失且 thread 已 idle（自然收口竞态），直接返回。
    """
    stop = page.locator(STOP_BUTTON).first
    if stop.count() == 0:
        wait_thread_idle(page, timeout_ms=10_000)
        return
    try:
        stop.wait_for(state="visible", timeout=3_000)
        stop.click()
    except Exception:  # noqa: BLE001 - 终止按钮在点击前消失 = 自然收口竞态
        pass
    wait_thread_idle(page, timeout_ms=60_000)


def journal_main_entries(sfv_mock: Any, marker: str) -> list[dict[str, Any]]:
    """主调用条目（口径对齐共享车道的 64KB 坑，形状为实验实测）。

    aimock journal 单条目 64KB 上限：主调用请求体超限时条目仍记录，但 body 解析
    为空（``messages: []``、``model: None``，实验实测形状）——按 marker 匹配
    messages 会全部漏计（run6-14 连续误报「主调用未到 mock」即此因）。口径：
    - body 缺失或 messages 为空：按主调用计（标题等辅助调用 body 很小，不会触顶）；
    - messages 在场：末条 user 以「用户消息：」开头 → 标题辅助调用，排除；不含
      本用例 marker → 其他调用面（探活等），排除。
    """
    entries = sfv_mock.server.journal(path="/v1/chat/completions")
    mains: list[dict[str, Any]] = []
    for entry in entries:
        body = entry.get("body") or {}
        msgs = body.get("messages") or []
        if not body or not msgs:
            mains.append(entry)
            continue
        last_user = ""
        for m in reversed(msgs):
            if (m or {}).get("role") == "user":
                last_user = str((m or {}).get("content") or "")
                break
        if last_user.lstrip().startswith("用户消息："):
            continue
        if any(marker in str((m or {}).get("content") or "") for m in msgs):
            mains.append(entry)
    return mains


def entry_status(entry: dict[str, Any]) -> int:
    return int((entry.get("response") or {}).get("status") or 0)


def retry_entry_count(page: Any) -> int:
    """失败轮重试入口总数（banner 实时路径 + 行内历史路径，见锚点注释）。"""
    return page.locator(RETRY_BUTTON_BANNER).count() + page.locator(RETRY_BUTTON_HOVER).count()


def assert_recipe_alive(page: Any) -> None:
    from tests.e2e.helpers.page_anchors import domain_recipe_selector

    assert page.locator(domain_recipe_selector("chat-session-workbench")).first.is_visible(), (
        "chat 页面壳（chat-session-workbench recipe）不可见：前端在故障注入后挂死"
    )


@pytest.fixture
def sfv_agent(sfv_mock: Any):
    """建一个绑本车道模型的 Agent；用例结束归档（与本文件其他用例隔离）。"""
    created = sfv_mock.create_agent("E2E SFV Agent")
    yield created
    sfv_mock.delete_agent(created["agentId"])


# ---------------------------------------------------------------------------
# 用例一：断流可见
# ---------------------------------------------------------------------------


def _sample_stream_failure_visibility(page: Any, *, timeout_ms: int) -> tuple[str, dict[str, Any]]:
    """断流轮期间轮询采样可见性证据，直到 thread 自然收口或观察窗耗尽。

    返回 (outcome, evidence)；outcome：``settled``（thread 回 idle 且 active-turn
    note 消失）/ ``unresolved``（观察窗耗尽仍未收口）。证据按强弱分级（强弱由
    断言消费，采样本身不判失败）：
    - retry_stage_values：data-active-turn-stage 出现过的 retrying/model_retry；
    - retry_attempt_seen：data-active-turn-retry-attempt（第 3 次尝试起）；
    - disconnected_seen：SSE 会话流断连咨询 chip（data-active-turn-disconnected）；
    - banner_seen / notice_seen：失败态结构锚是否出现过。
    """
    evidence: dict[str, Any] = {
        "stages": [],
        "retry_stage_values": [],
        "retry_attempt_seen": False,
        "disconnected_seen": False,
        "banner_seen": False,
        "notice_seen": False,
    }
    # 提交到乐观壳渲染之间有一小段 idle+无 note 的窗口，必须见过至少一次活动
    # （note/横幅/失败卡任一）才允许按「idle 且 note 消失」判收口，否则抢跑。
    saw_activity = False
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        notes = page.locator(TURN_STATUS_NOTE)
        count = notes.count()
        for i in range(min(count, 4)):
            note = notes.nth(i)
            stage = _attr(note, "data-active-turn-stage")
            if stage:
                if not evidence["stages"] or evidence["stages"][-1] != stage:
                    evidence["stages"].append(stage)
                if stage in RETRY_STAGE_NAMES and stage not in evidence["retry_stage_values"]:
                    evidence["retry_stage_values"].append(stage)
            if _attr(note, "data-active-turn-retry-attempt"):
                evidence["retry_attempt_seen"] = True
            if _attr(note, "data-active-turn-disconnected"):
                evidence["disconnected_seen"] = True
        if page.locator(TURN_ERROR_BANNER).count():
            evidence["banner_seen"] = True
        if page.locator(TURN_ERROR_NOTICE).count():
            evidence["notice_seen"] = True
        saw_activity = saw_activity or count > 0 or evidence["banner_seen"] or evidence["notice_seen"]
        thread_status = _attr(page.locator(THREAD_ROOT).first, "data-agent-thread-status")
        if saw_activity and thread_status == "idle" and count == 0:
            return "settled", evidence
        page.wait_for_timeout(150)
    return "unresolved", evidence


def test_stream_truncation_is_visible_and_session_recovers(
    page: Any, e2e_instance: Any, sfv_mock: Any, sfv_agent: dict
) -> None:
    """断流（每次调用都 truncate）必须可观测，且失败后用户有收口手段。

    剧本契约（本车道剧本 1）：每次主调用都在 3 chunk 后截断——产品的自动重试
    （1010ec9cf：部分流发射后的传输失败走重试环）也无法成功。硬闸门（0916
    「断流可见」钉子）：观察窗内必须采到重试/断流投影（心跳条 model_retry/
    retrying stage 或 data-active-turn-retry-attempt）——干净实测必现
    model_retry。观察窗内自然收敛则追加断言终态失败可见性与重试入口；窗内不
    收敛（自愈链路过长，实测分钟级）则如实降级为「用户终止收口 + 会话仍可用」，
    并把长链事实打印为产品 UX 缺口证据，不落假闸门。
    """
    open_agent_chat(page, e2e_instance, sfv_agent["sessionId"])

    count_before = thread_count(page)
    send_message(page, DROP_TEXT)
    assert wait_turn_started(page, sfv_mock, submit_text=DROP_TEXT), "断流轮未启动"
    outcome, evidence = _sample_stream_failure_visibility(
        page, timeout_ms=STREAM_SETTLE_WINDOW_MS
    )
    if outcome == "unresolved":
        # 产品缺口证据（如实记录，不判失败本身）：断流自愈链路超过观察窗仍未
        # 收敛——用户长时间面对重试心跳无终态。降级收口：用户终止。
        print(
            f"[sfv] 产品 UX 证据：断流自愈链路在 {STREAM_SETTLE_WINDOW_MS}ms 内未收敛"
            f"（stages={evidence['stages']}），降级为用户终止收口"
        )
        stop_active_turn(page)
    else:
        wait_turn_closed(page, expected_messages=count_before + 2, timeout_ms=30_000)
    assert_recipe_alive(page)

    # journal 证据：断流剧本的主调用次数。截断流的 HTTP status 仍是 200（SSE 头
    # 先行），无法用 status 区分截断；条目数 >= 2 即产品自动重试的直接证据。
    drop_entries = journal_main_entries(sfv_mock, DROP_MARKER)
    if not drop_entries:
        # 已知缺陷嫌疑④兜底：turn 收口但主调用未到 mock（静默丢弃），整轮重发一次。
        print("[sfv] 断流轮收口但主调用未到 mock（静默丢弃嫌疑），重发一次")
        fallback_baseline = len(sfv_mock.server.journal(path="/v1/chat/completions"))
        send_message(page, DROP_TEXT)
        assert wait_turn_started(
            page, sfv_mock, submit_text=DROP_TEXT, baseline_entries=fallback_baseline
        ), "重发后断流轮仍未启动"
        outcome, evidence = _sample_stream_failure_visibility(
            page, timeout_ms=STREAM_SETTLE_WINDOW_MS
        )
        if outcome == "unresolved":
            stop_active_turn(page)
        else:
            wait_turn_closed(page, expected_messages=count_before + 4, timeout_ms=30_000)
        drop_entries = journal_main_entries(sfv_mock, DROP_MARKER)
    assert drop_entries, "断流剧本主调用未到 mock（journal 无该 marker 条目）"
    drop_statuses = [entry_status(e) for e in drop_entries]
    print(
        f"[sfv] 断流轮主调用次数={len(drop_entries)} statuses={drop_statuses} "
        f"outcome={outcome} stages={evidence['stages']} "
        f"retry_attempt_seen={evidence['retry_attempt_seen']} "
        f"disconnected_seen={evidence['disconnected_seen']}"
    )

    # 硬闸门（0916「断流可见」）：重试/断流投影必须可观测——心跳条进入重试相位
    # （model_retry/retrying）或第 3 次尝试起的可见计数。终态失败可见性作为
    # 收敛场景的追加断言。
    retry_projection = bool(evidence["retry_stage_values"]) or evidence["retry_attempt_seen"]
    notice_count = page.locator(TURN_ERROR_NOTICE).count()
    banner_count = page.locator(TURN_ERROR_BANNER).count()
    failed_visible = bool(
        evidence["notice_seen"] or evidence["banner_seen"] or notice_count or banner_count
    )
    print(
        f"[sfv] 可见性分级: retry_projection={retry_projection} "
        f"failed_visible={failed_visible}（notice={notice_count} banner={banner_count}）"
    )
    if outcome == "settled":
        assert retry_projection or failed_visible, (
            f"断流整轮静默（无重试投影、无失败态投影）——0916「断流可见」缺口: "
            f"stages={evidence['stages']}"
        )
    else:
        assert retry_projection, (
            f"断流重试链路无任何用户可见投影（心跳条无 retrying/model_retry、"
            f"无 data-active-turn-retry-attempt）——0916「断流可见」缺口: "
            f"stages={evidence['stages']}"
        )
    if failed_visible:
        # 失败态可见 → 必须提供重试入口（banner「重试这一轮」或行内「重试此轮」）。
        retry_count = retry_entry_count(page)
        assert retry_count >= 1, (
            f"断流失败态可见（notice={notice_count} banner={banner_count}）"
            f"但无任何重试入口（count={retry_count}）"
        )
    # 收口且不炸已由 assert_recipe_alive 保证；收口恢复：失败/终止之后用户仍有
    # 完整的收口手段——新消息可提交、可起调、可终止、thread 回 idle。风暴后
    # litellm 路由对故障 deployment 有冷却期，恢复轮可能被兜底路由代答且时长
    # 分钟级，因此恢复轮以「可起调 + 可终止」为收口契约，不等兜底轮自然结束；
    # 命中 mock 正文作为路由自愈证据打印（不硬断言，见下）。
    count_after_drop = thread_count(page)
    journal_before_close = len(sfv_mock.server.journal(path="/v1/chat/completions"))
    send_message(page, CLOSE_TEXT)
    close_started = wait_turn_started(
        page,
        sfv_mock,
        submit_text=CLOSE_TEXT,
        timeout_ms=CLOSE_START_TIMEOUT_MS,
        baseline_entries=journal_before_close,
    )
    if not close_started:
        # 冷却期长于起调窗口：再给一次机会（wait_turn_started 内部已重发过一次）。
        journal_before_close = len(sfv_mock.server.journal(path="/v1/chat/completions"))
        send_message(page, CLOSE_TEXT)
        close_started = wait_turn_started(
            page,
            sfv_mock,
            submit_text=CLOSE_TEXT,
            timeout_ms=CLOSE_START_TIMEOUT_MS,
            baseline_entries=journal_before_close,
        )
    assert close_started or thread_count(page) > count_after_drop, (
        "断流后恢复轮未启动且无任何新投影"
    )
    # 用户收口：终止恢复轮（冷却代答轮时长分钟级，不等自然结束），thread 回 idle
    # 即「会话可用、用户有收口手段」成立。
    stop_active_turn(page)
    texts = thread_text(page)
    served_by_mock = CLOSE_SUCCESS_TEXT in texts
    print(
        f"[sfv] 恢复轮已提交并终止收口：count={thread_count(page)} "
        f"由 mock 服答={served_by_mock}（冷却期由兜底路由代答亦算会话可用）"
    )
    assert_recipe_alive(page)


# ---------------------------------------------------------------------------
# 用例二：失败轮可重试
# ---------------------------------------------------------------------------


def test_failed_turn_offers_retry_entry_and_retry_closes(
    page: Any, e2e_instance: Any, sfv_mock: Any, sfv_agent: dict
) -> None:
    """不可重试 4xx → turn 失败态可见且有「重试此轮」入口 → 点重试新轮收口。

    剧本契约（本车道剧本 2）：第 1 次主调用返回 400 真参数错误
    （"Invalid parameter: messages"，bad_request fail-closed 不可重试），第 2 次
    返回成功正文。journal 断言 400→200 两次主调用（失败→用户重试）。
    """
    open_agent_chat(page, e2e_instance, sfv_agent["sessionId"])

    count_before = thread_count(page)
    send_message(page, RETRY_TEXT)
    assert wait_turn_started(page, sfv_mock, submit_text=RETRY_TEXT), "失败轮未启动"

    # 失败态上屏：400 fail-closed 快速失败，轮询等内联失败卡（主锚）或实时横幅。
    deadline = time.monotonic() + 60_000 / 1000
    while time.monotonic() < deadline:
        if page.locator(TURN_ERROR_NOTICE).count() or page.locator(TURN_ERROR_BANNER).count():
            break
        page.wait_for_timeout(200)
    wait_turn_closed(page, expected_messages=count_before + 2, timeout_ms=60_000)

    notice_count = page.locator(TURN_ERROR_NOTICE).count()
    banner_count = page.locator(TURN_ERROR_BANNER).count()
    print(f"[sfv] 失败轮呈现: notice={notice_count} banner={banner_count}")
    # 失败态可见：实时横幅（div.turnError，本轮实测的活跃呈现）或时间线内联失败
    # 卡（div.turnErrorNotice，53c4418aa 后的持久化呈现）任一在场即算可见。
    assert notice_count >= 1 or banner_count >= 1, (
        "turn 失败后时间线无任何失败态投影（banner 与 notice 均缺席）——"
        "失败态不可见，0916「失败可见」缺口"
    )
    assert_recipe_alive(page)

    # 重试入口（结构锚）：本轮实测活跃呈现为 banner 内「重试这一轮」；行内
    # 「重试此轮」（hover 容器，opacity 显隐）为持久化呈现路径——两者任一在场
    # 即点它。banner 按钮无需 hover；行内按钮先 hover 规避显隐时序竞态。
    banner_retry = page.locator(RETRY_BUTTON_BANNER).first
    hover_retry = page.locator(RETRY_BUTTON_HOVER).first
    if banner_retry.count() >= 1:
        retry_button = banner_retry
    else:
        retry_button = hover_retry
    assert retry_button.count() >= 1, (
        f"失败态可见但无任何重试入口（banner={banner_retry.count()} "
        f"hover={hover_retry.count()}）——09b53abfa「失败轮可重试」缺口"
    )
    retry_button.hover()
    retry_button.click()

    # 重试走 regenerate 管线重跑原 user 消息 → 剧本第 2 次尝试返回成功正文。
    texts = wait_thread_text(page, RETRY_SUCCESS_TEXT, timeout_ms=TURN_COMPLETE_TIMEOUT_MS)
    assert RETRY_SUCCESS_TEXT in texts, f"重试后的成功回复未上时间线: {texts[-300:]!r}"
    wait_turn_closed(page, expected_messages=count_before + 2, timeout_ms=60_000)
    assert_recipe_alive(page)

    # journal：失败→重试 = 2 次主调用，400 在前、200 在后（journal 追加序）。
    retry_entries = journal_main_entries(sfv_mock, RETRY_MARKER)
    statuses = [entry_status(e) for e in retry_entries]
    print(f"[sfv] 失败轮重试链主调用 statuses={statuses}")
    assert len(retry_entries) >= 2, (
        f"失败→重试主调用不足 2 次（statuses={statuses}）：重试未发出新的主调用"
    )
    assert 400 in statuses, f"journal 未记录首发 400: {statuses}"
    assert 200 in statuses, f"journal 未记录重试成功 200: {statuses}"
    assert statuses.index(400) < len(statuses) - 1 - statuses[::-1].index(200), (
        f"400 未发生在重试 200 之前: {statuses}"
    )
