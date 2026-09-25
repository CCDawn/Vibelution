# -*- coding: utf-8 -*-
"""配置中心会话级 provider 注册/注销（draft → apply，控制令牌口径）。

链式口径（对照 core/web/routes/config.py 与 web/src/routes/config/configApplyModel.ts）：
1. ``GET /api/config/workspace`` → ``publicConfig`` + ``hash``（即磁盘基线 hash）；
2. ``POST /api/config/draft/providers``（body 带 ``publicConfig/draftMeta/baseHash/
   providerId/provider``）→ 返回草稿 workspace（含新 ``publicConfig``）；
3. ``PUT /api/config/apply``（``publicConfig=`` 草稿、``baseHash=`` **磁盘基线** hash、
   ``baseConfig=null``）→ 落盘 operator config.toml；
4. 注销对称：unpin 模型（``DELETE /config/draft/providers/{id}/models/{key}``）→
   删 provider（``DELETE /config/draft/providers/{id}``）→ apply → 与注册前快照核对。

apply 会写**共享的** operator config（%USERPROFILE%\\Documents\\Vibelution\\config\\
config.toml），因此注册前必须深拷贝快照 provider 列表，teardown 恢复并精确核对；
apply 失败要报告并保现场（不静默吞掉）。
"""

from __future__ import annotations

import copy
import json
import time
import urllib.error
import urllib.request
from typing import Any

from tests.e2e.helpers.instance_registry import control_token

CONTROL_TOKEN_HEADER = "X-Vibelution-Control-Token"

MOCK_PROVIDER_ID = "e2e-mock"
MOCK_CHAT_MODEL_KEY = "e2e-mock-chat"
MOCK_TOOLS_MODEL_KEY = "e2e-mock-tools"

# 与 scenarios/fixtures 的上游模型名（upstream_id）对齐：aimock /v1/models 由
# fixture 合成探活用，产品发送的 model 字段即这里的 upstream_id。
MOCK_PROVIDER_MODELS: dict[str, dict[str, Any]] = {
    MOCK_CHAT_MODEL_KEY: {
        "upstream_id": MOCK_CHAT_MODEL_KEY,
        "label": "E2E Mock Chat (aimock)",
        "wire_protocol": "chat_completions",
        "interaction_contract": "tool_chat",
        # 显式声明协议：chat turn 会绑定工具，协议名不可识别会被兜底成
        # basic_chat_no_tools 并以 capability_error 拦截本轮（实测 transcripts）。
        "model_protocol": "openai_chat_tools",
        "context_window": 32768,
        "defaults": {"timeout": 90, "connect_timeout": 20, "streaming": True},
    },
    MOCK_TOOLS_MODEL_KEY: {
        "upstream_id": MOCK_TOOLS_MODEL_KEY,
        "label": "E2E Mock Tools (aimock)",
        "wire_protocol": "chat_completions",
        "interaction_contract": "tool_chat",
        "model_protocol": "openai_chat_tools",
        "context_window": 32768,
        "defaults": {"timeout": 90, "connect_timeout": 20, "streaming": True},
    },
}


class ConfigCenterError(RuntimeError):
    """配置中心 draft/apply 流程失败（含保现场信息）。"""


APPLY_CONFLICT_RETRIES = 3


def _is_conflict(exc: Exception) -> bool:
    """共享 operator config 的并发写冲突（其他实例/页面同时 apply）。"""
    return "HTTP 409" in str(exc)


