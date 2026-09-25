// 程序化剧本服务器：e2e mock-LLM 车道的产品级默认入口。
//
// 为什么需要程序化路由（实测结论，2026-09-25）：产品主聊天调用的末条 user 消息是
// "## Turn Status Bar" 遥测尾巴，composer 正文在更早的 user 消息里；而 aimock 的
// JSON fixture `userMessage` 只匹配**末条** user 消息文本。因此 JSON 剧本
// （fixtures/ 目录）对标题生成等辅助调用有效，主调用必须由本 runner 在**完整
// messages** 上做标记路由。
//
// 启动：node runner.mjs --port <空闲端口> --host 127.0.0.1
// 控制面与 CLI 相同：GET /health、GET /__aimock/journal、POST /__aimock/reset/journal。
import { createRequire } from "node:module";
import path from "node:path";

// aimock 从会话级安装缓存解析（本文件不在安装树内，走显式 require 路径）。
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

// --- 工具函数 ---------------------------------------------------------------

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

// 每标记请求计数（跨 turn 持续；不同用例用不同标记天然隔离）。
const counters = new Map();
function bump(key) {
  const next = (counters.get(key) || 0) + 1;
  counters.set(key, next);
  return next;
}

// --- 场景注册 ---------------------------------------------------------------
// 说明：fixture 级选项（streamingProfile / truncateAfterChunks / chaos）与响应
// 一起通过 addFixture 的完整 Fixture 对象声明。

// (1) normal_stream：reasoning + markdown 正文（喂渲染器），配轻 pacing 让前端
//     thinking 阶段可观测。
mock.addFixture({
  match: { predicate: makeScenarioPredicate("E2E-MOCK-MARKDOWN-V1") },
  response: {
    reasoning: "先判断用户意图：需要一份 markdown 结构样例。再组织标题、列表与代码块，确保渲染器能吃到标题、列表与代码块三种形态。",
    content: "## E2E 冒烟回复\n\n这是 **mock LLM** 的正文，用于喂渲染器：\n\n- 第一条要点\n- 第二条要点，含 `inline code`\n\n```python\nprint(\"hello from aimock\")\nprint(\"line two for pacing\")\nprint(\"line three for pacing\")\n```\n\n以上即全部内容，用于验证阶段推进与渲染。",
  },
  streamingProfile: { ttft: 300, tps: 8, jitter: 0 },
});

// (2) normal_stream 多轮：同标记连发，按请求次序区分轮次。
mock.addFixture({
  match: { predicate: makeScenarioPredicate("E2E-MOCK-MULTITURN-V1") },
  response: (req) => {
    const turn = bump("E2E-MOCK-MULTITURN-V1");
    if (turn === 1) {
      return { reasoning: "第一轮：做自我介绍。", content: "第一轮回复：我是 e2e-mock 提供的模拟模型。" };
    }
    return { reasoning: "第二轮：用户重复了同一句话，说明在验证上下文记忆。", content: "第二轮回复：我记得你上一轮问过同样的问题。" };
  },
});

// (3) incident_signatures：429 首发命中（带 Retry-After），重试成功。
mock.addFixture({
  match: { predicate: makeScenarioPredicate("E2E-MOCK-429-V1") },
  response: (req) => {
    const attempt = bump("E2E-MOCK-429-V1");
    if (attempt === 1) {
      return {
        error: { message: "Too many requests", type: "rate_limit_error", code: "rate_limit_exceeded" },
        status: 429,
        retryAfter: 1,
      };
    }
    return { reasoning: "上次被限流，这次重试成功。", content: "429 重试链路存活：这是重试后的成功回复。" };
  },
});

// (4) incident_signatures：400 网关抖动（首发 400，重试过）。当前产品对 400 的
//     分类不可重试时，该剧本只作演练/回放，不进产品级用例。
mock.addFixture({
  match: { predicate: makeScenarioPredicate("E2E-MOCK-400-V1") },
  response: (req) => {
    const attempt = bump("E2E-MOCK-400-V1");
    if (attempt === 1) {
      return { error: { message: "Invalid parameter: messages", type: "invalid_request_error" }, status: 400 };
    }
    return { content: "400 网关抖动重试后成功。" };
  },
});

