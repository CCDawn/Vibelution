# -*- coding: utf-8 -*-
"""e2e 群聊（group conversation，多 agent 会话）主流程：UI 建群 + 成员归属 + 多轮完整。

车道口径（照抄 test_mock_llm_flow.py 的约定）：
- ``serial`` marker + ``skipif`` 环境门（VIBELUTION_E2E=1 才运行）；
- 本文件**自包含**：aimock 剧本（runner.mjs）在 fixture 里运行时生成到系统临时目录，
  provider ``e2e-mock-group``（模型 e2e-mock-group-a / -b）用配置中心 draft/apply
  注册，teardown 注销并核对零残留（不与共享 e2e-mock 车道共用剧本与端口）；
- 成员 agent 经实例 API 创建（dialogue 槽分别绑到两个 mock 模型），群聊经 UI 创建
  （chat 左栏「新建任务 → 新建群聊」），议题经群聊 composer 发送（启动一轮）；
- 断言锚点（web/src/routes/chat/ChatGroupCenterSurface.tsx）：
  * 轮次块 ``section[data-group-round-id="<roundId>"]``，divider 文案「发言已结束」；
  * 议题行 ``[data-testid="group-stream-topic-identity"]``；
  * 发言身份行 ``[data-testid="group-stream-identity"]``（每人每轮首条发言一行，
    显示 identityLabel = 成员显示名）；
  * 排队/输入状态：运行中的 pending 发言行 trailing 文案「等待发言」/「正在输入」。

产品事实（探索结论，2026-09-28）：
- 房间 API：POST/GET/DELETE /api/chat-rooms，POST /chat-rooms/{id}/rounds 后台跑轮；
  round_robin 串行按 participants 顺序发言，speaker LLM 用成员 agent 的 dialogue 槽；
- 成员 prompt（core/web/services/chat_room_service.py _build_participant_prompt）含
  「当前议题: <topic>」与「你的界面代号: <agentCode>」行——runner 用前者路由轮次、
  用后者区分发言者（取最后一次出现；第二轮起 prior 发言会引用其他成员正文）；
- round 终态 completed/partial/failed/stopped；本轮 messages 全量落盘后前端经
  chat-rooms/{id}/events SSE 收快照。
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest

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

PROVIDER_ID = "e2e-mock-group"
MODEL_A = "e2e-mock-group-a"
MODEL_B = "e2e-mock-group-b"
# context_window 用 32768：群聊 speaker 轮走 v2 prompt 装配（分层预算硬闸），
# STABLE_CORE 层预算 = max(3000, window*0.05)，本仓库 AGENTS.md 段实测 ~3063
# tokens，32768 窗口下预算 3000 直接 protected_tier_over_budget（实测 run3）。
# 历史上这条车道被迫声明 200k 大窗口绕闸；核心快照 seed 对齐直聊后，speaker
# 的核心三文件由 session 快照承载并移出 PromptManager 装配预算，32k 小窗口
# 真实可过。本文件因此回归钉 32768：seed 失效即整车道发言失败（原始复现场景）。
GROUP_CONTEXT_WINDOW = 32_768
PROVIDER_MODELS: dict[str, dict[str, Any]] = {
    MODEL_A: {
        "upstream_id": MODEL_A,
        "label": "E2E Group Speaker A (aimock)",
        "wire_protocol": "chat_completions",
        "interaction_contract": "tool_chat",
        "model_protocol": "openai_chat_tools",
        "context_window": GROUP_CONTEXT_WINDOW,
        "defaults": {"timeout": 120, "connect_timeout": 20, "streaming": True},
    },
    MODEL_B: {
        "upstream_id": MODEL_B,
        "label": "E2E Group Speaker B (aimock)",
        "wire_protocol": "chat_completions",
        "interaction_contract": "tool_chat",
        "model_protocol": "openai_chat_tools",
        "context_window": GROUP_CONTEXT_WINDOW,
        "defaults": {"timeout": 120, "connect_timeout": 20, "streaming": True},
    },
}

MEMBER_A_NAME = "E2E群聊成员A"
MEMBER_B_NAME = "E2E群聊成员B"

TOPIC_R1 = "E2E-GROUP-R1 请各位确认到场"
TOPIC_R2 = "E2E-GROUP-R2 请补充风险提示"
TOPIC_R3 = "E2E-GROUP-R3 观察排队状态"

REPLY_R1 = "第一轮发言：{code} 已到场，确认群聊链路正常。"
REPLY_R2 = "第二轮发言：{code} 补充风险提示：成员归属回归已就位。"
REPLY_R3_SLOW = "第三轮发言：{code} 慢速发言，用于暴露排队状态。"
REPLY_R3_FAST = "第三轮发言：{code} 快速收尾。"

ROUND_TERMINAL_STATUSES = {"completed", "partial", "failed", "stopped"}
ROUND_TERMINAL_TIMEOUT_S = 180.0

TOPIC_INPUT_PLACEHOLDER = "输入下一轮群聊议题"
IDENTITY_ROW = '[data-testid="group-stream-identity"]'
TOPIC_IDENTITY_ROW = '[data-testid="group-stream-topic-identity"]'


# ---------------------------------------------------------------------------
# 共享基础设施（自包含：不修改 tests/e2e/mock_llm/conftest.py 的共享 fixture）
# ---------------------------------------------------------------------------


def _api(port: int, method: str, path: str, payload: dict | None = None, *, timeout_seconds: float = 60.0):
    from tests.e2e.mock_llm.config_center import _api_request

    return _api_request(port, method, path, payload, timeout_seconds=timeout_seconds)


def _post_ok(port: int, path: str, payload: dict, *, what: str, timeout_seconds: float = 90.0) -> dict:
    """建资源类 POST：冷实例首请求实测可能 >30s，带瞬态重试（与共享车道同口径）。"""
    from tests.e2e.mock_llm.config_center import ConfigCenterError

    last_exc: Exception | None = None
    for _attempt in range(3):
        try:
            status, result = _api(port, "POST", path, payload, timeout_seconds=timeout_seconds)
        except (TimeoutError, OSError, ConfigCenterError) as exc:
            last_exc = exc
            time.sleep(2.0)
            continue
        if 200 <= status < 300 and isinstance(result, dict):
            return result
        raise RuntimeError(f"{what} 失败: HTTP {status} {str(result)[:300]}")
    raise RuntimeError(f"{what} 连续失败（瞬态重试耗尽）: {last_exc}")


def _group_provider_entry(base_url: str) -> dict[str, Any]:
    """e2e-mock-group provider 条目；字段集照抄共享车道 canonical v2 形状
    （local runtime_framework 必须显式声明，否则 localhost SSRF 守卫拦全部请求）。"""
    from tests.e2e.mock_llm.config_center import mock_provider_entry

    entry = mock_provider_entry(base_url)
    entry["label"] = "E2E Mock Group LLM (aimock)"
    entry["models"] = json.loads(json.dumps(PROVIDER_MODELS))
    return entry


class GroupProviderSession:
    """配置中心会话：快照 → 注册 e2e-mock-group → 恢复并核对（零残留）。

    与共享 config_center.ConfigCenterSession 同链路（draft → apply，控制令牌），
    但 provider id 独占本车道，注册/注销逻辑按本车道参数自包含实现。
    """

    def __init__(self, port: int, *, base_url: str) -> None:
        from tests.e2e.mock_llm.config_center import ConfigCenterError

        self._ConfigCenterError = ConfigCenterError
        self.port = port
        self.base_url = base_url.rstrip("/").removesuffix("/v1")
        self.provider_base_url = f"{self.base_url}/v1"
        self.snapshot_providers: dict[str, Any] = {}
        self.snapshot_hash: str = ""

    def _fail(self, what: str, status: int, result: Any) -> dict:
        raise self._ConfigCenterError(
            f"{what} 失败：HTTP {status}，响应={json.dumps(result, ensure_ascii=False)[:500]}"
        )

    def _require_ok(self, what: str, status: int, result: Any) -> dict:
        if status < 200 or status >= 300 or not isinstance(result, dict):
            return self._fail(what, status, result)
        return result

    def _providers(self, workspace: dict | None = None, *, fallback: bool = True) -> dict[str, Any]:
        if workspace is None and fallback:
            workspace = self._require_ok(
                "GET /api/config/workspace", *_api(self.port, "GET", "/api/config/workspace")
            )
        providers = ((workspace or {}).get("publicConfig") or {}).get("llm", {}).get("providers", {})
        return providers if isinstance(providers, dict) else {}

    def snapshot(self) -> None:
        providers = self._providers()
        orphan = providers.get(PROVIDER_ID)
        if isinstance(orphan, dict):
            expected_label = _group_provider_entry("http://127.0.0.1:0/v1")["label"]
            if str(orphan.get("label") or "") != expected_label:
                raise self._ConfigCenterError(
                    f"注册前已存在非本车道创建的 {PROVIDER_ID} provider，拒绝覆盖；请先清理现场再跑。"
                )
            print(f"[group_chat] 发现上次会话残留的 {PROVIDER_ID}，先自愈注销")
            self.snapshot_providers = {
                key: value for key, value in providers.items() if key != PROVIDER_ID
            }
            self.restore_and_verify()
            providers = self._providers()
        self.snapshot_providers = json.loads(json.dumps(providers))
        workspace = self._require_ok(
            "GET /api/config/workspace", *_api(self.port, "GET", "/api/config/workspace")
        )
        self.snapshot_hash = str(workspace.get("hash") or "")

    def register(self) -> None:
        workspace = self._require_ok(
            "GET /api/config/workspace", *_api(self.port, "GET", "/api/config/workspace")
        )
        base_hash = str(workspace.get("hash") or "")
        if not base_hash:
            raise self._ConfigCenterError("workspace 未返回 hash，无法作为 baseHash")
        draft = self._require_ok(
            "POST /api/config/draft/providers",
            *_api(
                self.port,
                "POST",
                "/api/config/draft/providers",
                {
                    "publicConfig": workspace.get("publicConfig") or {},
                    "draftMeta": {"source": "e2e-mock-group"},
                    "baseHash": base_hash,
                    "providerId": PROVIDER_ID,
                    "provider": _group_provider_entry(self.provider_base_url),
                },
            ),
        )
        drafted = draft.get("publicConfig")
        if not isinstance(drafted, dict):
            raise self._ConfigCenterError(
                f"草稿响应缺 publicConfig: keys={sorted(draft.keys())} "
                f"body={json.dumps(draft, ensure_ascii=False)[:400]}"
            )
        # 注意 _providers 入参是 workspace 形（自己挖 publicConfig），
        # 传完整 draft 响应而不是已提取的 publicConfig 值。
        if PROVIDER_ID not in self._providers(draft, fallback=False):
            raise self._ConfigCenterError(
                f"草稿未见 {PROVIDER_ID}: providers={sorted(self._providers(draft, fallback=False))}"
            )
        applied = self._require_ok(
            "PUT /api/config/apply",
            *_api(
                self.port,
                "PUT",
                "/api/config/apply",
                {
                    "publicConfig": drafted,
                    "draftMeta": {"source": "e2e-mock-group"},
                    "baseHash": base_hash,
                    "baseConfig": None,
                },
            ),
        )
        providers = self._providers(applied)
        entry = providers.get(PROVIDER_ID)
        if not isinstance(entry, dict):
            raise self._ConfigCenterError(f"apply 后回读未见 {PROVIDER_ID}（保现场）")
        actual_base = str(entry.get("base_url") or "")
        if actual_base != self.provider_base_url:
            raise self._ConfigCenterError(f"apply 后 base_url 不符: {actual_base!r}")
        missing = sorted(set(PROVIDER_MODELS) - set(entry.get("models") or {}))
        if missing:
            raise self._ConfigCenterError(f"apply 后缺模型: {missing}")
        print(f"[group_chat] provider {PROVIDER_ID} 已注册: base_url={actual_base}")

    def restore_and_verify(self) -> None:
        from tests.e2e.mock_llm.config_center import _is_conflict

        last_error: Exception | None = None
        for _attempt in range(3):
            try:
                self._restore_once()
                self._verify_restored()
                return
            except Exception as exc:  # 仅 409 冲突可重试
                if not _is_conflict(exc):
                    raise
                last_error = exc
                print(f"[group_chat] 恢复 apply 基线冲突，重试: {exc}")
                time.sleep(1.0)
        raise last_error  # type: ignore[misc]

    def _restore_once(self) -> None:
        workspace = self._require_ok(
            "GET /api/config/workspace", *_api(self.port, "GET", "/api/config/workspace")
        )
        base_hash = str(workspace.get("hash") or "")
        providers = self._providers(workspace)
        if PROVIDER_ID not in providers:
            print(f"[group_chat] {PROVIDER_ID} 已不在配置中，跳过注销")
            return
        drafted = workspace.get("publicConfig") or {}
        for model_key in sorted(PROVIDER_MODELS):
            drafted = self._require_ok(
                f"DELETE draft models/{model_key}",
                *_api(
                    self.port,
                    "DELETE",
                    f"/api/config/draft/providers/{PROVIDER_ID}/models/{model_key}",
                    {
                        "publicConfig": drafted,
                        "draftMeta": {"source": "e2e-mock-group"},
                        "baseHash": base_hash,
                        "providerId": PROVIDER_ID,
                        "upstreamId": model_key,
                        "modelKey": model_key,
                    },
                ),
            ).get("publicConfig")
        drafted = self._require_ok(
            f"DELETE draft providers/{PROVIDER_ID}",
            *_api(
                self.port,
                "DELETE",
                f"/api/config/draft/providers/{PROVIDER_ID}",
                {
                    "publicConfig": drafted,
                    "draftMeta": {"source": "e2e-mock-group"},
                    "baseHash": base_hash,
                    "providerId": PROVIDER_ID,
                },
            ),
        ).get("publicConfig")
        self._require_ok(
            "PUT /api/config/apply (restore)",
            *_api(
                self.port,
                "PUT",
                "/api/config/apply",
                {
                    "publicConfig": drafted,
                    "draftMeta": {"source": "e2e-mock-group"},
                    "baseHash": base_hash,
                    "baseConfig": None,
                },
            ),
        )

    def _verify_restored(self) -> None:
        providers = self._providers()
        if PROVIDER_ID in providers:
            raise self._ConfigCenterError(f"恢复后仍存在 {PROVIDER_ID}（注销失败，保现场待排查）")
        missing = sorted(set(self.snapshot_providers) - set(providers))
        if missing:
            raise self._ConfigCenterError(f"快照中的 provider 被外部改动删除: {missing}")
        print(f"[group_chat] {PROVIDER_ID} 已注销；快照 provider 全部在位: {sorted(providers) or '(空)'}")


# --- aimock runner（运行时生成，speaker 身份从 codes 文件懒读取） --------------

RUNNER_MJS = """\
// e2e 群聊车道剧本（test_group_chat.py 运行时生成到临时目录）。
// 路由口径：轮次按议题标记（E2E-GROUP-R1/R2/R3）在完整 user 文本上匹配；
// 发言者身份按 prompt「你的界面代号: <agentCode>」行取最后一次出现（第二轮起
// prior 发言会引用其他成员正文，不能按 code 出现与否路由）。
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import path from "node:path";

