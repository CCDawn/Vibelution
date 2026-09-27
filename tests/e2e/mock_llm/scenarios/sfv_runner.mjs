// SFV 车道专用剧本服务器（stream failure visibility e2e 自持 aimock）。
//
// 为什么不复用共享 runner.mjs（2026-09-26 实测结论）：mock_llm 车道的 provider
// 注册落在**共享 operator config** 上，且 provider id 固定为 e2e-mock。同机并行
// 的另一 e2e 会话（同 lane 不同任务）会在 snapshot 自愈/teardown 时把 e2e-mock
// 注销，双向互踩（实测 run2/3/5 三次失败均源于此）。本 runner 配合测试文件里的
// 独立 provider id（e2e-mock-sfv），与并行车道完全解耦。
//
// 启动：node sfv_runner.mjs --port <空闲端口> --host 127.0.0.1
// 控制面与共享 runner 相同：GET /health、GET /__aimock/journal、POST /__aimock/reset/journal。
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

// --- 工具函数（与共享 runner.mjs 同口径） ------------------------------------

function userTexts(req) {
  return (req.messages || [])
    .filter((m) => m && m.role === "user")
    .map((m) => (typeof m.content === "string" ? m.content : ""))
    .filter((t) => t.length > 0);
}

function isTitleCall(req) {
  const texts = userTexts(req);
  if (texts.length === 0) return false;
  const last = texts[texts.length - 1].trimStart();
  return last.startsWith("用户消息：");
}

function fullUserText(req) {
  return userTexts(req).join("\n");
}

function makeScenarioPredicate(marker) {
  return (req) => !isTitleCall(req) && fullUserText(req).includes(marker);
}

// 每标记请求计数（跨 turn 持续；journal reset 不清计数）。
const counters = new Map();
function bump(key) {
  const next = (counters.get(key) || 0) + 1;
  counters.set(key, next);
  return next;
}

// --- 场景注册 ---------------------------------------------------------------

// (1) 断流：每次调用都在 3 chunk 后截断（必须配 tps，否则 Windows 上 RST 先于
//     在途字节到达，客户端一帧都收不到——共享 runner 实测结论）。产品自动重试
//     也不可能成功，用于断言断流可见性。
mock.addFixture({
  match: { predicate: makeScenarioPredicate("E2E-SFV-DROP-V1") },
  response: { content: "0123456789".repeat(30) },
  streamingProfile: { ttft: 50, tps: 8, jitter: 0 },
  truncateAfterChunks: 3,
});

// (2) 失败轮可重试：第 1 次主调用返回 400 真参数错误（bad_request fail-closed，
//     不命中网关瞬态 400 短语）；重试（第 2 次起）返回成功正文。
mock.addFixture({
  match: { predicate: makeScenarioPredicate("E2E-SFV-400-V1") },
  response: (req) => {
    const attempt = bump("E2E-SFV-400-V1");
    if (attempt === 1) {
      return {
        error: { message: "Invalid parameter: messages", type: "invalid_request_error" },
        status: 400,
      };
    }
    return { reasoning: "上次参数被网关拒绝，这次换合法请求成功。", content: "SFV 失败轮重试成功：这是重试后的回复。" };
  },
});

// (3) 收口恢复：断流/失败轮之后发一条普通消息，会话照常可用。
mock.addFixture({
  match: { predicate: makeScenarioPredicate("E2E-SFV-CLOSE-V1") },
  response: { content: "SFV 收口回复：断流后会话照常可用。" },
});

// (4) 兜底：未命中任何标记的调用（标题生成漏网、新调用面）——必须最后注册。
mock.addFixture({
  match: { userMessage: /.*/ },
  response: { content: "ok (sfv catch-all)" },
});

const url = await mock.start();
console.log(`SFV_MOCK_RUNNER_URL=${url}`);
setInterval(() => {}, 1 << 30);
