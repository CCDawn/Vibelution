# -*- coding: utf-8 -*-
"""e2e 图片链路：钉住 09-25 修复批的用户可见行为（真实分支实例 + 独占 aimock）。

钉住的行为（对应修复）：
- composer 上传图片 → 发送 → 用户消息里图片附件可见 → mock 回复到达；
- 页面 reload 后图片在历史消息里仍然可见（历史可见性，9bd376b8b 的 UI 面）；
- 多文件上传 allSettled 语义：单个上传失败不拖死整批、成功项保留 artifactId、
  失败项呈现可重试状态，重试成功后整批可发送（2da5a4902 的 upload retry 面）；
- composer 草稿 reload 后保留（chatDraftPersistence localStorage 防抖）。

边界与实现口径（本文件自包含，不改共享文件）：
- 独占 provider id ``e2e-mock-img``（模型 ``e2e-mock-img-vl``，upstream_id 含
  "vl" 触发后端 vision 名称启发式，避免图片附件在 add 阶段被丢弃）；注册走
  config-center draft/apply（照抄 tests/e2e/mock_llm/config_center.py 的链路，
  只换 provider id/模型表），teardown 反注册并核对快照，不留残留。
- aimock 用本文件内嵌的 runner 脚本（tempfile 落盘）：图片轮的主调用 user
  content 是多模态数组（text + image_url part），字符串级路由会漏，标记匹配
  在 ``JSON.stringify(messages)`` 上做。
- 「图片真的到了模型」由两层钉住：journal 证明主调用 200（主调用 body 超
  aimock journal 64KB 条目上限会被清空，不能反查 image_url，同
  test_mock_llm_flow 的口径）；aimock runner 剧本在真实请求上打印
  IMG_E2E_PROBE 探针行（has_image），测试读日志断言 image_url 块存在
  （9bd376b8b 的请求面）。降采样阶梯缓存（6731377d8）在模型输入归一化层，
  无用户可见锚点，不 e2e 断言。
- headless 车道没有 vibelutionLauncher preload 桥，``resolveLocalFilePath``
  恒为 null → 上传走二进制路径；zero-copy 本地路径注册（4b55026b4）只在
  cdp 模式可达，本车道不钉（web 单测 chatComposerZeroCopyUpload.test.ts 覆盖）。
  上传失败注入因此同时匹配 ``X-Vibelution-Filename`` 头（二进制路径）与
  JSON body 文件名（零拷贝路径），两种模式都能命中。
- 附件 tray 是 React 内存态、不持久化（chatDraftPersistence 头注释「plain
  text only」），reload 后附件消失是产品文档化行为而非缺陷，本文件只断言草稿。

主缺陷已修复（原 strict xfail 已提升为硬断言）：
- 时间线里的图片附件（上传与生成，同一 ``/api/sessions/{sid}/artifacts/{id}``
  URL 形态）曾被 WebControlGuardMiddleware 以 control token 拒绝（浏览器原生
  图片加载无法附带自定义头 → 403 → 前端 onError 降级为文件卡）。修复沿用
  47e6149a5 的 ``_SOURCE_ONLY_GET_PATH_PREFIXES`` 先例，为会话图片 artifact 开
  GET-only 窄口（仅图片扩展名 artifact id 放行；文档 artifact 与 mutating
  方法仍要 token，trusted-source 校验保留），test_history_image_renders_as_img
  已是硬断言，钉住图片必须以 ``<img>`` 真实加载。
- 次要缺陷（取证后按事实记录，不作断言）：上传失败批次被拦下后，乐观用户行
  残留在时间线上（submitTurnWithAttachments 失败分支的
  removeOptimisticUserMessage 未生效，截图 + thread count=1 取证），视觉上像
  「已发出一条消息」，重发后该残留行仍在。不影响 allSettled 语义本体（无
  turn、无回复、无主调用），报告附证据。

写法约定照抄 test_mock_llm_flow.py：serial + skipif 环境门（禁模块级 skip），
锚点用 ARIA/结构属性，不猜 class。
"""

from __future__ import annotations

import json
import os
import struct
import tempfile
import time
import urllib.parse
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from tests.e2e.mock_llm import aimock_runtime, config_center

pytestmark = [
    pytest.mark.serial,
    pytest.mark.timeout(0),
    # skipif 而非模块级 skip：模块级 skip 会「零收集」，closeout 选择器直跑
    # 本文件时 pytest 退出码 5（NO_TESTS_COLLECTED）判失败。
    pytest.mark.skipif(
        os.environ.get("VIBELUTION_E2E") != "1",
        reason="e2e 手动车道：设 VIBELUTION_E2E=1 后运行（见 docs/guides/e2e-mock-llm.md）",
    ),
]

# ---------------------------------------------------------------------------
# 独占 mock 供应商标识（与其他车道/文件互不重叠）
# ---------------------------------------------------------------------------

IMG_PROVIDER_ID = "e2e-mock-img"
IMG_MODEL_KEY = "e2e-mock-img-vl"
IMG_MODEL_REF = f"{IMG_PROVIDER_ID}/{IMG_MODEL_KEY}"
IMG_REPLY_MAIN = "图片链路回复：e2e-mock-img 收到图片附件。"
IMG_REPLY_RETRY = "附件重试链路回复：e2e-mock-img 确认整批完成。"
MARKER_MAIN = "E2E-IMG-PIPE-V1"
MARKER_RETRY = "E2E-IMG-RETRY-V1"

# ---------------------------------------------------------------------------

TURN_COMPLETE_TIMEOUT_MS = 120_000
THREAD_ROOT = "div[data-agent-thread-message-count]"
COMPOSER_TEXTAREA = 'textarea[aria-label="发送消息"]'
ATTACH_INPUT = 'input[aria-label="选择附件"]'
ATTACHMENT_TRAY = 'div[role="list"][aria-label="待发送附件"]'
CONTEXT_ATTACHMENT_GROUP = 'div[data-agent-context-group="attachments"]'
TURN_ERROR_BANNER = 'div.turnError[role="status"]'
TURN_ERROR_NOTICE = 'div.turnErrorNotice[role="status"]'
EVIDENCE_DIR = Path(tempfile.gettempdir()) / "vibelution-e2e-image-pipeline"


# ---------------------------------------------------------------------------
# 本地 fixture：运行时生成小 PNG（不提交大二进制）
# ---------------------------------------------------------------------------