const installRoot = process.env.AIMOCK_INSTALL_ROOT || "";
if (!installRoot) {
  console.error("AIMOCK_INSTALL_ROOT 未设置：runner 需要指向 aimock 安装根目录");
  process.exit(1);
}
const require = createRequire(path.join(installRoot, "node_modules", "@copilotkit", "aimock", "package.json"));
const { LLMock } = require("@copilotkit/aimock");

const args = process.argv.slice(2);
function flag(name, fallback) {
  const index = args.indexOf(name);
  return index >= 0 && index + 1 < args.length ? args[index + 1] : fallback;
}
const mock = new LLMock({
  port: Number(flag("--port", "0")) || 0,
  host: String(flag("--host", "127.0.0.1")),
  logLevel: "info",
});

function userTexts(req) {
  return (req.messages || [])
    .filter((m) => m && m.role === "user")
    .map((m) => (typeof m.content === "string" ? m.content : ""))
    .filter((t) => t.length > 0);
}
function isTitleCall(req) {
  const texts = userTexts(req);
  return texts.length > 0 && texts[texts.length - 1].trimStart().startsWith("用户消息：");
}
function fullUserText(req) {
  return userTexts(req).join("\\n");
}
function speakerCode(req) {
  const matches = [...fullUserText(req).matchAll(/你的界面代号[:：]\\s*([^\\n\\r]+)/g)];
  const hit = matches.at(-1);
  return hit ? hit[1].trim() : "";
}
function codes() {
  // 成员 agentCode 是产品运行时分配的，fixture 先起 aimock 后建 agent；
  // runner 每次请求懒读取 codes 文件（建号后由测试进程写入）。
  const file = process.env.E2E_GROUP_CODES_FILE || "";
  if (!file) return {};
  try {
    return JSON.parse(readFileSync(file, "utf-8"));
  } catch {
    return {};
  }
}
function hasMarker(req, marker) {
  return !isTitleCall(req) && fullUserText(req).includes(marker);
}
function codeEquals(req, key) {
  const wanted = String(codes()[key] || "");
  return Boolean(wanted) && speakerCode(req) === wanted;
}