def mock_provider_entry(base_url: str) -> dict[str, Any]:
    """e2e-mock provider 条目（canonical v2 字段集）。

    - base_url 必须带 ``/v1`` 前缀（aimock models 探活在 ``/v1/models``，
      ``/provider/v1`` 前缀会让探活 404）；
    - 127.0.0.1 + http 只允许 local 类：v2 形状下 service_class=local_runtime 之外，
      运行时 legacy kind 由 deployment.runtime_framework 决定（framework 优先于
      vendor/driver）。必须显式给 runtime_framework=local，否则 legacy kind 解析成
      "openai"，localhost SSRF 守卫会在运行时拒绝所有请求（实测：chat 全部
      network_error、probe 报 “targets localhost but provider kind is not local”）。
    - vendor=custom + driver=openai → 运行时 legacy kind="openai"（litellm
      openai/ 前缀 + api_base，spike 已实测穿透）；
    - 无凭据：aimock 不校验 Authorization，``auth_kind=none`` + ``requires_credential=false``
      使运行时 key 为空（local 预设同款口径）。
    """
    return {
        "kind": "",
        "label": "E2E Mock LLM (aimock)",
        "vendor": "custom",
        "driver": "openai",
        "service_class": "local_runtime",
        "auth_kind": "none",
        "requires_credential": False,
        "credential_ref": "",
        "base_url": base_url,
        "compat_mode": "openai",
        "context_window": 32768,
        "deployment": {"runtime_framework": "local"},
        "protocols": {"default": "chat_completions", "allowed": ["chat_completions"]},
        "discovery": {"mode": "manual", "adapter": "manual"},
        "models": copy.deepcopy(MOCK_PROVIDER_MODELS),
    }


def model_ref(model_key: str) -> str:
    return f"{MOCK_PROVIDER_ID}/{model_key}"


# ---------------------------------------------------------------------------
# HTTP（控制令牌）
# ---------------------------------------------------------------------------