def build_png(width: int = 32, height: int = 32, rgb: tuple[int, int, int] = (200, 60, 60)) -> bytes:
    """纯 stdlib 生成真彩 PNG（后端按魔数嗅探为 png，~几百字节）。"""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    row = b"\x00" + bytes(rgb) * width
    raw = row * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


# ---------------------------------------------------------------------------
# aimock runner 脚本（内嵌，tempfile 落盘）
# ---------------------------------------------------------------------------

IMG_RUNNER_SCRIPT = r'''// e2e-mock-img 图片链路剧本（由 test_image_pipeline.py 落盘启动）。
// 图片轮的主调用 user content 是多模态数组（text + image_url part），字符串级
// userMessage 匹配会漏（对比 scenarios/runner.mjs 的口径注释），所以标记匹配在
// JSON.stringify(messages) 上做；标题生成辅助调用（末条 user 文本「用户消息：」
// 开头）由兜底 fixture 接住，必须最后注册。
// 模型可见性探针：主调用 body 超 aimock journal 64KB 条目上限会被清空（见
// test_mock_llm_flow.assert_journal_all_mock 注释），journal 反查不到 image_url；
// 剧本在响应函数里直接检查请求并打印 IMG_E2E_PROBE 行（stdout 落 aimock 日志），
// 测试侧读日志断言 has_image=true。
import { createRequire } from "node:module";
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
const port = Number(flag("--port", "0")) || 0;
const host = String(flag("--host", "127.0.0.1"));

const mock = new LLMock({ port, host, logLevel: "info" });

function isTitleCall(req) {
  const texts = (req.messages || [])
    .filter((m) => m && m.role === "user" && typeof m.content === "string")
    .map((m) => String(m.content).trimStart());
  return texts.length > 0 && texts[texts.length - 1].startsWith("用户消息：");
}
function rawText(req) {
  try { return JSON.stringify(req.messages || []); } catch { return ""; }
}
function imageProbeResponse(marker, content) {
  return (req) => {
    const raw = rawText(req);
    console.log(`IMG_E2E_PROBE marker=${marker} has_image=${raw.includes("image_url")} bytes=${raw.length}`);
    return { content };
  };
}
function markerPredicate(marker) {
  return (req) => !isTitleCall(req) && rawText(req).includes(marker);
}

mock.addFixture({
  match: { predicate: markerPredicate("E2E-IMG-PIPE-V1") },
  response: imageProbeResponse("E2E-IMG-PIPE-V1", "图片链路回复：e2e-mock-img 收到图片附件。"),
  streamingProfile: { ttft: 200, tps: 20, jitter: 0 },
});

mock.addFixture({
  match: { predicate: markerPredicate("E2E-IMG-RETRY-V1") },
  response: imageProbeResponse("E2E-IMG-RETRY-V1", "附件重试链路回复：e2e-mock-img 确认整批完成。"),
  streamingProfile: { ttft: 200, tps: 20, jitter: 0 },
});

// 兜底最后注册：标题生成等辅助调用。
mock.addFixture({
  match: { userMessage: /.*/ },
  response: { content: "ok (e2e-mock-img catch-all)" },
});

const url = await mock.start();
console.log(`E2E_MOCK_IMG_RUNNER_URL=${url}`);
setInterval(() => {}, 1 << 30);
'''


# ---------------------------------------------------------------------------
# config-center 注册（provider id 换成 e2e-mock-img，链路照抄 config_center.py）
# ---------------------------------------------------------------------------


def _img_provider_entry(base_url: str) -> dict[str, Any]:
    """e2e-mock-img provider 条目：复用 e2e-mock 的 v2 canonical 字段集，换 label 与模型表。"""
    entry = config_center.mock_provider_entry(base_url)
    entry["label"] = "E2E Mock Image LLM (aimock)"
    entry["models"] = {
        IMG_MODEL_KEY: {
            "upstream_id": IMG_MODEL_KEY,
            "label": "E2E Mock Image VL (aimock)",
            "wire_protocol": "chat_completions",
            "interaction_contract": "tool_chat",
            "model_protocol": "openai_chat_tools",
            "context_window": 32768,
            # upstream_id 含 "vl" → 后端 vision 名称启发式判 True（模型不判 false
            # 就不会在 add 阶段丢图片附件）。
            "defaults": {"timeout": 90, "connect_timeout": 20, "streaming": True},
        },
    }
    return entry