// R1：两位成员各自确认到场。
mock.addFixture({
  match: { predicate: (req) => hasMarker(req, "E2E-GROUP-R1") },
  response: (req) => ({ content: `第一轮发言：${speakerCode(req)} 已到场，确认群聊链路正常。` }),
});

// R2：第二轮接续（prior 发言在 prompt 里，身份仍取「你的界面代号」行）。
mock.addFixture({
  match: { predicate: (req) => hasMarker(req, "E2E-GROUP-R2") },
  response: (req) => ({ content: `第二轮发言：${speakerCode(req)} 补充风险提示：成员归属回归已就位。` }),
});

// R3 慢速位（成员 A）：拉长 ttft 提供「等待发言/正在输入」的可观测窗口。
mock.addFixture({
  match: { predicate: (req) => hasMarker(req, "E2E-GROUP-R3") && codeEquals(req, "a") },
  response: (req) => ({ content: `第三轮发言：${speakerCode(req)} 慢速发言，用于暴露排队状态。` }),
  streamingProfile: { ttft: 6000, tps: 5, jitter: 0 },
});
// R3 快速位（成员 B）。
mock.addFixture({
  match: { predicate: (req) => hasMarker(req, "E2E-GROUP-R3") },
  response: (req) => ({ content: `第三轮发言：${speakerCode(req)} 快速收尾。` }),
});