// (5) incident_signatures：确定性畸形 JSON（chaos.malformedRate=1 每次命中必畸形）。
mock.addFixture({
  match: { predicate: makeScenarioPredicate("E2E-MOCK-MALFORMED-V1") },
  response: { content: "this text will never be seen" },
  chaos: { malformedRate: 1 },
});

// (6) incident_signatures：中途断流（必须配 tps pacing，否则 Windows 上 RST 先于
//     在途字节到达，客户端一个帧都收不到）。
mock.addFixture({
  match: { predicate: makeScenarioPredicate("E2E-MOCK-DROP-V1") },
  response: { content: "0123456789".repeat(30) },
  streamingProfile: { ttft: 50, tps: 8, jitter: 0 },
  truncateAfterChunks: 3,
});

// (7) incident_signatures：stall（大 ttft = 首帧前长时间停顿）。
mock.addFixture({
  match: { predicate: makeScenarioPredicate("E2E-MOCK-STALL-V1") },
  response: { reasoning: "迟迟不出的思考。", content: "stall 恢复后的最终回复。" },
  streamingProfile: { ttft: 8000, tps: 10, jitter: 0 },
});

// (8) incident_signatures：协议格式泄漏（前端渲染不炸）。
mock.addFixture({
  match: { predicate: makeScenarioPredicate("E2E-MOCK-LEAK-V1") },
  response: {
    reasoning: "<think>协议格式泄漏样例：思考字段里混入 think 标签与工具信封。",
    content: "<think>未闭合的思考标签泄漏</think>\n[TOOL_CALL: write_file {\"path\": \"x\"}]\n<summary>内部摘要信封泄漏</summary>\n正文仍然可读。",
  },
});

// (9) tool_calls：参数多分片（长 arguments 超过 20 字符分片阈值）。
mock.addFixture({
  match: { predicate: makeScenarioPredicate("E2E-MOCK-TOOL-V1") },
  response: {
    toolCalls: [
      {
        name: "write_file",
        arguments: JSON.stringify({
          path: "logs/e2e-mock.log",
          content: "X".repeat(200),
        }),
      },
    ],
  },
});

// (10) tool_calls：tool-first 交错（blocks：先工具后文本）。
mock.addFixture({
  match: { predicate: makeScenarioPredicate("E2E-MOCK-TOOLFIRST-V1") },
  response: {
    blocks: [
      { type: "toolCall", name: "search_web", arguments: JSON.stringify({ query: "e2e mock" }), id: "call_e2e_search_1" },
      { type: "text", text: "先调用工具，再补一句说明。" },
    ],
  },
});

// (11) timing：长思考（前端停在 thinking 且 elapsed 增长的可观测窗口）。
mock.addFixture({
  match: { predicate: makeScenarioPredicate("E2E-MOCK-LONGTHINK-V1") },
  response: {
    reasoning: "这是一段长思考：先拆解问题，再逐条推演，最后复核。模拟推理模型在前端停留在 thinking 阶段的可观测窗口。",
    content: "长思考结束后的正式回复。",
  },
  streamingProfile: { ttft: 3000, tps: 5, jitter: 0 },
});

// (12) timing：慢速流（低 tps 拉长 responding 窗口）。
mock.addFixture({
  match: { predicate: makeScenarioPredicate("E2E-MOCK-SLOW-V1") },
  response: {
    reasoning: "慢速流样例。",
    content: "0123456789".repeat(24),
  },
  streamingProfile: { ttft: 500, tps: 8, jitter: 0 },
});

// (13) 兜底：未命中任何标记的调用（标题生成的漏网、新调用面）——必须最后注册。
mock.addFixture({
  match: { userMessage: /.*/ },
  response: { content: "ok (e2e-mock catch-all)" },
});

const url = await mock.start();
console.log(`E2E_MOCK_RUNNER_URL=${url}`);
setInterval(() => {}, 1 << 30);