class ImageProviderSession:
    """e2e-mock-img 的快照 → 注册 → 恢复核对（draft/apply 控制令牌口径）。"""

    def __init__(self, port: int, *, base_url: str) -> None:
        self.port = port
        self.base_url = base_url.rstrip("/").removesuffix("/v1")
        self.provider_base_url = f"{self.base_url}/v1"
        self.snapshot_providers: dict[str, Any] = {}
        self.snapshot_hash = ""

    def _current_providers(self, workspace: dict[str, Any] | None = None) -> dict[str, Any]:
        workspace = workspace or config_center._require_ok(
            *config_center._api_request(self.port, "GET", "/api/config/workspace"),
            "GET /api/config/workspace",
        )
        llm = (workspace.get("publicConfig") or {}).get("llm") or {}
        providers = llm.get("providers") or {}
        return providers if isinstance(providers, dict) else {}

    def snapshot(self) -> None:
        """注册前快照；发现上次残留的 e2e-mock-img 先自愈注销（label 同源才动）。"""
        providers = self._current_providers()
        orphan = providers.get(IMG_PROVIDER_ID)
        if isinstance(orphan, dict):
            if str(orphan.get("label") or "") != str(
                _img_provider_entry("http://127.0.0.1:0/v1").get("label")
            ):
                raise config_center.ConfigCenterError(
                    f"注册前已存在非本车道创建的 {IMG_PROVIDER_ID} provider，拒绝覆盖；请先清理现场再跑。"
                )
            print(f"[img_e2e] 发现上次会话残留的 {IMG_PROVIDER_ID}，先自愈注销")
            self.snapshot_providers = {
                key: value for key, value in providers.items() if key != IMG_PROVIDER_ID
            }
            self.restore_and_verify()
            providers = self._current_providers()
        self.snapshot_providers = json.loads(json.dumps(providers))
        workspace = config_center._require_ok(
            *config_center._api_request(self.port, "GET", "/api/config/workspace"),
            "GET /api/config/workspace",
        )
        self.snapshot_hash = str(workspace.get("hash") or "")

    def register(self) -> None:
        """draft 注册 → apply 落盘 → 回读核对；共享 config 409 冲突限次重试。"""
        last_error: Exception | None = None
        for attempt in range(1, config_center.APPLY_CONFLICT_RETRIES + 1):
            try:
                self._register_once()
                return
            except config_center.ConfigCenterError as exc:
                if "HTTP 409" not in str(exc):
                    raise
                last_error = exc
                print(f"[img_e2e] apply 基线冲突（第 {attempt} 次），重读配置重试: {exc}")
                time.sleep(1.0)
        raise last_error  # type: ignore[misc]

    def _register_once(self) -> None:
        workspace = config_center._require_ok(
            *config_center._api_request(self.port, "GET", "/api/config/workspace"),
            "GET /api/config/workspace",
        )
        base_hash = str(workspace.get("hash") or "")
        if not base_hash:
            raise config_center.ConfigCenterError("workspace 未返回 hash，无法作为 baseHash")
        draft = config_center._require_ok(
            *config_center._api_request(
                self.port,
                "POST",
                "/api/config/draft/providers",
                {
                    "publicConfig": workspace.get("publicConfig") or {},
                    "draftMeta": {"source": "e2e-mock-img"},
                    "baseHash": base_hash,
                    "providerId": IMG_PROVIDER_ID,
                    "provider": _img_provider_entry(self.provider_base_url),
                },
            ),
            "POST /api/config/draft/providers",
        )
        drafted_config = draft.get("publicConfig")
        if not isinstance(drafted_config, dict):
            raise config_center.ConfigCenterError(f"草稿响应缺 publicConfig: {json.dumps(draft)[:400]}")
        # 注意层级：draft 是 workspace 信封，providers 检查必须传 workspace 本身
        # （config_center._register_once 同款口径），传 drafted_config 会少一层。
        if IMG_PROVIDER_ID not in self._current_providers(draft):
            raise config_center.ConfigCenterError(
                f"草稿未见 {IMG_PROVIDER_ID}: providers={sorted(self._current_providers(draft))}"
            )
        applied = config_center._require_ok(
            *config_center._api_request(
                self.port,
                "PUT",
                "/api/config/apply",
                {
                    "publicConfig": drafted_config,
                    "draftMeta": {"source": "e2e-mock-img"},
                    "baseHash": base_hash,
                    "baseConfig": None,
                },
            ),
            "PUT /api/config/apply",
        )
        entry = self._current_providers(applied).get(IMG_PROVIDER_ID)
        if not isinstance(entry, dict):
            raise config_center.ConfigCenterError(
                f"apply 后回读未见 {IMG_PROVIDER_ID}（apply 失败，保现场）"
            )
        if str(entry.get("base_url") or "") != self.provider_base_url:
            raise config_center.ConfigCenterError(
                f"apply 后 base_url 不符: {entry.get('base_url')!r} != {self.provider_base_url!r}"
            )
        print(f"[img_e2e] provider {IMG_PROVIDER_ID} 已注册: base_url={self.provider_base_url}")

    def restore_and_verify(self) -> None:
        """注销 e2e-mock-img 并 apply，核对快照 provider 全部在位、本 provider 零残留。"""
        last_error: Exception | None = None
        for attempt in range(1, config_center.APPLY_CONFLICT_RETRIES + 1):
            try:
                self._restore_once()
                self._verify_restored()
                return
            except config_center.ConfigCenterError as exc:
                if "HTTP 409" not in str(exc):
                    raise
                last_error = exc
                print(f"[img_e2e] 恢复 apply 基线冲突（第 {attempt} 次），重试: {exc}")
                time.sleep(1.0)
        raise last_error  # type: ignore[misc]

    def _restore_once(self) -> None:
        workspace = config_center._require_ok(
            *config_center._api_request(self.port, "GET", "/api/config/workspace"),
            "GET /api/config/workspace",
        )
        base_hash = str(workspace.get("hash") or "")
        providers = self._current_providers(workspace)
        entry = providers.get(IMG_PROVIDER_ID)
        if not isinstance(entry, dict):
            print(f"[img_e2e] {IMG_PROVIDER_ID} 已不在配置中，跳过注销")
            return
        drafted = workspace.get("publicConfig") or {}
        models = entry.get("models") or {}
        for model_key in sorted(models):
            drafted = config_center._require_ok(
                *config_center._api_request(
                    self.port,
                    "DELETE",
                    f"/api/config/draft/providers/{IMG_PROVIDER_ID}/models/{model_key}",
                    {
                        "publicConfig": drafted,
                        "draftMeta": {"source": "e2e-mock-img"},
                        "baseHash": base_hash,
                        "providerId": IMG_PROVIDER_ID,
                        "upstreamId": str((models.get(model_key) or {}).get("upstream_id") or ""),
                        "modelKey": model_key,
                    },
                ),
                f"DELETE draft models/{model_key}",
            ).get("publicConfig")
        drafted = config_center._require_ok(
            *config_center._api_request(
                self.port,
                "DELETE",
                f"/api/config/draft/providers/{IMG_PROVIDER_ID}",
                {
                    "publicConfig": drafted,
                    "draftMeta": {"source": "e2e-mock-img"},
                    "baseHash": base_hash,
                    "providerId": IMG_PROVIDER_ID,
                },
            ),
            f"DELETE draft providers/{IMG_PROVIDER_ID}",
        ).get("publicConfig")
        config_center._require_ok(
            *config_center._api_request(
                self.port,
                "PUT",
                "/api/config/apply",
                {
                    "publicConfig": drafted,
                    "draftMeta": {"source": "e2e-mock-img"},
                    "baseHash": base_hash,
                    "baseConfig": None,
                },
            ),
            "PUT /api/config/apply (restore)",
        )

    def _verify_restored(self) -> None:
        providers = self._current_providers()
        if IMG_PROVIDER_ID in providers:
            raise config_center.ConfigCenterError(
                f"恢复后仍存在 {IMG_PROVIDER_ID}（注销失败，保现场待排查）"
            )
        missing = sorted(set(self.snapshot_providers) - set(providers))
        if missing:
            raise config_center.ConfigCenterError(f"快照中的 provider 被外部改动删除: {missing}")
        print(f"[img_e2e] {IMG_PROVIDER_ID} 已注销；快照 provider 全部在位: {sorted(providers) or '(空)'}")