// 兜底：标题生成等辅助调用，必须最后注册。
mock.addFixture({
  match: { userMessage: /.*/ },
  response: { content: "ok (e2e-mock-group catch-all)" },
});

const url = await mock.start();
console.log(`E2E_GROUP_RUNNER_URL=${url}`);
setInterval(() => {}, 1 << 30);
"""


# --- agent / room arrange -----------------------------------------------------


def _first_prompt_template_id(port: int) -> str:
    from tests.e2e.helpers.instance_registry import fetch_json

    catalog = fetch_json(port, "/api/prompt-templates")
    for item in catalog.get("templates") or []:
        template_id = str((item or {}).get("templateId") or "").strip()
        if template_id:
            return template_id
    raise RuntimeError(f"实例无可用提示词模板，无法创建 Agent: {str(catalog)[:200]}")


def create_group_member(
    port: int,
    display_name: str,
    model_key: str,
    *,
    prompt_template_id: str = "",
) -> dict:
    """建群聊成员 Agent（persistent + 直属会话），dialogue 槽绑到本车道模型。

    ``prompt_template_id`` 缺省取实例模板目录首个可用模板；显式传入不存在的
    模板 id（如 fail-closed 用例）会得到一个快照不可 seed 的成员——与「Agent
    无 promptTemplateId」同一条 fail-closed 分支（ensure 返回的快照渲染不出
    快照块，host-seed 标记保持 False）。
    """
    agent = _post_ok(
        port,
        "/api/agents",
        {
            "displayName": display_name,
            "primaryMode": "chat",
            "promptTemplateId": prompt_template_id or _first_prompt_template_id(port),
            "llmBindings": {"dialogue": {"modelId": f"{PROVIDER_ID}/{model_key}"}},
        },
        what=f"创建群聊成员 {display_name}",
    )
    agent_id = str(agent.get("agentId") or "").strip()
    session_id = str(agent.get("directSessionId") or "").strip()
    agent_code = str(agent.get("agentCode") or "").strip()
    if not agent_id or not session_id:
        raise RuntimeError(f"成员创建响应缺 agentId/directSessionId: {str(agent)[:300]}")
    if not agent_code:
        from tests.e2e.helpers.instance_registry import fetch_json

        catalog = fetch_json(port, "/api/agents?includeArchived=true")
        for item in catalog if isinstance(catalog, list) else []:
            if str((item or {}).get("agentId") or "") == agent_id:
                agent_code = str((item or {}).get("agentCode") or "").strip()
                break
    print(f"[group_chat] 成员就绪: {display_name} agent={agent_id} code={agent_code!r}")
    return {
        "agentId": agent_id,
        "sessionId": session_id,
        "agentCode": agent_code,
        "displayName": display_name,
        "modelKey": model_key,
    }


def delete_group_member(port: int, agent_id: str, *, timeout_seconds: float = 150.0) -> None:
    """teardown：归档 + purge（硬删连带会话），回读核对，避免 live 引用挡 provider 注销。

    每次尝试都留状态证据：最后仍在 registry 时，把末次归档/ purge 响应打出来定位
    挡点（409 busy / 422 校验等），不让 teardown 静默盲重试。
    """
    last_archive = "n/a"
    last_purge = "n/a"
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        for label, path, sink in (
            ("archive", f"/api/agents/{agent_id}", "last_archive"),
            ("purge", f"/api/agents/{agent_id}/purge", "last_purge"),
        ):
            try:
                status, result = _api(port, "DELETE", path, timeout_seconds=90.0)
                if label == "archive":
                    last_archive = f"HTTP {status} {str(result)[:200]}"
                else:
                    last_purge = f"HTTP {status} {str(result)[:200]}"
            except Exception as exc:  # noqa: BLE001 - 瞬态失败交给外层重试
                if label == "archive":
                    last_archive = f"EXC {exc}"
                else:
                    last_purge = f"EXC {exc}"
        try:
            status, result = _api(port, "GET", "/api/agents?includeArchived=true", timeout_seconds=30.0)
            present = status != 200 or not isinstance(result, list) or any(
                str((item or {}).get("agentId") or "") == agent_id for item in result
            )
        except Exception:  # noqa: BLE001 - 读不到当还在，继续重试
            present = True
        if not present:
            return
        time.sleep(2.0)
    print(
        f"[group_chat] 测试成员删除未闭环（仍在 registry）: {agent_id}；"
        f"末次 archive={last_archive} purge={last_purge}"
    )


def create_room_via_api(port: int, title: str, agent_ids: list[str]) -> dict:
    room = _post_ok(
        port,
        "/api/chat-rooms",
        {"title": title, "agentIds": agent_ids, "mode": "round_robin", "purpose": "discussion"},
        what="API 创建群聊",
    )
    room_id = str(room.get("roomId") or "").strip()
    if not room_id:
        raise RuntimeError(f"群聊创建响应缺 roomId: {str(room)[:300]}")
    return room


def delete_room(port: int, room_id: str) -> None:
    """删除群聊并回读核对；删失败只打印（实例停机后数据目录整体清理兜底）。"""
    try:
        status, result = _api(port, "DELETE", f"/api/chat-rooms/{room_id}")
        if status < 200 or status >= 300:
            print(f"[group_chat] 群聊删除失败: HTTP {status} {str(result)[:200]}: {room_id}")
            return
    except Exception as exc:  # noqa: BLE001 - 尽力而为
        print(f"[group_chat] 群聊删除失败: {room_id}: {exc}")
        return
    if fetch_room(port, room_id) is not None:
        print(f"[group_chat] 群聊删除后仍可读到（可能异步）: {room_id}")
        return
    print(f"[group_chat] 群聊已删除: {room_id}")


def delete_leftover_test_rooms(port: int) -> None:
    """安全网：删除本车道残留的测试群聊（标题前缀识别），避免房间引用挡成员归档
    （实测 run7：房间残留时先归档 A 会把房间缩成仅剩 B，B 归档随即 422 唯一成员）。"""
    try:
        status, rooms = _api(port, "GET", "/api/chat-rooms", timeout_seconds=30.0)
    except Exception as exc:  # noqa: BLE001 - 实例可能已在收尾
        print(f"[group_chat] 残留群聊清单读取失败: {exc}")
        return
    if status != 200 or not isinstance(rooms, list):
        return
    for room in rooms:
        room_id = str((room or {}).get("roomId") or "").strip()
        title = str((room or {}).get("title") or "").strip()
        if room_id and title.startswith("E2E群聊-"):
            print(f"[group_chat] 发现残留测试群聊: {room_id} ({title})，删除")
            delete_room(port, room_id)


def fetch_room(port: int, room_id: str) -> dict | None:
    status, result = _api(port, "GET", f"/api/chat-rooms/{room_id}", timeout_seconds=30.0)
    return result if status == 200 and isinstance(result, dict) else None


def wait_room_rounds_at_least(port: int, room_id: str, *, min_rounds: int, timeout_s: float = 30.0) -> None:
    """等房间详情记录到第 N 轮（议题 POST 是异步 mutation，立即回读会抢跑）。"""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        room = fetch_room(port, room_id)
        if len((room or {}).get("rounds") or []) >= min_rounds:
            return
        time.sleep(0.5)
    raise AssertionError(f"房间 {room_id} 在 {timeout_s:.0f}s 内未记录到第 {min_rounds} 轮")


def wait_round_terminal(port: int, room_id: str, *, min_rounds: int) -> dict:
    """轮询房间详情直到最新一轮到终态；返回该轮 payload（含 roundId/messages）。"""
    deadline = time.monotonic() + ROUND_TERMINAL_TIMEOUT_S
    last_state = ""
    while time.monotonic() < deadline:
        room = fetch_room(port, room_id)
        rounds = (room or {}).get("rounds") or []
        if rounds:
            latest = rounds[-1]
            status = str(latest.get("status") or "")
            last_state = f"rounds={len(rounds)} status={status} messages={len(latest.get('messages') or [])}"
            if status in ROUND_TERMINAL_STATUSES:
                if status != "completed":
                    print(f"[group_chat] 轮次以非 completed 终态收口: {status}")
                return latest
        time.sleep(1.0)
    raise AssertionError(f"群聊轮在 {ROUND_TERMINAL_TIMEOUT_S:.0f}s 内未收口（最后状态 {last_state}）")


# --- 群聊 UI 步骤 --------------------------------------------------------------


def open_chat_route(page: Any, e2e_instance: Any) -> None:
    from tests.e2e.helpers.page_anchors import wait_route_ready

    page.goto(f"{e2e_instance.base_url}/chat", wait_until="domcontentloaded")
    wait_route_ready(page)


def create_room_via_ui(page: Any, port: int, title: str, member_names: list[str]) -> str:
    """chat 左栏「新建任务 → 新建群聊」建群；返回路由里的真实 roomId。

    建群是乐观投影：URL 先落 ``temp-room-`` 壳，成功后才换成服务端 room-xxx；
    这里等到非 temp 的真实 roomId 且房间详情 API 可读，才认为创建完成。
    """
    page.locator("#chat-agent-create-trigger").click()
    page.get_by_text("新建群聊", exact=True).first.click()
    panel = page.locator('section[aria-label="新建群聊"]')
    panel.wait_for(state="visible", timeout=15_000)
    panel.locator("label", has_text="群名").locator("input").first.fill(title)
    for name in member_names:
        option = panel.locator("label", has_text=name).first
        option.scroll_into_view_if_needed()
        option.locator('input[type="checkbox"]').check()
    panel.get_by_role("button", name="创建群聊").click()
    room_id = ""
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        url = page.url
        if "room=" in url:
            candidate = url.split("room=", 1)[1].split("&", 1)[0]
            if candidate and not candidate.startswith("temp-room-") and fetch_room(port, candidate):
                room_id = candidate
                break
        page.wait_for_timeout(300)
    assert room_id, f"建群后未拿到真实 roomId（url={page.url}）"
    page.locator(f'input[placeholder="{TOPIC_INPUT_PLACEHOLDER}"]').first.wait_for(
        state="visible", timeout=30_000
    )
    return room_id


def send_round_topic(page: Any, topic: str) -> None:
    composer = page.locator(f'input[placeholder="{TOPIC_INPUT_PLACEHOLDER}"]').first
    composer.wait_for(state="visible", timeout=15_000)
    composer.click()
    composer.fill(topic)
    composer.press("Enter")


def round_section(page: Any, round_id: str):
    return page.locator(f'section[data-group-round-id="{round_id}"]')


def wait_round_settled_in_ui(page: Any, round_payload: dict, *, timeout_s: float = 45.0) -> Any:
    """等轮次块上屏且以「发言已结束」收口；SSE 快照落后时点一次「刷新」兜底。"""
    round_id = str(round_payload.get("roundId") or "")
    deadline = time.monotonic() + timeout_s
    refreshed = False
    last_text = ""
    while time.monotonic() < deadline:
        section = round_section(page, round_id)
        if section.count():
            last_text = section.first.inner_text()
            if "发言已结束" in last_text:
                return section.first
        if not refreshed and time.monotonic() > deadline - timeout_s / 2:
            refreshed = True
            refresh = page.get_by_role("button", name="刷新")
            if refresh.count():
                refresh.first.click()
        page.wait_for_timeout(500)
    raise AssertionError(
        f"轮 {round_id} 未在 UI 以「发言已结束」收口（SSE/刷新后仍未见）；末次文本尾={last_text[-200:]!r}"
    )


def assert_member_reply_attribution(
    page: Any,
    round_id: str,
    member: dict,
    reply_text: str,
    other_member: dict,
    other_reply_text: str,
) -> None:
    """归属断言：含该成员正文的发言 article，其身份行必须是该成员（不串人）。

    只在 ``.groupMessageList`` 的发言行里找（字面 class token，见
    ChatGroupCenterSurface.styles.ts），避开议题气泡与轮次纪要 article。
    """
    section = round_section(page, round_id)
    articles = section.locator(".groupMessageList article").filter(has_text=reply_text)
    assert articles.count() == 1, (
        f"成员 {member['displayName']} 的回复在轮 {round_id} 中应恰好 1 条，"
        f"实际 {articles.count()} 条: {reply_text!r}"
    )
    article = articles.first
    identity = article.locator(IDENTITY_ROW)
    assert identity.count() >= 1, (
        f"成员 {member['displayName']} 的发言缺少身份行（归属不可见）: {reply_text!r}"
    )
    label = identity.first.inner_text()
    assert member["displayName"] in label, (
        f"身份行不指向 {member['displayName']}: {label!r}（正文 {reply_text!r}）"
    )
    assert other_member["displayName"] not in label, (
        f"身份行串人（出现 {other_member['displayName']}）: {label!r}"
    )
    body = article.inner_text()
    assert other_reply_text not in body, (
        f"成员 {member['displayName']} 的发言混入了 {other_member['displayName']} 的正文"
    )


def assert_round_speaker_rows(page: Any, round_payload: dict, ordered_members: list[dict]) -> None:
    """每轮发言身份行数量与顺序 == speakerOrder（round_robin 按 participants 顺序）。"""
    section = round_section(page, str(round_payload.get("roundId") or ""))
    identities = section.locator(IDENTITY_ROW)
    expected = len(round_payload.get("messages") or [])
    assert identities.count() == expected, (
        f"轮 {round_payload.get('roundId')} 身份行数 {identities.count()} != 发言数 {expected}"
    )
    labels = [identities.nth(i).inner_text() for i in range(identities.count())]
    for index, member in enumerate(ordered_members):
        assert member["displayName"] in labels[index], (
            f"第 {index + 1} 条发言身份应为 {member['displayName']}，实际 {labels[index]!r}"
        )


def assert_round_journal(mock_llm_group: Any, marker: str, expected_model_keys: list[str]) -> None:
    """journal 口径：带该议题标记的请求按成员模型各命中 200，且无意外 model。"""
    entries = mock_llm_group.server.journal(path="/v1/chat/completions")
    assert entries, "journal 为空：群聊轮没有向 e2e-mock-group 发起请求"
    hits: dict[str, list[int]] = {}
    for entry in entries:
        body = entry.get("body") or {}
        model = str(body.get("model") or "")
        messages = body.get("messages") or []
        if any(marker in str((m or {}).get("content") or "") for m in messages):
            hits.setdefault(model, []).append(int((entry.get("response") or {}).get("status") or 0))
    for model_key in expected_model_keys:
        statuses = hits.get(model_key) or []
        assert 200 in statuses, (
            f"成员模型 {model_key} 的请求未以 200 命中（标记 {marker}）: {statuses}"
        )
    unexpected = set(hits) - set(expected_model_keys) - {""}
    assert not unexpected, f"journal 出现意外 model: {unexpected}"


# ---------------------------------------------------------------------------
# fixtures（会话级：aimock + provider 注册；成员 agent；房间复用）
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def group_llm(e2e_instance: Any):
    """起本车道 aimock（runner 模式）→ 注册 e2e-mock-group → 测试 → 注销核对 → 停进程。"""
    from dataclasses import dataclass

    from tests.e2e.mock_llm import aimock_runtime

    @dataclass
    class GroupLlmHandle:
        server: aimock_runtime.AimockServer
        center: GroupProviderSession
        port: int

    tmp_dir = Path(tempfile.mkdtemp(prefix="e2e-group-chat-"))
    runner_path = tmp_dir / "group_runner.mjs"
    runner_path.write_text(RUNNER_MJS, encoding="utf-8")
    # 成员 agentCode 由产品运行时分配，晚于 aimock 启动；runner 经此文件懒读取。
    codes_path = tmp_dir / "member_codes.json"
    codes_path.write_text("{}", encoding="utf-8")
    os.environ["E2E_GROUP_CODES_FILE"] = str(codes_path)

    server = aimock_runtime.start_aimock(tmp_dir, script=runner_path)
    center = GroupProviderSession(e2e_instance.port, base_url=server.base_url)
    try:
        center.snapshot()
        center.register()
    except Exception:
        try:
            server.stop()
            server.assert_stopped()
        except Exception as stop_exc:  # noqa: BLE001 - 不掩盖注册失败原始错误
            print(f"[group_chat] 注册失败后的 aimock 补停未闭环: {stop_exc}")
        raise
    handle = GroupLlmHandle(server=server, center=center, port=e2e_instance.port)
    print(f"[group_chat] 车道就绪: aimock={server.base_url} provider={PROVIDER_ID}")
    yield handle
    teardown_error: Exception | None = None
    try:
        center.restore_and_verify()
    except Exception as exc:  # noqa: BLE001 - 恢复失败要报告并保现场
        teardown_error = exc
        print(f"[group_chat] provider 注销/恢复失败（保现场）: {exc}")
    try:
        server.stop()
        server.assert_stopped()
    except Exception as exc:  # noqa: BLE001 - 进程零残留是硬指标
        print(f"[group_chat] aimock 拆机异常: {exc}")
        if teardown_error is None:
            teardown_error = exc
    os.environ.pop("E2E_GROUP_CODES_FILE", None)
    if teardown_error is not None:
        raise teardown_error


@pytest.fixture(scope="session")
def group_members(group_llm: Any, e2e_instance: Any):
    """两个群聊成员 Agent（dialogue 各绑一个本车道模型）；会话结束归档+purge。"""
    port = e2e_instance.port
    member_a = create_group_member(port, MEMBER_A_NAME, MODEL_A)
    member_b = create_group_member(port, MEMBER_B_NAME, MODEL_B)
    codes_path = Path(os.environ["E2E_GROUP_CODES_FILE"])
    codes_path.write_text(
        json.dumps({"a": member_a["agentCode"], "b": member_b["agentCode"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    members = {"a": member_a, "b": member_b}
    yield members
    # 先清残留测试群聊再删成员：房间引用会让归档 422（唯一成员/成员引用）。
    delete_leftover_test_rooms(port)
    delete_group_member(port, member_a["agentId"])
    delete_group_member(port, member_b["agentId"])


@pytest.fixture(scope="session")
def group_room_state() -> dict:
    """跨用例共享的房间句柄：本用例建房后登记；cleanup fixture 负责删除。"""
    return {"roomId": ""}


@pytest.fixture()
def group_room_cleanup(e2e_instance: Any, group_room_state: dict):
    """每条用例结束删除本用例的测试房间（用例失败也要清：房间引用会挡成员
    archive/purge，成员残留又挡 provider 注销——run3 实测链）。"""
    yield
    room_id = str(group_room_state.get("roomId") or "")
    if room_id:
        delete_room(e2e_instance.port, room_id)
        group_room_state["roomId"] = ""


@pytest.fixture(autouse=True)
def reset_group_llm_journal(group_llm: Any):
    """每条用例前清空本车道 aimock journal（共享车道的 autouse 只清它的服务器）。"""
    group_llm.server.reset_journal()
    yield


# ---------------------------------------------------------------------------
# 用例
# ---------------------------------------------------------------------------


def test_group_room_create_rounds_and_member_attribution(
    page: Any,
    e2e_instance: Any,
    group_llm: Any,
    group_members: dict,
    group_room_state: dict,
    group_room_cleanup: None,
) -> None:
    """UI 建群（≥2 成员）→ 两轮群聊：议题上屏、逐成员回复归属正确、轮次完整无丢失。

    - 第 1 轮：议题行（用户身份）+ 每位成员各 1 条发言，身份行指向正确成员、
      正文不串人（A 的 article 无 B 的正文，反之亦然）；
    - 第 2 轮：同一房间再开一轮，两轮 4 条发言同屏（无丢失、无跨成员重复），
      round_robin 发言顺序按 participants 顺序（A 先 B 后）。
    """
    port = e2e_instance.port
    member_a = group_members["a"]
    member_b = group_members["b"]
    title = f"E2E群聊-{int(time.time())}"
    reply_a_r1 = REPLY_R1.format(code=member_a["agentCode"])
    reply_b_r1 = REPLY_R1.format(code=member_b["agentCode"])
    reply_a_r2 = REPLY_R2.format(code=member_a["agentCode"])
    reply_b_r2 = REPLY_R2.format(code=member_b["agentCode"])

    open_chat_route(page, e2e_instance)
    room_id = create_room_via_ui(
        page, port, title, [member_a["displayName"], member_b["displayName"]]
    )
    group_room_state["roomId"] = room_id
    print(f"[group_chat] UI 建群成功: {room_id} ({title})")

    # --- 第 1 轮 ---
    send_round_topic(page, TOPIC_R1)
    round1 = wait_round_terminal(port, room_id, min_rounds=1)
    assert len(round1.get("messages") or []) == 2, (
        f"第 1 轮应恰有 2 条成员发言: {str(round1.get('messages'))[:300]}"
    )
    section1 = wait_round_settled_in_ui(page, round1)
    assert TOPIC_R1 in section1.inner_text(), "第 1 轮议题未上时间线"
    assert section1.locator(TOPIC_IDENTITY_ROW).count() == 1, "第 1 轮缺用户议题身份行"
    assert_member_reply_attribution(page, round1["roundId"], member_a, reply_a_r1, member_b, reply_b_r1)
    assert_member_reply_attribution(page, round1["roundId"], member_b, reply_b_r1, member_a, reply_a_r1)
    assert_round_speaker_rows(page, round1, [member_a, member_b])
    assert_round_journal(group_llm, "E2E-GROUP-R1", [MODEL_A, MODEL_B])

    # --- 第 2 轮（同房间多轮，断言轮次完整、无丢失） ---
    send_round_topic(page, TOPIC_R2)
    wait_room_rounds_at_least(port, room_id, min_rounds=2)
    round2 = wait_round_terminal(port, room_id, min_rounds=2)
    assert len(round2.get("messages") or []) == 2, (
        f"第 2 轮应恰有 2 条成员发言: {str(round2.get('messages'))[:300]}"
    )
    wait_round_settled_in_ui(page, round2)
    assert_member_reply_attribution(page, round2["roundId"], member_a, reply_a_r2, member_b, reply_b_r2)
    assert_member_reply_attribution(page, round2["roundId"], member_b, reply_b_r2, member_a, reply_a_r2)
    assert_round_speaker_rows(page, round2, [member_a, member_b])
    assert_round_journal(group_llm, "E2E-GROUP-R2", [MODEL_A, MODEL_B])
    # 两轮同屏：4 条成员发言全部可见（无消息丢失），每轮各 2 条身份行（无跨成员重复）。
    assert round_section(page, round1["roundId"]).count() == 1, "第 1 轮时间线块消失"
    assert round_section(page, round2["roundId"]).count() == 1, "第 2 轮时间线块缺失"
    total_identities = (
        round_section(page, round1["roundId"]).locator(IDENTITY_ROW).count()
        + round_section(page, round2["roundId"]).locator(IDENTITY_ROW).count()
    )
    assert total_identities == 4, f"两轮身份行总数应为 4，实际 {total_identities}"


def test_group_round_pending_speaker_visibility(
    page: Any,
    e2e_instance: Any,
    group_llm: Any,
    group_members: dict,
    group_room_state: dict,
    group_room_cleanup: None,
) -> None:
    """运行中的轮次暴露排队/发言状态：后位成员显示「等待发言」，收口后正文照常归属。

    成员 A 的剧本 ttft 6s（排队窗），round_robin 串行使 B 在 A 发言期间排队。
    每条用例用完即删房（cleanup fixture），本用例单独跑时经 API 兜底建房。
    """
    port = e2e_instance.port
    member_a = group_members["a"]
    member_b = group_members["b"]
    room_id = str(group_room_state.get("roomId") or "")
    if not room_id or fetch_room(port, room_id) is None:
        room = create_room_via_api(
            port, f"E2E群聊-排队观察-{int(time.time())}", [member_a["agentId"], member_b["agentId"]]
        )
        room_id = room["roomId"]
        group_room_state["roomId"] = room_id

    from tests.e2e.helpers.page_anchors import wait_route_ready

    page.goto(f"{e2e_instance.base_url}/chat?room={room_id}", wait_until="domcontentloaded")
    wait_route_ready(page)
    page.locator(f'input[placeholder="{TOPIC_INPUT_PLACEHOLDER}"]').first.wait_for(
        state="visible", timeout=30_000
    )

    baseline_rounds = len((fetch_room(port, room_id) or {}).get("rounds") or [])
    send_round_topic(page, TOPIC_R3)

    # 排队窗：A 慢速发言（ttft 6s）期间，后位成员 B 的 pending 行显示「等待发言」。
    # 注意锁定 B 的行：轮次刚启动的快照里 A 也可能是 queued（后端 speakerProgress
    # 尚未推进，实测 run7），首个「等待发言」行未必是 B。
    deadline = time.monotonic() + 25.0
    queued_row = None
    typing_seen = False
    while time.monotonic() < deadline:
        pending = page.locator(".groupBubbleRowPending").filter(
            has_text=member_b["displayName"]
        ).filter(has_text="等待发言")
        if pending.count():
            queued_row = pending.first
            break
        typing = page.locator('[aria-label="正在输入"]')
        if typing.count():
            typing_seen = True
        page.wait_for_timeout(250)
    print(f"[group_chat] 排队窗采样: 等待发言行={'可见' if queued_row is not None else '未见'} "
          f"正在输入指示={'可见' if typing_seen else '未见'}")
    assert queued_row is not None, (
        "运行中的轮次未观测到「等待发言」pending 行（排队状态不可见）"
    )
    queued_identity = queued_row.locator(IDENTITY_ROW).first.inner_text()
    assert member_b["displayName"] in queued_identity, (
        f"「等待发言」行不属于后位成员 {member_b['displayName']}: {queued_identity!r}"
    )

    round3 = wait_round_terminal(port, room_id, min_rounds=baseline_rounds + 1)
    messages = round3.get("messages") or []
    assert len(messages) == 2, f"第 3 轮应恰有 2 条成员发言: {str(messages)[:300]}"
    wait_round_settled_in_ui(page, round3)
    reply_a_r3 = REPLY_R3_SLOW.format(code=member_a["agentCode"])
    reply_b_r3 = REPLY_R3_FAST.format(code=member_b["agentCode"])
    assert_member_reply_attribution(page, round3["roundId"], member_a, reply_a_r3, member_b, reply_b_r3)
    assert_member_reply_attribution(page, round3["roundId"], member_b, reply_b_r3, member_a, reply_a_r3)
    assert_round_journal(group_llm, "E2E-GROUP-R3", [MODEL_A, MODEL_B])


def test_group_speaker_without_seedable_snapshot_fails_closed_at_32k(
    e2e_instance: Any,
    group_llm: Any,
    group_members: dict,
    group_room_state: dict,
    group_room_cleanup: None,
) -> None:
    """32k 窗口回归钉的 fail-closed 侧：快照不可 seed 的成员不绕预算硬闸。

    成员 C 的 promptTemplateId 指向不存在的模板（与「Agent 无 promptTemplateId」
    同一条 fail-closed 分支：快照渲染不出快照块，host-seed 标记 False）。32k
    窗口下核心三文件装不进 STABLE_CORE 预算（3000），protected_tier_over_budget
    硬闸拦截其发言；轮内失败消息必须携带可行动指引（换更大窗口模型），且同成员
    正常模板的发言不受影响（round partial 收口）。零输出重试排除由单测钉住，
    这里钉真实链路的失败消息形态。
    """
    port = e2e_instance.port
    member_a = group_members["a"]
    broken = create_group_member(
        port,
        "E2E群聊成员C-缺模板",
        MODEL_B,
        prompt_template_id="prompt-e2e-group-missing-template",
    )
    try:
        room = create_room_via_api(
            port,
            f"E2E群聊-缺模板fail-closed-{int(time.time())}",
            [member_a["agentId"], broken["agentId"]],
        )
        room_id = room["roomId"]
        group_room_state["roomId"] = room_id

        status, started = _api(
            port,
            "POST",
            f"/api/chat-rooms/{room_id}/rounds",
            {"topic": "E2E-GROUP-FC 请确认预算闸行为", "mode": "round_robin", "purpose": "discussion"},
        )
        assert 200 <= status < 300, f"开轮失败: HTTP {status} {str(started)[:300]}"

        latest = wait_round_terminal(port, room_id, min_rounds=1)
        round_status = str(latest.get("status") or "")
        assert round_status in {"partial", "failed"}, (
            f"缺模板成员应令轮次以 partial/failed 收口，实际 {round_status}: "
            f"{str(latest.get('messages'))[:400]}"
        )
        messages = latest.get("messages") or []
        assert len(messages) == 2, f"轮内应有 2 条消息（1 成功 1 失败）: {str(messages)[:400]}"

        by_agent: dict[str, dict] = {
            str((m or {}).get("agentId") or ""): m for m in messages if isinstance(m, dict)
        }
        ok_message = by_agent.get(member_a["agentId"]) or {}
        assert str(ok_message.get("status") or "") == "completed", (
            f"正常模板成员在 32k 窗口下应照常发言（seed 生效）: {str(ok_message)[:300]}"
        )
        failed_message = by_agent.get(broken["agentId"]) or {}
        assert str(failed_message.get("status") or "") == "failed", (
            f"缺模板成员应失败落消息: {str(failed_message)[:300]}"
        )
        summary = str(failed_message.get("summary") or "")
        assert str(failed_message.get("errorType") or "") == "PromptAssemblyBudgetError", (
            f"失败消息 errorType 应为预算闸错误: {str(failed_message)[:300]}"
        )
        assert "64k" in summary and ("预算闸" in summary or "budget gate" in summary), (
            f"失败消息缺可行动指引（换 ≥64k 模型）: {summary[:300]}"
        )
    finally:
        delete_group_member(port, broken["agentId"])
