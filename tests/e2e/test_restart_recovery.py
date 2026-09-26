# -*- coding: utf-8 -*-
"""e2e P1：重启自动恢复（钉 09-25 session startup recovery 整轮重发链路）。

钉的产品契约（core/web/services/session/startup_recovery.py + 前端
session_recovery_resumed 状态行）：
- 后端进程死亡瞬间若存在 journal open turn + chat_turn work-run 快照 active
  且 finishedAt 空 → 判定轮次被重启打断；
- startup sweep 用 ``submit_session_message(turn_mode="hot_restart_resume",
  write_intent=False, client_submission_id="resume:{turn_id}")`` 整轮重发
  （半截丢弃，LLM 流无断点，UI 不重复用户消息）；
- 恢复状态行走 EVENT_SESSION_RECOVERY_RESUMED（合成 turn ``session-recovery:{id}``），
  前端按 ``metadata.kind="session_recovery_resumed"`` 渲染成独立状态行
  （article.cliAgentLifecycleTurn 字面量类 + 文案「已从重启中恢复，继续执行」）；
- 重发后轮次正常收口，时间线消息计数有界（实测口径含一条重复 user 行，
  见 EXPECTED_THREAD_MESSAGES 注释的缺陷候选留档）。

中断编排为什么是「进程树硬终止」而不是 launcher stop（2026-09-26 实测定案）：
- 官方 launcher stop 是优雅车道：Electron retire 先走 graceful shutdown，后端
  harvest 会主动关停在飞轮次（`_stop_active_chat_turns_before_shutdown` →
  `request_stop_session_turn`），work-run 快照被写成终态 + finishedAt——重启后
  sweep 判据不成立、不重发。KEEP_DATA 尸检证据：快照
  status=completed/finishedAt 已写、重启后 45s 无重发主调用、无恢复状态行。
- startup sweep 钉的就是「进程死亡」场景（其 docstring：a still-active snapshot
  right after a restart proves the process died mid-turn）。因此本用例按
  registry 身份核验（spawnPid 存活 + cmdline 指向本 worktree 的
  web_workbench.py）后用 psutil 硬终止后端进程树模拟崩溃；这不是 lifecycle 命令、不涉 active-work guard，
  也无任何可见控制台（红线合规）。身份不符即 fail-closed，绝不误杀。
- 崩溃后的 registry 收口走官方车道：launcher stop 对 dead spawn 做身份核对与
  registry reconcile（reconcileDeadRegisteredHandles 路径），再 launcher start。

其他编排事实：
- aimock（车道自拉 node 进程，不在实例内）与 provider 注册横跨重启存活：
  provider 经配置中心 draft→apply 落盘共享 operator config，新后端实例从磁盘
  加载。本文件用模块级 fixture 自管 aimock + 注册（tests/e2e/mock_llm/conftest.py
  的 session 级 mock_llm fixture 与本文件互相不可见；直接复用其 aimock_runtime /
  config_center）。共享 config 有本机其他实例/页面的活跃并发写
  （实测 apply 409 与注册被整份覆盖），用例内对「在场」做自愈并留证据。
- 数据目录在崩溃→重启之间天然保留（只有会话 teardown 清数据，
  VIBELUTION_E2E_KEEP_DATA 语义）；重启后重读 registry 刷新端口事实。

已知边界（如实留档）：队列 drain 推一把、群聊孤儿轮收窄重发、重试预算跨重启
继承不在本用例覆盖面（各有单测；e2e 编排成本过高，见任务汇报）。
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytestmark = [
    pytest.mark.serial,
    pytest.mark.timeout(0),
    # skipif 而非模块级 skip：模块级 skip 会「零收集」，closeout 选择器直跑
    # 本文件时 pytest 退出码 5（NO_TESTS_COLLECTED）判失败；skipif 逐条跳过退出码 0。
    pytest.mark.skipif(
        os.environ.get("VIBELUTION_E2E") != "1",
        reason="e2e 手动车道：设 VIBELUTION_E2E=1 后运行（见 docs/guides/e2e-playwright.md）",
    ),
]

# E2E-MOCK-SLOW-V1 → runner.mjs 场景 (12) 慢速流（ttft 500ms / tps 8 / 240 字符），
# 只读复用共享剧本（边界：不改 runner.mjs）。
RESUME_MARKER = "E2E-MOCK-SLOW-V1"
SUBMIT_TEXT = f"{RESUME_MARKER} 重启自动恢复"

# 恢复状态行锚（web/src/components/conversation/ConversationView.tsx：
# isSessionRecoveryResumedMessage 分支复用 cliAgentLifecycleTurn 字面量类 token，
# 文案来自 conversationSpecialMessagePresentation.sessionRecoveryResumedLabel）。
RECOVERY_ROW_ANCHOR = "article.cliAgentLifecycleTurn"
RECOVERY_ROW_TEXT = "已从重启中恢复，继续执行"

# aimock 流窗口：主调用 200 到场后短等即动手——快照实测（2026-09-26）turn 从
# 启动到完整收口约 8s（240 字符分片 ≈60 token @8tps），kill 必须落在其中。
STREAMING_SETTLE_SECONDS = 1.0

CLOSED_TIMEOUT_SECONDS = 120.0
READY_TIMEOUT_SECONDS = 240.0
RESUMED_MAIN_CALL_TIMEOUT_SECONDS = 180.0
RESUMED_MAIN_CALL_POLL_SECONDS = 90.0
RECOVERY_ROW_TIMEOUT_MS = 60_000
RESUMED_TURN_CLOSE_TIMEOUT_MS = 420_000

# 收口后的时间线计数（pin 实测口径，2026-09-26 三次运行稳定复现）：
# 原始 user 行 1 + 重发轮 user 行 1（重复！）+ 恢复状态行 1 + 重发轮助手行 1 = 4。
# 缺陷候选如实留档：09-25 档案契约称 hot_restart_resume + write_intent=False
# 「UI 不重复用户消息」，实测时间线仍出现第二条相同 user 行（同文本、独立
# row-key、三次运行稳定）。按车道 ⑦b 先例不落假闸门：计数按实测 pin，
# 重复 user 行作为缺陷候选随任务汇报，待产品收口后本 pin 收紧为 3。
EXPECTED_THREAD_MESSAGES = 4

# 与 startup_recovery._RECOVERY_BUSY_WORK_RUN_STATUSES 同口径（快照 active 判据）。
INTERRUPTED_SNAPSHOT_STATUSES = {"queued", "running", "stopping", "paused"}

# 本用例专用 provider id：共享 operator config 上多车道并发写活跃（实测同 id
# e2e-mock 会在重启窗口内被其他车道同 id 注册整份覆写——劫持 base_url 后重发轮
# 的 LLM 调用打到别人 aimock，journal 断言必炸）。独立 id 与 mock_llm 车道的
# e2e-mock / 其他车道的 e2e-mock-sfv 互不干扰。
RECOVERY_PROVIDER_ID = "e2e-mock-recovery"
RECOVERY_MODEL_KEY = "e2e-mock-chat"


def recovery_model_ref() -> str:
    return f"{RECOVERY_PROVIDER_ID}/{RECOVERY_MODEL_KEY}"


class RecoveryProviderSession:
    """独立 provider id 的注册/自愈/注销（draft→apply，控制令牌口径）。

    与 mock_llm 车道 ConfigCenterSession 同链路，但 providerId 固定为
    ``e2e-mock-recovery``（见模块头注释的并发写证据）。port 可变：实例重启后
    由 :func:`_start_and_reattach` 刷新。
    """

    def __init__(self, port: int, *, base_url: str) -> None:
        import copy

        from tests.e2e.mock_llm import config_center

        self._cc = config_center
        self.port = port
        provider = config_center.mock_provider_entry(base_url.rstrip("/").removesuffix("/v1") + "/v1")
        provider["label"] = "E2E Mock LLM (aimock, restart-recovery)"
        self.provider_entry = provider
        self.models = copy.deepcopy(config_center.MOCK_PROVIDER_MODELS)
        self.provider_base_url = str(provider.get("base_url") or "")
        self.snapshot_providers: dict[str, Any] = {}
        self.snapshot_hash = ""

    # -- 读 -------------------------------------------------------------------

    def load_workspace(self) -> dict[str, Any]:
        # 冷启动后端的首个配置读可能超时（control-token/workspace 均 15-30s 级），
        # 对瞬态网络错误限次重试（与建 Agent 的重试口径一致）。
        last_exc: Exception | None = None
        for _attempt in range(3):
            try:
                status, result = self._cc._api_request(self.port, "GET", "/api/config/workspace")
                return self._cc._require_ok(status, result, "GET /api/config/workspace")
            except (TimeoutError, OSError, self._cc.ConfigCenterError) as exc:
                last_exc = exc
                time.sleep(2.0)
        raise self._cc.ConfigCenterError(f"GET /api/config/workspace 连续失败: {last_exc}")

    def current_providers(self, workspace: dict[str, Any] | None = None) -> dict[str, Any]:
        workspace = workspace or self.load_workspace()
        providers = (workspace.get("publicConfig") or {}).get("llm", {}).get("providers", {})
        return providers if isinstance(providers, dict) else {}

    # -- 快照 / 注册 / 自愈 / 注销 ---------------------------------------------

    def snapshot(self) -> None:
        import copy

        workspace = self.load_workspace()
        providers = self.current_providers(workspace)
        if RECOVERY_PROVIDER_ID in providers:
            # 上次会话残留（同 label 同源）先自愈注销，再取干净基线。
            print(f"[restart_recovery] 发现残留 {RECOVERY_PROVIDER_ID}，先自愈注销")
            self.snapshot_providers = copy.deepcopy(
                {k: v for k, v in providers.items() if k != RECOVERY_PROVIDER_ID}
            )
            self.restore_and_verify()
            workspace = self.load_workspace()
            providers = self.current_providers(workspace)
        self.snapshot_providers = copy.deepcopy(providers)
        self.snapshot_hash = str(workspace.get("hash") or "")

    def register(self) -> None:
        last_error: Exception | None = None
        for attempt in range(1, self._cc.APPLY_CONFLICT_RETRIES + 1):
            try:
                self._register_once()
                return
            except self._cc.ConfigCenterError as exc:
                if not self._cc._is_conflict(exc):
                    raise
                last_error = exc
                print(f"[restart_recovery] apply 基线冲突（第 {attempt} 次），重试: {exc}")
                time.sleep(1.0)
        raise last_error  # type: ignore[misc]

    def _register_once(self) -> None:
        workspace = self.load_workspace()
        base_hash = str(workspace.get("hash") or "")
        entry = dict(self.provider_entry)
        entry["models"] = {**self.models}
        draft = self._cc._require_ok(
            *self._cc._api_request(
                self.port,
                "POST",
                "/api/config/draft/providers",
                {
                    "publicConfig": workspace.get("publicConfig") or {},
                    "draftMeta": {"source": "e2e-restart-recovery"},
                    "baseHash": base_hash,
                    "providerId": RECOVERY_PROVIDER_ID,
                    "provider": entry,
                },
            ),
            "POST /api/config/draft/providers (recovery)",
        )
        drafted_config = draft.get("publicConfig")
        self._cc._require_ok(
            *self._cc._api_request(
                self.port,
                "PUT",
                "/api/config/apply",
                {
                    "publicConfig": drafted_config,
                    "draftMeta": {"source": "e2e-restart-recovery"},
                    "baseHash": base_hash,
                    "baseConfig": None,
                },
            ),
            "PUT /api/config/apply (recovery)",
        )
        self._verify_registered()

    def _verify_registered(self) -> None:
        entry = self.current_providers().get(RECOVERY_PROVIDER_ID)
        assert isinstance(entry, dict), (
            f"apply 后未见 {RECOVERY_PROVIDER_ID}: providers={sorted(self.current_providers())}"
        )
        assert str(entry.get("base_url") or "") == self.provider_base_url, (
            f"{RECOVERY_PROVIDER_ID} base_url 不符: {entry.get('base_url')!r} != {self.provider_base_url!r}"
        )

    def ensure_registered(self) -> bool:
        """在场且 base_url 归我 → False；缺失或被劫持 → 重注册并返回 True。"""
        entry = self.current_providers().get(RECOVERY_PROVIDER_ID)
        if isinstance(entry, dict) and str(entry.get("base_url") or "") == self.provider_base_url:
            return False
        if isinstance(entry, dict):
            reason = f"被覆写 base_url={entry.get('base_url')!r}"
        else:
            reason = "缺失"
        print(f"[restart_recovery] {RECOVERY_PROVIDER_ID} {reason}，重新注册")
        self.register()
        return True

    def restore_and_verify(self) -> None:
        last_error: Exception | None = None
        for attempt in range(1, self._cc.APPLY_CONFLICT_RETRIES + 1):
            try:
                self._restore_once()
                self._verify_restored()
                return
            except self._cc.ConfigCenterError as exc:
                if not self._cc._is_conflict(exc):
                    raise
                last_error = exc
                print(f"[restart_recovery] 恢复 apply 基线冲突（第 {attempt} 次），重试: {exc}")
                time.sleep(1.0)
        raise last_error  # type: ignore[misc]

    def _restore_once(self) -> None:
        workspace = self.load_workspace()
        base_hash = str(workspace.get("hash") or "")
        providers = self.current_providers(workspace)
        entry = providers.get(RECOVERY_PROVIDER_ID)
        if not isinstance(entry, dict):
            print(f"[restart_recovery] {RECOVERY_PROVIDER_ID} 已不在配置中，跳过注销")
            return
        drafted = workspace.get("publicConfig") or {}
        models = entry.get("models") or {}
        for model_key in sorted(models):
            drafted = self._cc._require_ok(
                *self._cc._api_request(
                    self.port,
                    "DELETE",
                    f"/api/config/draft/providers/{RECOVERY_PROVIDER_ID}/models/{model_key}",
                    {
                        "publicConfig": drafted,
                        "draftMeta": {"source": "e2e-restart-recovery"},
                        "baseHash": base_hash,
                        "providerId": RECOVERY_PROVIDER_ID,
                        "upstreamId": str((models.get(model_key) or {}).get("upstream_id") or ""),
                        "modelKey": model_key,
                    },
                ),
                f"DELETE draft models/{model_key} (recovery)",
            ).get("publicConfig")
        drafted = self._cc._require_ok(
            *self._cc._api_request(
                self.port,
                "DELETE",
                f"/api/config/draft/providers/{RECOVERY_PROVIDER_ID}",
                {
                    "publicConfig": drafted,
                    "draftMeta": {"source": "e2e-restart-recovery"},
                    "baseHash": base_hash,
                    "providerId": RECOVERY_PROVIDER_ID,
                },
            ),
            "DELETE draft providers (recovery)",
        ).get("publicConfig")
        self._cc._require_ok(
            *self._cc._api_request(
                self.port,
                "PUT",
                "/api/config/apply",
                {
                    "publicConfig": drafted,
                    "draftMeta": {"source": "e2e-restart-recovery"},
                    "baseHash": base_hash,
                    "baseConfig": None,
                },
            ),
            "PUT /api/config/apply (recovery restore)",
        )

    def _verify_restored(self) -> None:
        providers = self.current_providers()
        assert RECOVERY_PROVIDER_ID not in providers, (
            f"恢复后仍存在 {RECOVERY_PROVIDER_ID}（注销失败，保现场待排查）"
        )
        missing = sorted(set(self.snapshot_providers) - set(providers))
        assert not missing, f"快照中的 provider 被外部改动删除: {missing}，需人工核查 config.toml"


def _create_recovery_agent(port: int, display_name: str) -> dict[str, str]:
    """经实例 API 建 Agent（dialogue 绑 e2e-mock-recovery/<key>），返回 ids。

    冷实例首个建 Agent 请求实测可能 >30s：放宽超时并对瞬态错误限次重试
    （与 mock_llm 车道 MockLlmHandle.create_agent 同口径）。
    """
    from tests.e2e.helpers.instance_registry import fetch_json
    from tests.e2e.mock_llm import config_center

    def _post(path: str, payload: dict) -> dict:
        last_exc: Exception | None = None
        status: int | None = None
        result: Any = None
        for _attempt in range(3):
            try:
                status, result = config_center._api_request(port, "POST", path, payload, timeout_seconds=90.0)
                break
            except (TimeoutError, OSError, config_center.ConfigCenterError) as exc:
                last_exc = exc
                time.sleep(2.0)
        assert status is not None and 200 <= status < 300 and isinstance(result, dict), (
            f"POST {path} 失败: HTTP {status} {str(result)[:300]} (last={last_exc})"
        )
        return result

    templates = fetch_json(port, "/api/prompt-templates").get("templates") or []
    template_id = next(
        (str((item or {}).get("templateId") or "").strip() for item in templates
         if str((item or {}).get("templateId") or "").strip()),
        "",
    )
    assert template_id, f"实例无可用提示词模板: {str(templates)[:200]}"
    agent = _post(
        "/api/agents",
        {
            "displayName": display_name,
            "primaryMode": "chat",
            "promptTemplateId": template_id,
            "llmBindings": {"dialogue": {"modelId": recovery_model_ref()}},
        },
    )
    agent_id = str(agent.get("agentId") or "").strip()
    assert agent_id, f"agent 创建响应缺 agentId: {str(agent)[:300]}"
    session_id = str(agent.get("directSessionId") or "").strip()
    if not session_id:
        catalog = fetch_json(port, f"/api/sessions/query?agentId={agent_id}")
        items = catalog.get("items") or catalog.get("sessions") or []
        if items:
            session_id = str(items[0].get("id") or "")
    assert session_id, f"agent {agent_id} 未找到关联会话"
    return {"agentId": agent_id, "sessionId": session_id}


def _delete_recovery_agent(port: int, agent_id: str, *, timeout_seconds: float = 60.0) -> None:
    """teardown 用：归档 + purge 测试 Agent（硬删，连带会话），让 provider 注销
    不被 agent llmBindings 的 live model reference 挡住（与 mock_llm 车道同口径）。"""
    from tests.e2e.mock_llm import config_center

    def _delete(path: str) -> None:
        try:
            config_center._api_request(port, "DELETE", path, timeout_seconds=90.0)
        except (TimeoutError, OSError, config_center.ConfigCenterError) as exc:
            print(f"[restart_recovery] DELETE {path} 瞬态失败，重试: {exc}")

    def _agent_present() -> bool:
        try:
            status, result = config_center._api_request(
                port, "GET", "/api/agents?includeArchived=true", timeout_seconds=30.0
            )
        except (TimeoutError, OSError, config_center.ConfigCenterError):
            return True
        if status != 200 or not isinstance(result, list):
            return True
        return any(str((item or {}).get("agentId") or "") == agent_id for item in result)

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        _delete(f"/api/agents/{agent_id}")
        _delete(f"/api/agents/{agent_id}/purge")
        if not _agent_present():
            return
        time.sleep(2.0)
    print(f"[restart_recovery] 测试 Agent 删除未闭环（仍注册，provider 注销或被挡）: {agent_id}")


@pytest.fixture(scope="module")
def recovery_llm(e2e_instance: Any):
    """模块级 aimock + 独立 provider 注册/注销（横跨实例重启的整生命周期）。

    provider 用本文件专用 id ``e2e-mock-recovery``（RecoveryProviderSession，
    draft→apply 落盘共享 operator config，链路同 mock_llm 车道）；aimock 用共享
    runner.mjs（程序化标记路由，只读复用）。teardown 顺序：先（实例仍在服务时，
    必要时按官方车道拉起）注销 provider 并核对注册前快照，再停 aimock 断言零
    残留；之后父级 session fixture 才停实例。
    """
    from tests.e2e.mock_llm import aimock_runtime

    server = aimock_runtime.start_aimock(
        Path(__file__).resolve().parent / "mock_llm" / "scenarios" / "fixtures",
        script=Path(__file__).resolve().parent / "mock_llm" / "scenarios" / "runner.mjs",
    )
    providers = RecoveryProviderSession(e2e_instance.port, base_url=server.base_url)
    try:
        providers.snapshot()
        providers.register()
    except Exception:
        # 注册失败不泄漏 aimock 进程（apply 失败的现场在异常信息里保出）。
        try:
            server.stop()
            server.assert_stopped()
        except Exception as stop_exc:  # noqa: BLE001 - 不掩盖注册失败原始错误
            print(f"[restart_recovery] 注册失败后的 aimock 补停未闭环: {stop_exc}")
        raise
    handle = SimpleNamespace(
        instance_port=e2e_instance.port,
        server=server,
        providers=providers,
    )
    print(
        f"[restart_recovery] 模块就绪: aimock={server.base_url} "
        f"provider={RECOVERY_PROVIDER_ID} base_url={providers.provider_base_url} "
        f"instance_port={e2e_instance.port}"
    )
    yield handle
    teardown_error: Exception | None = None
    # 用例中途失败可能把实例留在关闭态（如崩溃模拟后、start 前）；provider
    # 注销必须打在活实例上，先按官方车道拉起并刷新端口事实。
    try:
        from tests.e2e.helpers import instance_registry

        instance_registry.fetch_health(handle.instance_port, timeout_seconds=3.0)
    except Exception:  # noqa: BLE001 - 实例不可达即拉起兜底
        try:
            _start_and_reattach(e2e_instance, handle)
        except Exception as exc:  # noqa: BLE001 - 拉起失败不掩盖原始错误
            print(f"[restart_recovery] teardown 前实例拉起失败（保现场）: {exc}")
    try:
        providers.restore_and_verify()
    except Exception as exc:  # noqa: BLE001 - 恢复失败要报告并保现场
        teardown_error = exc
        print(f"[restart_recovery] provider 注销/恢复失败（保现场）: {exc}")
    try:
        server.stop()
        server.assert_stopped()
    except Exception as exc:  # noqa: BLE001 - 进程零残留是硬指标
        print(f"[restart_recovery] aimock 拆机异常: {exc}")
        if teardown_error is None:
            teardown_error = exc
    if teardown_error is not None:
        raise teardown_error


# ---------------------------------------------------------------------------
# 中断与重启编排
# ---------------------------------------------------------------------------


def _require_session_recovery_enabled(handle: Any) -> None:
    """arrange 自检：operator 开关显式关闭时给出可读失败，不让 sweep 静默跳过。

    缺 section/缺字段 = 缺省开（core/session_recovery_flags.py 默认 True）。
    """
    section = ((handle.providers.load_workspace().get("publicConfig") or {}).get("session_recovery")) or {}
    if isinstance(section, dict) and section.get("enabled") is False:
        pytest.fail(
            "operator config 显式关闭了 session_recovery.enabled=false；"
            "重启自动恢复 sweep 会静默跳过，本用例无法执行。请恢复默认开启后重跑。"
        )


def _ensure_provider_registered(handle: Any, *, what: str) -> bool:
    """确保专用 provider 在共享 operator config 中且 base_url 归我；被并发写
    清掉/覆写时重注册（RecoveryProviderSession.ensure_registered）。"""
    return handle.providers.ensure_registered()


def _resolve_data_home(e2e_instance: Any) -> Path:
    """实例数据目录：优先产品解析函数（与父 conftest 同口径），registry 兜底。"""
    try:
        from core.launcher.slot_identity import data_home_for_project

        return Path(data_home_for_project(e2e_instance.project_root))
    except Exception:  # noqa: BLE001 - 解析失败退回 registry/fixture 值
        return Path(e2e_instance.data_home)


def _read_turn_snapshot(e2e_instance: Any, session_id: str) -> dict[str, Any]:
    """读本会话最新的 chat_turn 快照；找不到返回空 dict。"""
    import json as _json

    runs_dir = (
        _resolve_data_home(e2e_instance).parent
        / "runtime" / "runtime-manager" / "work_runs" / "chat_turn" / "runs"
    )
    mine: dict[str, Any] = {}
    if runs_dir.is_dir():
        for path in runs_dir.glob("*.json"):
            try:
                payload = _json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(payload, dict) and str(payload.get("sessionId") or "") == session_id:
                started = str(payload.get("startedAt") or "")
                if not mine or started >= str(mine.get("startedAt") or ""):
                    mine = payload
    return mine


def _wait_turn_snapshot_running(e2e_instance: Any, session_id: str, *, timeout_seconds: float = 5.0) -> dict[str, Any]:
    """等快照进入 active 态（turn 真正运行中）再允许 kill；超时给出可读失败。"""
    deadline = time.monotonic() + timeout_seconds
    snapshot: dict[str, Any] = {}
    while time.monotonic() < deadline:
        snapshot = _read_turn_snapshot(e2e_instance, session_id)
        status = str(snapshot.get("status") or snapshot.get("currentPhase") or "").strip().lower()
        if status in INTERRUPTED_SNAPSHOT_STATUSES and not str(snapshot.get("finishedAt") or "").strip():
            return snapshot
        time.sleep(0.2)
    raise AssertionError(
        f"{timeout_seconds:.0f}s 内未见运行中的 chat_turn 快照（kill 必须落在流式中）: "
        f"{ {k: snapshot.get(k) for k in ('status', 'finishedAt', 'runId')} }"
    )


def _assert_turn_snapshot_active(e2e_instance: Any, session_id: str) -> dict[str, Any]:
    """恢复 sweep 的判据输入：本会话最新 chat_turn 快照 active 且 finishedAt 空。

    与 startup_recovery._open_turn_work_run_is_interrupted 同口径（不复制其
    判定代码，只镜像判据字段），在重启前把「中断态已成立」钉成闸门。
    """
    mine = _read_turn_snapshot(e2e_instance, session_id)
    assert mine, f"未找到会话 {session_id} 的 chat_turn 快照（runs 目录缺失或为空）"
    status = str(mine.get("status") or mine.get("currentPhase") or "").strip().lower()
    assert status in INTERRUPTED_SNAPSHOT_STATUSES, (
        f"中断后快照非 active 态（sweep 判据不成立）: status={status} snapshot={mine}"
    )
    assert not str(mine.get("finishedAt") or "").strip(), (
        f"中断后快照已有 finishedAt（sweep 判据不成立）: {mine}"
    )
    print(f"[restart_recovery] 中断态快照确认: status={status} runId={mine.get('runId')}")
    return mine


def _crash_backend_and_close(e2e_instance: Any) -> None:
    """按 registry 身份核验后硬终止后端进程树（崩溃模拟），再官方 stop 收口。

    身份核验 fail-closed：spawnPid 必须活着、create_time 与 registry
    spawnCreateTime 一致、cmdline 指向本 worktree 的 web_workbench.py；任一不符
    即抛错，绝不终止未验证进程。psutil 全程无窗口（红线合规）。
    """
    import psutil

    from tests.e2e.helpers import instance_registry

    _, entry = instance_registry.find_entry(e2e_instance.project_root)
    pid = int(entry.get("spawnPid") or 0)
    assert pid > 0, f"registry 条目无 spawnPid，无法定位后端进程: {instance_registry.describe_entry(entry)}"
    proc = psutil.Process(pid)
    # 所有权核验（fail-closed）：后端进程的 cmdline 必须指向本 worktree 的
    # web_workbench.py。projectRoot 每实例唯一，满足即证明归属本实例；
    # spawnCreateTime 的单位/语义跨版本不稳（实测 null/数值不一），不作判据。
    worktree = str(e2e_instance.project_root)
    cmdline = " ".join(proc.cmdline()).lower()
    script_ok = "web_workbench.py" in cmdline
    root_ok = worktree.lower() in cmdline
    if not (script_ok and root_ok):
        raise AssertionError(
            f"pid {pid} 身份核验失败（fail-closed，不终止未验证进程）: "
            f"cmdline={cmdline[:300]!r} worktree={worktree!r}"
        )

    victims = [*proc.children(recursive=True), proc]
    for victim in victims:
        try:
            victim.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(victims, timeout=10.0)
    for victim in alive:
        try:
            victim.kill()
        except psutil.NoSuchProcess:
            pass
    print(f"[restart_recovery] 后端进程树已终止: pid={pid} children={len(victims) - 1}")

    # 后端确认下线：旧端口拒绝连接（healthy 轮询报不可达）。
    deadline = time.monotonic() + 20.0
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            instance_registry.fetch_health(e2e_instance.port, timeout_seconds=2.0)
        except instance_registry.InstanceRegistryError as exc:
            last_error = exc
            break
        time.sleep(0.5)
    assert last_error is not None, "终止后旧端口仍健康（后端未下线）"

    # 对 dead spawn 的 registry 条目走官方 stop：身份核对 + reconcile → closed。
    from tests.e2e.helpers import launcher

    launcher.stop_instance(e2e_instance.project_root)
    closed_entry = instance_registry.wait_for_entry(
        e2e_instance.project_root,
        instance_registry.entry_is_closed,
        timeout_seconds=CLOSED_TIMEOUT_SECONDS,
        what="实例关闭（崩溃模拟后的 registry reconcile）",
    )
    print(f"[restart_recovery] registry 收口完成: {instance_registry.describe_entry(closed_entry)}")


def _start_and_reattach(e2e_instance: Any, handle: Any) -> int:
    """官方 launcher start，并重读 registry 刷新端口事实；返回新端口。"""
    from tests.e2e.helpers import instance_registry, launcher

    try:
        launcher.start_instance(e2e_instance.project_root)
    except launcher.LauncherCommandError as exc:
        # 实测（2026-09-26）：冷壳时 start 的 bridge 结算窗口（90s）可能先于
        # registry steady 到点而退出码 3，但实例随后照常就绪。真正就绪口径是
        # registry ready + health 二次确认，这里不因结算超时误杀重启编排。
        print(f"[restart_recovery] start 结算报错（继续等 registry 就绪口径）: {exc}")
    entry = instance_registry.wait_for_entry(
        e2e_instance.project_root,
        instance_registry.entry_is_ready,
        timeout_seconds=READY_TIMEOUT_SECONDS,
        what="实例重启就绪（steady/open + 端口租约 held）",
    )
    port = int(entry["port"])
    health = instance_registry.fetch_health(port)
    instance_registry.assert_health_serves_worktree(health, e2e_instance.project_root)
    # 端口可能随重启迁移：同步刷新 session fixture 与 provider 句柄上的端口，
    # 后续 DOM 断言（e2e_instance.base_url）与 teardown 注销（center.port）都打新端口。
    e2e_instance.port = port
    e2e_instance.base_url = f"http://127.0.0.1:{port}"
    e2e_instance.instance_id = str(entry.get("instanceId") or e2e_instance.instance_id)
    e2e_instance.data_home = str(entry.get("dataHome") or e2e_instance.data_home)
    e2e_instance.health = health
    handle.instance_port = port
    handle.providers.port = port
    print(
        f"[restart_recovery] start 完成: port={port} "
        f"generation={entry.get('generation')} instanceId={e2e_instance.instance_id}"
    )
    return port


def _is_title_entry(entry: dict[str, Any]) -> bool:
    """journal 条目是否为标题生成等辅助调用（口径同 mock_llm 车道）。

    辅助调用 body 小、末条 user content 以「用户消息：」开头；主调用 body 超过
    journal 64KB 上限时条目里 body 为空（None）——按非辅助（主调用）计。
    """
    body = entry.get("body") or {}
    msgs = body.get("messages") or []
    for m in reversed(msgs):
        if (m or {}).get("role") == "user":
            return str((m or {}).get("content") or "").lstrip().startswith("用户消息：")
    return False


def _journal_main_counts(handle: Any) -> tuple[int, int]:
    """返回 (主调用条目数, journal 总条数)（只看 /v1/chat/completions）。"""
    entries = handle.server.journal(path="/v1/chat/completions")
    return sum(1 for e in entries if not _is_title_entry(e)), len(entries)


def _wait_first_main_call(handle: Any, *, timeout_seconds: float = 60.0) -> tuple[int, int]:
    """等首条主调用（非标题等辅助调用）到达 aimock，返回 (mains, journal 长度)。

    实测：wait_turn_started 的 stage 证据（user_submit → thinking）早于 LLM 请求
    发出，turn 启动后主调用还要经上下文装配才到 mock，必须显式轮询。
    """
    deadline = time.monotonic() + timeout_seconds
    mains, total = _journal_main_counts(handle)
    while mains < 1 and time.monotonic() < deadline:
        time.sleep(0.5)
        mains, total = _journal_main_counts(handle)
    return mains, total


def _wait_resumed_main_call(
    handle: Any,
    *,
    mains_before: int,
    journal_len_before: int,
    timeout_seconds: float = RESUMED_MAIN_CALL_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """等重启后的新主调用到达 aimock（整轮重发的 journal 证据）。

    sweep 在 workbench lifespan 就绪后触发 resume submit；轮次引擎随后向 mock
    发起主调用。这里轮询「非辅助调用条目增长」+「重启段存在 200 完成的
    e2e-mock 模型条目」（标记匹配只作软证据：主调用 body 可能超 aimock journal
    64KB 上限而 body 落 None，见 test_mock_llm_flow.journal_main_counts 注释）。
    """
    deadline = time.monotonic() + timeout_seconds
    entries: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        entries = handle.server.journal(path="/v1/chat/completions")
        post_restart = entries[journal_len_before:]
        # 重发主调用判据：重启段 200 完成 + 非标题辅助调用。实测产品主调用 body
        # 的 model 字段可以是空串（原始主调用同为空串，标题辅助调用反而带
        # e2e-mock-chat），所以这里不能按 model 白名单筛，只按 200 + 非辅助筛。
        resumed_200 = [
            entry
            for entry in post_restart
            if int(entry.get("response", {}).get("status") or 0) == 200
            and not _is_title_entry(entry)
        ]
        if resumed_200:
            mains, total = _journal_main_counts(handle)
            print(
                f"[restart_recovery] 重发主调用到达: mains={mains}（重启前 {mains_before}） "
                f"journal total={total} 重启段 200 条目={len(resumed_200)}"
            )
            return {
                "entries": entries,
                "post_restart": post_restart,
                "resumed_200": resumed_200,
                "mains_after": mains,
            }
        time.sleep(1.0)
    entries = handle.server.journal(path="/v1/chat/completions")
    provider_entry = handle.providers.current_providers().get(RECOVERY_PROVIDER_ID) or {}
    dump = [
        {
            "status": int(e.get("response", {}).get("status") or 0),
            "model": str(e.get("body", {}).get("model") or ""),
            "is_title": _is_title_entry(e),
            "body_none": e.get("body") is None,
        }
        for e in entries
    ]
    raise AssertionError(
        f"重启后 {timeout_seconds:.0f}s 内未见重发主调用到达 aimock "
        f"（mains_before={mains_before}，journal 现长={len(entries)}，entries={dump}，"
        f"provider_base_url={provider_entry.get('base_url')!r}，"
        f"my_base_url={handle.providers.provider_base_url!r}）——startup sweep 未重发该轮"
    )


def _thread_message_count(page: Any) -> int:
    try:
        raw = page.locator(
            'div[data-agent-thread-message-count]'
        ).first.get_attribute("data-agent-thread-message-count", timeout=2_000) or "0"
    except Exception:  # noqa: BLE001 - 元素瞬时分离按 0 处理，交给上层轮询
        return 0
    try:
        return int(raw)
    except ValueError:
        return 0


# ---------------------------------------------------------------------------
# 用例
# ---------------------------------------------------------------------------


def test_restart_mid_stream_resumes_turn(
    page: Any,
    e2e_instance: Any,
    recovery_llm: Any,
) -> None:
    """流式中后端进程死亡 → 重启 → 整轮重发 + 恢复状态行 + 收口不膨胀（P1 主契约）。

    排序说明：本用例自带模块级 aimock/provider 生命周期，与 mock_llm 车道的
    session 级 fixture 互不可见；共享 operator config 上同 id provider 的注册按
    「先注册者先注销」串行衔接（本文件字母序在 mock_llm 之后，届时其注册已由
    自愈/恢复链让位）。
    """
    from tests.e2e.mock_llm.test_mock_llm_flow import (
        assert_no_error_surface,
        open_agent_chat,
        send_message,
        thread_text,
        wait_turn_closed,
        wait_turn_started,
    )

    _require_session_recovery_enabled(recovery_llm)
    created = _create_recovery_agent(e2e_instance.port, "E2E Restart Recovery Agent")
    try:
        # --- arrange：低速流式轮进流中 --------------------------------------
        open_agent_chat(page, e2e_instance, created["sessionId"])
        recovery_llm.server.reset_journal()
        send_message(page, SUBMIT_TEXT)
        assert wait_turn_started(
            page, recovery_llm, submit_text=SUBMIT_TEXT, timeout_ms=20_000
        ), "turn 未启动（主调用未到 mock 且 stage 未推进）"
        mains_before, journal_len_before = _wait_first_main_call(recovery_llm)
        assert mains_before >= 1, (
            f"中断前主调用未到 mock（journal mains={mains_before}）——interrupt 前提不成立"
        )
        # ttft 0.5s + tps 8：再等一小段确保中断落在流式窗口内（约 30s 流长）。
        time.sleep(STREAMING_SETTLE_SECONDS)
        partial_visible = "0123456789" in thread_text(page)
        # 共享 operator config 有本机其他实例/页面的活跃并发写（apply 409 实测），
        # 中断前最后校验一次在场，把窗口内的暴露面压到最小。
        _ensure_provider_registered(recovery_llm, what="中断前")
        print(
            f"[restart_recovery] 中断前事实: mains={mains_before} "
            f"journal_len={journal_len_before} 半截上屏={partial_visible}（软证据，不作闸门）"
        )

        # --- act：崩溃模拟（中断）→ 官方 stop 收口 + start（恢复） ----------
        # kill 前置闸门：快照已进 active 态（turn 运行中），kill 必然落在轮内。
        _wait_turn_snapshot_running(e2e_instance, created["sessionId"])
        _crash_backend_and_close(e2e_instance)
        _assert_turn_snapshot_active(e2e_instance, created["sessionId"])
        _start_and_reattach(e2e_instance, recovery_llm)

        # --- 重启后 provider 在场（并发写竞态自愈 + 一次完整重试） ----------
        # sweep 在 lifespan 就绪后立刻提交 resume；若注册恰在重启窗口被并发写
        # 覆盖，重发主调用会缺席（provider 解析失败，原 open turn 保留、重试
        # 预算烧 1 次/上限 2），此时完整重试一次中断→重启编排。
        resumed: dict[str, Any] | None = None
        for attempt in (1, 2):
            provider_wiped = _ensure_provider_registered(recovery_llm, what=f"重启后（第 {attempt} 次）")
            try:
                resumed = _wait_resumed_main_call(
                    recovery_llm,
                    mains_before=mains_before,
                    journal_len_before=journal_len_before,
                    timeout_seconds=RESUMED_MAIN_CALL_POLL_SECONDS,
                )
                break
            except AssertionError:
                if attempt == 1 and provider_wiped:
                    print(
                        "[restart_recovery] 重启窗口内 provider 被并发写覆盖且重发主调用未到，"
                        "完整重试一次中断→重启编排"
                    )
                    _crash_backend_and_close(e2e_instance)
                    _start_and_reattach(e2e_instance, recovery_llm)
                    continue
                raise

        # --- assert 1：整轮重发（aimock journal 主调用再次到达） -------------
        assert resumed is not None
        assert resumed["mains_after"] >= mains_before + 1, (
            f"重发主调用条目未增长: before={mains_before} after={resumed['mains_after']}"
        )

        # --- assert 2：恢复状态行（contract kind=session_recovery_resumed） --
        open_agent_chat(page, e2e_instance, created["sessionId"])
        recovery_row = page.locator(RECOVERY_ROW_ANCHOR).filter(has_text=RECOVERY_ROW_TEXT)
        recovery_row.first.wait_for(state="visible", timeout=RECOVERY_ROW_TIMEOUT_MS)

        # --- assert 3：重发轮正常收口 + 消息计数不重复膨胀 -------------------
        wait_turn_closed(
            page,
            expected_messages=EXPECTED_THREAD_MESSAGES,
            timeout_ms=RESUMED_TURN_CLOSE_TIMEOUT_MS,
        )
        assert_no_error_surface(page)
        texts = thread_text(page)
        final_count = _thread_message_count(page)
        row_dump = page.locator(
            'div[data-agent-thread-message-count] [data-conversation-row-key]'
        )
        rows = []
        for i in range(min(row_dump.count(), 12)):
            try:
                rows.append(row_dump.nth(i).inner_text()[:60].replace("\n", "|"))
            except Exception:  # noqa: BLE001 - 行瞬时分离跳过
                continue
        print(f"[restart_recovery] 时间线逐行: {rows}")
        print(
            f"[restart_recovery] 收口事实: count={final_count}（pin {EXPECTED_THREAD_MESSAGES}） "
            f"重发回复上屏={'0123456789' in texts} 恢复行可见={recovery_row.first.is_visible()} "
            f"恢复行数={recovery_row.count()}"
        )
        assert final_count == EXPECTED_THREAD_MESSAGES, (
            f"收口后时间线计数漂移（重复 user 行缺陷候选的观测口径，见常量注释）: "
            f"count={final_count} 预期={EXPECTED_THREAD_MESSAGES} 时间线尾部={texts[-400:]!r}"
        )
        # 无界膨胀闸门：重发链不得循环制造行（有界 + 恰一条恢复状态行）。
        assert recovery_row.count() == 1, (
            f"恢复状态行数异常: {recovery_row.count()}（应为恰 1 条）"
        )
        assert "0123456789" in texts, f"重发轮最终回复未上时间线: {texts[-300:]!r}"
        # 恢复行 detail（<code>）应带原轮首行 turnLabel（startup_recovery 语义）。
        row_text = recovery_row.first.inner_text()
        print(f"[restart_recovery] 恢复状态行文本: {row_text!r}")
    finally:
        _delete_recovery_agent(e2e_instance.port, created["agentId"])