@dataclass
class ImageMockHandle:
    """本文件独占的 aimock + provider 会话句柄。"""

    instance_port: int
    server: aimock_runtime.AimockServer
    center: ImageProviderSession

    def create_agent(self, display_name: str) -> dict[str, str]:
        """建 chat Agent 并把 dialogue 槽绑到 e2e-mock-img/e2e-mock-img-vl。"""
        from tests.e2e.helpers.instance_registry import fetch_json
        from tests.e2e.mock_llm.config_center import ConfigCenterError, _api_request

        def _post(path: str, payload: dict) -> dict:
            last_exc: Exception | None = None
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

        catalog = fetch_json(self.instance_port, "/api/prompt-templates")
        templates = catalog.get("templates") or []
        template_id = next(
            (str((item or {}).get("templateId") or "").strip() for item in templates
             if str((item or {}).get("templateId") or "").strip()),
            "",
        )
        if not template_id:
            raise RuntimeError(f"实例无可用提示词模板，无法创建 Agent: {str(catalog)[:200]}")
        agent = _post(
            "/api/agents",
            {
                "displayName": display_name,
                "primaryMode": "chat",
                "promptTemplateId": template_id,
                "llmBindings": {"dialogue": {"modelId": IMG_MODEL_REF}},
            },
        )
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id:
            raise RuntimeError(f"agent 创建响应缺 agentId: {str(agent)[:300]}")
        session_id = str(agent.get("directSessionId") or "").strip()
        if not session_id:
            result = fetch_json(self.instance_port, f"/api/sessions/query?agentId={agent_id}")
            items = result.get("items") or result.get("sessions") or []
            if items:
                session_id = str(items[0].get("id") or "")
        if not session_id:
            raise RuntimeError(f"agent {agent_id} 未找到关联会话")
        return {"agentId": agent_id, "sessionId": session_id}

    def delete_agent(self, agent_id: str, *, timeout_seconds: float = 60.0) -> None:
        """归档 + purge 测试 Agent 并回读核对（live llmBinding 引用会挡 provider 注销）。"""
        from tests.e2e.mock_llm.config_center import ConfigCenterError, _api_request

        def _delete(path: str) -> None:
            try:
                _api_request(self.instance_port, "DELETE", path, timeout_seconds=90.0)
            except (TimeoutError, OSError, ConfigCenterError) as exc:
                print(f"[img_e2e] DELETE {path} 瞬态失败，重试: {exc}")

        def _agent_present() -> bool:
            try:
                status, result = _api_request(
                    self.instance_port, "GET", "/api/agents?includeArchived=true",
                    timeout_seconds=30.0,
                )
            except (TimeoutError, OSError, ConfigCenterError):
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
        print(f"[img_e2e] 测试 Agent 删除未闭环（仍带 live llmBinding）: {agent_id}")


@pytest.fixture(scope="module")
def img_mock(e2e_instance: Any):
    """独占 aimock（内嵌 runner）+ e2e-mock-img provider 注册；拆机先注销再停进程。"""
    runner_dir = Path(tempfile.mkdtemp(prefix="e2e-img-runner-"))
    runner_path = runner_dir / "img_runner.mjs"
    runner_path.write_text(IMG_RUNNER_SCRIPT, encoding="utf-8")
    server = aimock_runtime.start_aimock(runner_dir, script=runner_path)
    center = ImageProviderSession(e2e_instance.port, base_url=server.base_url)
    try:
        center.snapshot()
        center.register()
    except Exception:
        try:
            server.stop()
            server.assert_stopped()
        except Exception as stop_exc:  # noqa: BLE001 - 不掩盖注册失败原始错误
            print(f"[img_e2e] 注册失败后的 aimock 补停未闭环: {stop_exc}")
        raise
    handle = ImageMockHandle(instance_port=e2e_instance.port, server=server, center=center)
    print(f"[img_e2e] 会话就绪: aimock={server.base_url} provider={IMG_PROVIDER_ID}")
    yield handle
    teardown_error: Exception | None = None
    try:
        center.restore_and_verify()
    except Exception as exc:  # noqa: BLE001 - 恢复失败要报告并保现场
        teardown_error = exc
        print(f"[img_e2e] provider 注销/恢复失败（保现场）: {exc}")
    try:
        server.stop()
        server.assert_stopped()
    except Exception as exc:  # noqa: BLE001 - 进程零残留是硬指标
        print(f"[img_e2e] aimock 拆机异常: {exc}")
        if teardown_error is None:
            teardown_error = exc
    if teardown_error is not None:
        raise teardown_error


@pytest.fixture
def img_agent(img_mock: ImageMockHandle) -> Any:
    """建一个绑 e2e-mock-img 的 Agent；用例结束归档+purge。"""
    created = img_mock.create_agent("E2E Image Pipeline Agent")
    yield created
    img_mock.delete_agent(created["agentId"])


@pytest.fixture(autouse=True)
def isolate_img_mock_per_test(img_mock: ImageMockHandle) -> dict[str, int]:
    """用例级隔离：清空本车道 aimock journal（共享 conftest 的 autouse 只清共享
    那台），并快照探针行偏移，防止前一用例的 journal/探针行为本用例兜底。"""
    img_mock.server.reset_journal()
    state = {"probe_offset": len(probe_lines(img_mock))}
    yield state


# ---------------------------------------------------------------------------
# 共享步骤（口径照抄 test_mock_llm_flow.py，按本车道锚点裁剪）
# ---------------------------------------------------------------------------


def save_failure_evidence(page: Any, name: str) -> None:
    """关键断言失败时把页面现场截图落到系统临时目录（取证，不写 checkout）。"""
    try:
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        path = EVIDENCE_DIR / f"{name}-{int(time.time())}.png"
        page.screenshot(path=str(path), full_page=True)
        print(f"[img_e2e] 失败现场截图: {path}")
    except Exception as exc:  # noqa: BLE001 - 取证失败不掩盖原始断言错误
        print(f"[img_e2e] 截图失败: {exc}")


def open_agent_chat(page: Any, e2e_instance: Any, session_id: str) -> None:
    from tests.e2e.helpers.page_anchors import wait_route_ready

    page.goto(
        f"{e2e_instance.base_url}/chat?session={session_id}",
        wait_until="domcontentloaded",
    )
    wait_route_ready(page)
    page.locator(THREAD_ROOT).first.wait_for(state="visible", timeout=20_000)