def _api_request(
    port: int,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout_seconds: float = 30.0,
) -> tuple[int, Any]:
    """带控制令牌的实例 API 调用；403 自动刷新令牌重试一次（与 fetch_json 同口径）。"""
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json", "Content-Type": "application/json"}

    def _once(token: str) -> tuple[int, Any]:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            data=body,
            method=method,
            headers={**headers, CONTROL_TOKEN_HEADER: token},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read().decode("utf-8")
                return int(response.status), (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(raw)
            except ValueError:
                detail = raw[:400]
            return int(exc.code), detail
        except (urllib.error.URLError, OSError) as exc:
            raise ConfigCenterError(f"{method} {path} 不可达: {exc}") from exc

    status, result = _once(control_token(port))
    if status == 403:
        status, result = _once(control_token(port, refresh=True))
    return status, result


def _require_ok(status: int, result: Any, what: str) -> dict[str, Any]:
    if status < 200 or status >= 300 or not isinstance(result, dict):
        raise ConfigCenterError(
            f"{what} 失败：HTTP {status}，响应={json.dumps(result, ensure_ascii=False)[:600]}"
        )
    return result


# ---------------------------------------------------------------------------
# 注册 / 快照 / 恢复
# ---------------------------------------------------------------------------


class ConfigCenterSession:
    """一个实例上的配置中心会话：快照 → 注册 e2e-mock → 恢复并核对。"""

    def __init__(self, port: int, *, base_url: str) -> None:
        self.port = port
        # provider base_url 必须带 /v1（aimock models 探活与 chat/completions 都在
        # /v1 前缀下；normalize_provider_endpoint 会保留 path，实测不会被剥掉）。
        self.base_url = base_url.rstrip("/").removesuffix("/v1")
        self.provider_base_url = f"{self.base_url}/v1"
        self.snapshot_providers: dict[str, Any] = {}
        self.snapshot_hash: str = ""

    # -- 读 -------------------------------------------------------------------

    def load_workspace(self) -> dict[str, Any]:
        status, result = _api_request(self.port, "GET", "/api/config/workspace")
        return _require_ok(status, result, "GET /api/config/workspace")

    def current_providers(self, workspace: dict[str, Any] | None = None) -> dict[str, Any]:
        workspace = workspace or self.load_workspace()
        llm = workspace.get("publicConfig", {}).get("llm", {})
        providers = llm.get("providers", {})
        return providers if isinstance(providers, dict) else {}

    # -- 注册 -----------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """注册前快照 provider 列表（深拷贝）+ 磁盘基线 hash。

        若发现上次会话残留的 e2e-mock（label 同源），先自愈注销再快照；非同源
        同名 provider 视为手工现场，拒绝覆盖。
        """
        workspace = self.load_workspace()
        providers = self.current_providers(workspace)
        orphan = providers.get(MOCK_PROVIDER_ID)
        if isinstance(orphan, dict):
            if str(orphan.get("label") or "") != str(mock_provider_entry("http://127.0.0.1:0/v1").get("label")):
                raise ConfigCenterError(
                    f"注册前已存在非本车道创建的 {MOCK_PROVIDER_ID} provider，拒绝覆盖；请先清理现场再跑。"
                )
            print(f"[mock_llm] 发现上次会话残留的 {MOCK_PROVIDER_ID}，先自愈注销")
            # 自愈基线 = 当前 provider 减去残留 e2e-mock；注销后据此核对。
            self.snapshot_providers = copy.deepcopy(
                {key: value for key, value in providers.items() if key != MOCK_PROVIDER_ID}
            )
            self.restore_and_verify()
            workspace = self.load_workspace()
            providers = self.current_providers(workspace)
        self.snapshot_providers = copy.deepcopy(providers)
        self.snapshot_hash = str(workspace.get("hash") or "")
        return self.snapshot_providers

    def register(self) -> dict[str, Any]:
        """draft 注册 e2e-mock → apply 落盘 → 回读核对。

        operator config 是多实例共享的（并行的其他 e2e 实例也可能 apply），
        baseHash 冲突时重读最新基线整链重试。
        """
        last_error: ConfigCenterError | None = None
        for attempt in range(1, APPLY_CONFLICT_RETRIES + 1):
            try:
                return self._register_once()
            except ConfigCenterError as exc:
                if not _is_conflict(exc):
                    raise
                last_error = exc
                print(f"[mock_llm] apply 基线冲突（第 {attempt} 次），重读配置重试: {exc}")
                time.sleep(1.0)
        raise last_error  # type: ignore[misc]

    def _register_once(self) -> dict[str, Any]:
        workspace = self.load_workspace()
        base_hash = str(workspace.get("hash") or "")
        if not base_hash:
            raise ConfigCenterError("workspace 未返回 hash，无法作为 baseHash")
        draft = _require_ok(
            *_api_request(
                self.port,
                "POST",
                "/api/config/draft/providers",
                {
                    "publicConfig": workspace.get("publicConfig") or {},
                    "draftMeta": {"source": "e2e-mock-llm"},
                    "baseHash": base_hash,
                    "providerId": MOCK_PROVIDER_ID,
                    "provider": mock_provider_entry(self.provider_base_url),
                },
            ),
            "POST /api/config/draft/providers",
        )
        drafted_config = draft.get("publicConfig")
        if not isinstance(drafted_config, dict):
            raise ConfigCenterError(f"草稿响应缺 publicConfig: {json.dumps(draft)[:400]}")
        providers = self.current_providers(draft)
        if MOCK_PROVIDER_ID not in providers:
            raise ConfigCenterError(f"草稿未见 {MOCK_PROVIDER_ID}: providers={sorted(providers)}")
        applied = _require_ok(
            *_api_request(
                self.port,
                "PUT",
                "/api/config/apply",
                {
                    "publicConfig": drafted_config,
                    "draftMeta": {"source": "e2e-mock-llm"},
                    "baseHash": base_hash,
                    "baseConfig": None,
                },
            ),
            "PUT /api/config/apply",
        )
        return self._verify_registered(applied)

    def _verify_registered(self, applied: dict[str, Any]) -> dict[str, Any]:
        providers = self.current_providers(applied)
        entry = providers.get(MOCK_PROVIDER_ID)
        if not isinstance(entry, dict):
            raise ConfigCenterError(
                f"apply 后回读未见 {MOCK_PROVIDER_ID}（apply 失败，保现场）：providers={sorted(providers)}"
            )
        expected_base = self.provider_base_url
        actual_base = str(entry.get("base_url") or "")
        if actual_base != expected_base:
            raise ConfigCenterError(f"apply 后 base_url 不符: {actual_base!r} != {expected_base!r}")
        models = entry.get("models") or {}
        missing = sorted(set(MOCK_PROVIDER_MODELS) - set(models))
        if missing:
            raise ConfigCenterError(f"apply 后缺模型: {missing}")
        print(
            f"[mock_llm] provider {MOCK_PROVIDER_ID} 已注册: base_url={actual_base} "
            f"models={sorted(models)}"
        )
        return entry

    # -- 恢复 -----------------------------------------------------------------

    def restore_and_verify(self) -> dict[str, Any]:
        """注销 e2e-mock 并 apply，然后核对恢复。

        并发写冲突（共享 operator config）时重读基线整链重试；核对语义：
        - 硬失败：e2e-mock 仍存在；
        - 硬失败：快照里的 provider 被删掉；
        - 外部并发新增/修改的 key 打印为证据，不算本车道失败。
        """
        last_error: ConfigCenterError | None = None
        for attempt in range(1, APPLY_CONFLICT_RETRIES + 1):
            try:
                self._restore_once()
                return self._verify_restored()
            except ConfigCenterError as exc:
                if not _is_conflict(exc):
                    raise
                last_error = exc
                print(f"[mock_llm] 恢复 apply 基线冲突（第 {attempt} 次），重试: {exc}")
                time.sleep(1.0)
        raise last_error  # type: ignore[misc]

    def _restore_once(self) -> None:
        workspace = self.load_workspace()
        base_hash = str(workspace.get("hash") or "")
        providers = self.current_providers(workspace)
        entry = providers.get(MOCK_PROVIDER_ID)
        if not isinstance(entry, dict):
            print(f"[mock_llm] {MOCK_PROVIDER_ID} 已不在配置中，跳过注销")
            return

        drafted = workspace.get("publicConfig") or {}
        # 1) provider 必须先 unpin 全部模型（draft_delete_provider 的前置条件）。
        models = entry.get("models") or {}
        for model_key in sorted(models):
            drafted = _require_ok(
                *_api_request(
                    self.port,
                    "DELETE",
                    f"/api/config/draft/providers/{MOCK_PROVIDER_ID}/models/{model_key}",
                    {
                        "publicConfig": drafted,
                        "draftMeta": {"source": "e2e-mock-llm"},
                        "baseHash": base_hash,
                        "providerId": MOCK_PROVIDER_ID,
                        "upstreamId": str((models.get(model_key) or {}).get("upstream_id") or ""),
                        "modelKey": model_key,
                    },
                ),
                f"DELETE draft models/{model_key}",
            ).get("publicConfig")
        # 2) 删 provider。
        drafted = _require_ok(
            *_api_request(
                self.port,
                "DELETE",
                f"/api/config/draft/providers/{MOCK_PROVIDER_ID}",
                {
                    "publicConfig": drafted,
                    "draftMeta": {"source": "e2e-mock-llm"},
                    "baseHash": base_hash,
                    "providerId": MOCK_PROVIDER_ID,
                },
            ),
            "DELETE draft providers/e2e-mock",
        ).get("publicConfig")
        # 3) apply 落盘。
        _require_ok(
            *_api_request(
                self.port,
                "PUT",
                "/api/config/apply",
                {
                    "publicConfig": drafted,
                    "draftMeta": {"source": "e2e-mock-llm"},
                    "baseHash": base_hash,
                    "baseConfig": None,
                },
            ),
            "PUT /api/config/apply (restore)",
        )

    def _verify_restored(self, providers: dict[str, Any] | None = None) -> dict[str, Any]:
        providers = providers if providers is not None else self.current_providers()
        if MOCK_PROVIDER_ID in providers:
            raise ConfigCenterError(
                f"恢复后仍存在 {MOCK_PROVIDER_ID}（注销失败，保现场待排查）"
            )
        missing = sorted(set(self.snapshot_providers) - set(providers))
        if missing:
            raise ConfigCenterError(
                f"快照中的 provider 被外部改动删除: {missing}，需要人工核查 config.toml"
            )
        drifted = sorted(
            key for key in self.snapshot_providers
            if key in providers and providers[key] != self.snapshot_providers[key]
        )
        extras = sorted(set(providers) - set(self.snapshot_providers))
        # operator config 多实例共享：外部并发新增/修改不算本车道残留，打印留证。
        if drifted or extras:
            print(
                f"[mock_llm] 检测到并发外部配置改动（非本车道）：drifted={drifted} extras={extras}"
            )
        print(f"[mock_llm] e2e-mock 已注销；快照 provider 全部在位: {sorted(providers) or '(空)'}")
        return providers