def _attr(holder: Any, name: str, *, timeout_ms: int = 800) -> str:
    try:
        return holder.get_attribute(name, timeout=timeout_ms) or ""
    except Exception:  # noqa: BLE001 - playwright 定位失败即视为元素已消失
        return ""


def thread_status_and_count(page: Any) -> tuple[str, int]:
    thread = page.locator(THREAD_ROOT).first
    status = _attr(thread, "data-agent-thread-status")
    try:
        count = int(_attr(thread, "data-agent-thread-message-count") or "0")
    except ValueError:
        count = 0
    return status, count


def wait_turn_closed(page: Any, *, expected_messages: int, timeout_ms: int = TURN_COMPLETE_TIMEOUT_MS) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    status, count = thread_status_and_count(page)
    while time.monotonic() < deadline:
        status, count = thread_status_and_count(page)
        if status == "idle" and count >= expected_messages:
            return
        page.wait_for_timeout(200)
    raise AssertionError(
        f"thread 未收口（status={status} count={count}，预期 idle 且 count>={expected_messages}）"
    )


def thread_text(page: Any) -> str:
    return page.locator(THREAD_ROOT).first.inner_text()


def wait_thread_text(page: Any, needle: str, *, timeout_ms: int = 15_000) -> str:
    """等指定文本上屏（idle 投影可能晚一拍，见 test_mock_llm_flow 同名注释）。"""
    deadline = time.monotonic() + timeout_ms / 1000
    texts = thread_text(page)
    while needle not in texts and time.monotonic() < deadline:
        page.wait_for_timeout(200)
        texts = thread_text(page)
    return texts


def send_message(page: Any, text: str) -> None:
    composer = page.locator(COMPOSER_TEXTAREA).first
    composer.wait_for(state="visible", timeout=15_000)
    composer.click()
    composer.fill(text)
    composer.press("Enter")


def add_attachments(page: Any, paths: list[Path]) -> None:
    """经附件 file input 注入本地文件；等待 tray chips 上屏。"""
    hidden = page.locator(ATTACH_INPUT).first
    hidden.wait_for(state="attached", timeout=15_000)
    hidden.set_input_files([str(path) for path in paths])
    page.locator(ATTACHMENT_TRAY).first.wait_for(state="visible", timeout=15_000)


def tray_chip(page: Any, filename: str) -> Any:
    """tray 内指定文件名的 chip（role=listitem，aria-invalid 标失败态）。"""
    return page.locator(
        f'{ATTACHMENT_TRAY} div[role="listitem"]:has-text("{filename}")'
    ).first


def wait_upload_failed_chip(page: Any, filename: str, *, timeout_ms: int = 30_000) -> None:
    """等失败 chip 呈现可重试状态：aria-invalid + 失败提示 + 单 chip 重试按钮。"""
    chip = tray_chip(page, filename)
    deadline = time.monotonic() + timeout_ms / 1000
    last = ""
    while time.monotonic() < deadline:
        invalid = _attr(chip, "aria-invalid")
        hint = chip.locator('span:has-text("上传失败，可重试")')
        retry = page.locator(f'button[aria-label="重试上传: {filename}"]')
        last = f"aria-invalid={invalid!r} hint={hint.count()} retry={retry.count()}"
        if invalid == "true" and hint.count() >= 1 and retry.count() >= 1:
            return
        page.wait_for_timeout(250)
    save_failure_evidence(page, f"upload-failed-chip-{filename}")
    raise AssertionError(f"失败 chip 未呈现可重试状态（{filename}）: {last}")


def assert_chip_uploaded(page: Any, filename: str, *, timeout_ms: int = 30_000) -> None:
    """等 chip 到达稳定的已上传态：非失败、非上传中、无重试按钮。

    「上传中」态同样没有 aria-invalid 与重试按钮，必须一并排除，否则重试在途时
    会提前判定成功（错误条与上传完成同批渲染，随后才会消失）。
    """
    chip = tray_chip(page, filename)
    deadline = time.monotonic() + timeout_ms / 1000
    last = ""
    while time.monotonic() < deadline:
        invalid = _attr(chip, "aria-invalid")
        retry = page.locator(f'button[aria-label="重试上传: {filename}"]')
        uploading = chip.locator('span:has-text("上传中")')
        failed_hint = chip.locator('span:has-text("上传失败，可重试")')
        last = f"aria-invalid={invalid!r} retry={retry.count()} uploading={uploading.count()} failed={failed_hint.count()}"
        if invalid != "true" and retry.count() == 0 and uploading.count() == 0 and failed_hint.count() == 0:
            return
        page.wait_for_timeout(250)
    save_failure_evidence(page, f"chip-not-uploaded-{filename}")
    raise AssertionError(f"chip 未回到已上传态（{filename}）: {last}")


def _dump_attachment_evidence(e2e_instance: Any, session_id: str) -> None:
    """失败取证：消息附件元数据 + 直接探测 artifact URL 的可达性。"""
    import urllib.error
    import urllib.request

    urls: list[str] = []
    try:
        detail = e2e_instance.api_get(f"/api/sessions/{session_id}")
        for message in detail.get("messages") or []:
            attachments = message.get("attachments") or []
            if not attachments:
                continue
            print(
                f"[img_e2e] 证据 message role={message.get('role')} "
                f"attachments={json.dumps(attachments, ensure_ascii=False)[:600]}"
            )
            for attachment in attachments:
                url = str(attachment.get("url") or attachment.get("imageUrl") or "")
                if url:
                    urls.append(url)
    except Exception as exc:  # noqa: BLE001 - 取证失败不掩盖原始断言错误
        print(f"[img_e2e] 会话详情取证失败: {exc}")
    for url in urls:
        try:
            with urllib.request.urlopen(
                f"{e2e_instance.base_url}{url}", timeout=10
            ) as response:
                print(
                    f"[img_e2e] artifact GET {url} -> HTTP {response.status} "
                    f"type={response.headers.get('content-type')} "
                    f"bytes={response.headers.get('content-length')}"
                )
        except urllib.error.HTTPError as exc:
            print(f"[img_e2e] artifact GET {url} -> HTTP {exc.code}")
        except Exception as exc:  # noqa: BLE001 - 取证失败保打印
            print(f"[img_e2e] artifact GET {url} -> {exc}")


def assert_context_attachment_present(
    page: Any,
    filename: str,
    *,
    timeout_ms: int = 20_000,
) -> None:
    """历史消息里该文件名的附件卡片可见（用户上下文附件组 + figure 锚点）。

    链路用例钉「附件以原始文件名出现在历史消息里」；img 形态（必须以 ``<img>``
    真实加载）由 test_history_image_renders_as_img 硬断言钉住。
    """
    figure = page.locator(f'figure[data-agent-context-attachment-name="{filename}"]').first
    try:
        figure.wait_for(state="visible", timeout=timeout_ms)
    except Exception:
        save_failure_evidence(page, f"attachment-figure-missing-{filename}")
        raise
    label = _attr(figure, "aria-label")
    assert filename in label, f"附件 figure aria-label 缺文件名: {label!r}"


def assert_context_image_loaded(
    page: Any,
    e2e_instance: Any,
    session_id: str,
    filename: str,
    *,
    timeout_ms: int = 20_000,
) -> None:
    """历史消息里的图片必须以 <img> 形态真实加载（钉 onError 降级文件卡回归）。"""
    figure = page.locator(f'figure[data-agent-context-attachment-name="{filename}"]').first
    try:
        figure.wait_for(state="visible", timeout=timeout_ms)
    except Exception:
        save_failure_evidence(page, f"attachment-figure-missing-{filename}")
        _dump_attachment_evidence(e2e_instance, session_id)
        raise
    img = figure.locator("img").first
    deadline = time.monotonic() + timeout_ms / 1000
    had_img = False
    while time.monotonic() < deadline:
        if img.count() >= 1:
            had_img = True
            try:
                img.scroll_into_view_if_needed(timeout=2_000)
                if bool(img.evaluate("el => el.complete && el.naturalWidth > 0")):
                    return
            except Exception:  # noqa: BLE001 - 元素瞬时分离则继续轮询
                pass
        page.wait_for_timeout(250)
    save_failure_evidence(page, f"attachment-image-not-loaded-{filename}")
    _dump_attachment_evidence(e2e_instance, session_id)
    if had_img:
        raise AssertionError(
            f"历史消息图片未完成解码（{filename}）：img 存在但 complete/naturalWidth 不满足（疑 URL 加载失败）"
        )
    raise AssertionError(
        f"历史消息图片未以 <img> 渲染（{filename}）：figure 可见但无 img（onError 降级文件卡或分类回退），"
        "详见上方 attachments/artifact 取证"
    )


def _is_title_entry(entry: dict[str, Any]) -> bool:
    """journal 条目是否为标题生成等辅助调用（口径照抄 test_mock_llm_flow）。

    主调用 body 超 aimock journal 64KB 条目上限时 body 被清空（None/空串）——
    据此把「body 为空」的条目视为主调用；标题调用 body 小且末条 user 文本以
    「用户消息：」开头。
    """
    body = entry.get("body")
    if not body:
        return False
    messages = (body or {}).get("messages") or []
    for message in reversed(messages):
        if (message or {}).get("role") == "user":
            return str((message or {}).get("content") or "").lstrip().startswith("用户消息：")
    return False


def assert_main_call_reached_mock(img_mock: ImageMockHandle) -> int:
    """journal 钉主调用真实打到 e2e-mock-img 并以 200 被服务。

    主调用 body 超 journal 64KB 上限会被清空，无法（也不应）从 journal 反查
    image_url；图片对模型的可见性由 assert_probe_saw_image 用 runner 探针钉。
    """
    entries = img_mock.server.journal(path="/v1/chat/completions")
    assert entries, "journal 为空：产品没有向 e2e-mock-img 发起请求"
    mains = [
        entry
        for entry in entries
        if not _is_title_entry(entry)
        and int(entry.get("response", {}).get("status") or 0) == 200
    ]
    assert mains, (
        f"journal 无 200 主调用（只有标题生成等辅助调用）：条目数={len(entries)}"
    )
    bodies = [entry.get("body") for entry in entries if entry.get("body")]
    unexpected = {
        str((body or {}).get("model") or "")
        for body in bodies
        if str((body or {}).get("model") or "")
    } - {IMG_MODEL_KEY}
    assert not unexpected, f"journal 出现意外 model: {unexpected}"
    return len(mains)


def probe_lines(img_mock: ImageMockHandle) -> list[str]:
    """读取 aimock 日志里的全部探针行（IMG_E2E_PROBE）。"""
    log_path = img_mock.server.log_path
    assert log_path is not None and Path(log_path).is_file(), "aimock 日志文件不存在，探针不可用"
    return [
        line.strip()
        for line in Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()
        if "IMG_E2E_PROBE" in line
    ]


def assert_probe_saw_image(img_mock: ImageMockHandle, marker: str, *, offset: int = 0) -> None:
    """读 aimock runner 日志探针：该标记的主调用请求体必须含 image_url 块。

    这是「历史图片对模型可见」（9bd376b8b）的请求面硬证据：探针由剧本响应函数
    在真实请求上打印（IMG_E2E_PROBE marker=... has_image=...），不经 journal。
    ``offset`` 之前是本用例开始前的历史行（同一标记跨用例复用时避免旧行兜底）。
    """
    lines = [line for line in probe_lines(img_mock)[offset:] if marker in line]
    assert lines, f"探针无 {marker} 的主调用记录（主调用未命中剧本标记）"
    hits = [line for line in lines if "has_image=true" in line]
    assert hits, (
        f"主调用请求体不含 image_url 块（历史图片对模型可见性回归）：探针={lines!r}"
    )
    print(f"[img_e2e] 探针 {marker}: {hits[-1]}")


def assert_no_error_surface(page: Any) -> None:
    errors = page.locator('section[data-vui="state-surface"][data-tone="error"]')
    assert errors.count() == 0, f"出现 error 状态面（count={errors.count()}）"


def assert_no_turn_error_card(page: Any) -> None:
    assert page.locator(TURN_ERROR_BANNER).count() == 0, "出现「请求错误」实时错误横幅"
    assert page.locator(TURN_ERROR_NOTICE).count() == 0, "出现时间线内联错误卡"


def wait_turn_reached_mock(img_mock: ImageMockHandle, *, timeout_ms: int = 10_000) -> bool:
    """等主调用请求真实打到 aimock（乐观态冻结/turn 静默丢弃的启动证据）。"""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if img_mock.server.journal(path="/v1/chat/completions"):
            return True
        page_wait = 250
        time.sleep(page_wait / 1000)
    return False


def send_with_image_and_close(
    page: Any,
    img_mock: ImageMockHandle,
    marker: str,
    image_path: Path,
    *,
    expected_messages: int = 2,
) -> None:
    """上传一张图 → 带标记发送 → 等 turn 收口（含 turn 静默丢弃的一次重发兜底）。"""
    add_attachments(page, [image_path])
    send_message(page, marker)
    if not wait_turn_reached_mock(img_mock):
        # 同实例多轮后的偶发静默丢弃（见 test_mock_llm_flow.complete_turn 注释）：
        # 主调用未到 mock 就重发一次再收口。
        print("[img_e2e] 提交后主调用未到 mock（turn 疑似静默丢弃），重发一次")
        send_message(page, marker)
        assert wait_turn_reached_mock(img_mock, timeout_ms=15_000), "重发后 turn 仍未启动"
    wait_turn_closed(page, expected_messages=expected_messages)
    if not img_mock.server.journal(path="/v1/chat/completions"):
        print("[img_e2e] turn 收口但主调用未到 mock，重发一次")
        send_message(page, marker)
        wait_turn_closed(page, expected_messages=expected_messages + 2)


# ---------------------------------------------------------------------------
# 用例
# ---------------------------------------------------------------------------


def test_composer_upload_send_reply_and_model_sees_image(
    page: Any, e2e_instance: Any, img_mock: ImageMockHandle, img_agent: dict[str, str],
    isolate_img_mock_per_test: dict[str, int], tmp_path: Path,
) -> None:
    """场景 1：composer 上传一张图 → 发送 → 用户消息图片附件可见 → mock 回复到达。

    「图片真的到了模型」（9bd376b8b 请求面）两层钉：journal 证明主调用 200；
    runner 探针证明该主调用请求体含 image_url 块。降采样阶梯缓存（6731377d8）
    在模型输入归一化层，无 UI 锚点，由探针断言间接钉住 data-url 链路真实执行。
    """
    image_path = tmp_path / "e2e-img-alpha.png"
    image_path.write_bytes(build_png())
    open_agent_chat(page, e2e_instance, img_agent["sessionId"])

    send_with_image_and_close(page, img_mock, MARKER_MAIN, image_path)

    assert_no_error_surface(page)
    assert_no_turn_error_card(page)
    # mock 回复上时间线。
    texts = wait_thread_text(page, IMG_REPLY_MAIN)
    assert IMG_REPLY_MAIN in texts, f"mock 回复未上时间线: {texts[:300]!r}"
    # 用户消息里图片附件以原始文件名可见（img 真实加载由
    # test_history_image_renders_as_img 硬断言钉住）。
    assert_context_attachment_present(page, "e2e-img-alpha.png")
    group = page.locator(CONTEXT_ATTACHMENT_GROUP).first
    count = _attr(group, "data-agent-context-group-count")
    assert count == "1", f"用户上下文附件组计数异常: {count!r}"
    # 图片到了模型：journal 证明主调用 200，runner 探针证明请求体含 image_url。
    mains = assert_main_call_reached_mock(img_mock)
    assert_probe_saw_image(img_mock, MARKER_MAIN, offset=isolate_img_mock_per_test["probe_offset"])
    print(f"[img_e2e] 主调用 200 条目数={mains}")


def test_image_visible_after_page_reload(
    page: Any, e2e_instance: Any, img_mock: ImageMockHandle, img_agent: dict[str, str],
    isolate_img_mock_per_test: dict[str, int], tmp_path: Path,
) -> None:
    """场景 2：发送带图消息后 reload，图片在历史消息里仍然可见（历史可见性）。"""
    image_path = tmp_path / "e2e-img-history.png"
    image_path.write_bytes(build_png(rgb=(60, 120, 200)))
    open_agent_chat(page, e2e_instance, img_agent["sessionId"])

    send_with_image_and_close(page, img_mock, MARKER_MAIN, image_path)
    texts = wait_thread_text(page, IMG_REPLY_MAIN)
    assert IMG_REPLY_MAIN in texts

    page.reload(wait_until="domcontentloaded")
    from tests.e2e.helpers.page_anchors import wait_route_ready

    wait_route_ready(page)
    page.locator(THREAD_ROOT).first.wait_for(state="visible", timeout=20_000)
    wait_thread_text(page, IMG_REPLY_MAIN)
    assert_context_attachment_present(page, "e2e-img-history.png")
    assert_no_error_surface(page)


def test_multi_file_upload_allsettled_retry(
    page: Any, e2e_instance: Any, img_mock: ImageMockHandle, img_agent: dict[str, str],
    isolate_img_mock_per_test: dict[str, int], tmp_path: Path,
) -> None:
    """场景 3：多文件上传单个失败不拖死整批，失败项可重试，重试后整批可发送。

    allSettled 语义钉点（2da5a4902）：
    - 失败注入只命中 bad.png 的上传请求（二进制路径按 X-Vibelution-Filename 头，
      零拷贝 JSON 路径按 body 文件名，两种模式都覆盖）；
    - good.png 正常拿到 artifact（chip 不带失败态）；
    - 整批不发送：无 turn 启动（thread idle）、无回复上屏、mock 无主调用；
      草稿恢复到 composer、出现失败提示与「重试上传」入口（错误行 retry-all +
      单 chip 重试按钮）；
    - 解除注入 → 单 chip 重试成功（chip 回已上传态、成功项不重传）→ 再次发送，
      turn 正常收口且两张图都在用户消息里可见。
    """
    good_path = tmp_path / "e2e-img-good.png"
    bad_path = tmp_path / "e2e-img-bad.png"
    good_path.write_bytes(build_png(rgb=(40, 160, 90)))
    bad_path.write_bytes(build_png(rgb=(180, 40, 40)))
    draft = f"{MARKER_RETRY} 验证失败重试链路"
    open_agent_chat(page, e2e_instance, img_agent["sessionId"])

    add_attachments(page, [good_path, bad_path])

    def fail_bad_uploads(route: Any) -> None:
        request = route.request
        header = urllib.parse.unquote(request.header_value("x-vibelution-filename") or "")
        content_type = (request.header_value("content-type") or "").lower()
        body_hit = content_type.startswith("application/json") and "e2e-img-bad.png" in (
            request.post_data or ""
        )
        if header == "e2e-img-bad.png" or body_hit:
            route.abort("failed")
            return
        route.fallback()

    page.route("**/api/sessions/*/attachments", fail_bad_uploads)
    try:
        send_message(page, draft)
        # 失败项呈现可重试状态；成功项不受牵连。
        wait_upload_failed_chip(page, "e2e-img-bad.png")
        assert_chip_uploaded(page, "e2e-img-good.png")
        # 失败提示 + retry-all 入口（错误行）。
        alert = page.locator('p[role="alert"]')
        assert alert.count() >= 1, "composer 未出现上传失败提示（role=alert）"
        retry_all = page.locator('p[role="alert"] button:has-text("重试上传")')
        assert retry_all.count() >= 1, "错误行未出现「重试上传」retry-all 按钮"
        # allSettled 闸门：整批不发送——没有 turn 启动、没有回复上屏、mock 没有
        # 主调用（实测：乐观用户行会残留在时间线上，见模块头缺陷记录；这里钉
        # 「不发送」语义本身，不钉乐观行的清理时序）。
        status, _count = thread_status_and_count(page)
        assert status == "idle", f"上传失败后 thread 未回到 idle: {status!r}"
        texts_now = thread_text(page)
        assert IMG_REPLY_RETRY not in texts_now, "失败批次不应有任何回复上屏"
        mains_now = [
            entry
            for entry in img_mock.server.journal(path="/v1/chat/completions")
            if not _is_title_entry(entry)
        ]
        assert not mains_now, f"失败批次不应产生主调用（journal 非辅助条目={len(mains_now)}）"
        # 草稿恢复：提交被上传失败拦下后原文回到 composer。
        value = page.locator(COMPOSER_TEXTAREA).first.input_value()
        assert draft in value, f"失败后草稿未恢复到 composer: {value[:120]!r}"
    finally:
        page.unroute("**/api/sessions/*/attachments")

    # 重试成功：只补传失败项，成功项保留 artifact 不重传（无新增上传请求）。
    journal_before = len(img_mock.server.journal(path="/v1/chat/completions"))
    page.locator('button[aria-label="重试上传: e2e-img-bad.png"]').first.click()
    assert_chip_uploaded(page, "e2e-img-bad.png")
    deadline = time.monotonic() + 8_000 / 1000
    while page.locator('p[role="alert"]').count() > 0 and time.monotonic() < deadline:
        page.wait_for_timeout(200)
    assert page.locator('p[role="alert"]').count() == 0, "重试成功后失败提示未清除"

    # 整批完成后可发送：草稿仍在，直接发送。
    composer = page.locator(COMPOSER_TEXTAREA).first
    composer.click()
    if draft not in composer.input_value():
        composer.fill(draft)
    composer.press("Enter")
    wait_turn_closed(page, expected_messages=2)
    assert_no_error_surface(page)
    assert_no_turn_error_card(page)
    texts = wait_thread_text(page, IMG_REPLY_RETRY)
    assert IMG_REPLY_RETRY in texts, f"重试后的回复未上时间线: {texts[:300]!r}"
    assert_context_attachment_present(page, "e2e-img-good.png")
    assert_context_attachment_present(page, "e2e-img-bad.png")
    mains = assert_main_call_reached_mock(img_mock)
    assert_probe_saw_image(img_mock, MARKER_RETRY, offset=isolate_img_mock_per_test["probe_offset"])
    print(
        f"[img_e2e] 重试链路 journal：主调用 200 条目={mains}，"
        f"重试前后 chat journal 条目={journal_before}->{len(img_mock.server.journal(path='/v1/chat/completions'))}"
    )


def test_draft_survives_reload(
    page: Any, e2e_instance: Any, img_agent: dict[str, str]
) -> None:
    """场景 4：composer 草稿 reload 后保留（localStorage 450ms 防抖）。

    附件 tray 是内存态、reload 后清空是产品文档化行为（chatDraftPersistence
    「plain text only (no attachments)」），这里只断言事实并打印，不判失败。
    """
    draft = "E2E-IMG-DRAFT 草稿保留验证文本"
    open_agent_chat(page, e2e_instance, img_agent["sessionId"])
    composer = page.locator(COMPOSER_TEXTAREA).first
    composer.click()
    composer.fill(draft)
    # 等过 450ms 防抖写入窗口再 reload。
    page.wait_for_timeout(1_200)
    page.reload(wait_until="domcontentloaded")
    from tests.e2e.helpers.page_anchors import wait_route_ready

    wait_route_ready(page)
    composer = page.locator(COMPOSER_TEXTAREA).first
    composer.wait_for(state="visible", timeout=20_000)
    value = composer.input_value()
    assert draft in value, f"reload 后草稿未保留: {value[:120]!r}"
    tray_count = page.locator(ATTACHMENT_TRAY).count()
    print(f"[img_e2e] reload 后附件 tray 可见数={tray_count}（内存态不持久化，产品文档化行为）")


def test_history_image_renders_as_img(
    page: Any, e2e_instance: Any, img_mock: ImageMockHandle, img_agent: dict[str, str],
    isolate_img_mock_per_test: dict[str, int], tmp_path: Path,
) -> None:
    """硬断言：历史消息中的上传图片必须以 <img> 真实渲染，而不是降级文件卡。

    历史缺陷（2026-09-29 取证，已修复）：附件元数据正确（kind=user_image、
    imageUrl 指向 artifact 路由），但浏览器 <img> 请求该路由被
    WebControlGuardMiddleware 以「Missing or invalid web control token」403
    拒绝，前端 onError 后降级为文件卡（figure 内无 img）。修复：会话图片
    artifact 的 GET 走 _SOURCE_ONLY_GET_PATH_PREFIXES 窄口放行（仅图片扩展名，
    文档 artifact 与 mutating 方法仍要 token），下载导航（无 token 的
    ``?download=1`` GET）同批恢复可达。
    """
    image_path = tmp_path / "e2e-img-render.png"
    image_path.write_bytes(build_png(rgb=(90, 90, 210)))
    open_agent_chat(page, e2e_instance, img_agent["sessionId"])
    send_with_image_and_close(page, img_mock, MARKER_MAIN, image_path)
    wait_thread_text(page, IMG_REPLY_MAIN)
    page.reload(wait_until="domcontentloaded")
    from tests.e2e.helpers.page_anchors import wait_route_ready

    wait_route_ready(page)
    page.locator(THREAD_ROOT).first.wait_for(state="visible", timeout=20_000)
    assert_probe_saw_image(img_mock, MARKER_MAIN, offset=isolate_img_mock_per_test["probe_offset"])
    assert_context_image_loaded(page, e2e_instance, img_agent["sessionId"], "e2e-img-render.png")
