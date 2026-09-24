/**
 * 集成验证脚本（CDP，零第三方依赖）：真实浏览器里走主路径 ——
 * Ctrl+K 开全局命令面板 → Esc 关 → Ctrl+P 开会话搜索；收集 console 错误。
 *
 * 前提：生产 vite dev server 已在本脚本默认 APP_URL 运行。
 * 错误分类：/api 网络类（后端未启动时的 5xx/资源加载失败）为环境预期；
 * 其余 JS 异常/错误必须为 0。
 * 用法：node scripts/verify-cdp.mjs
 * 环境变量：VERIFY_APP_URL、VERIFY_CHROME、VERIFY_DEBUG_PORT。
 */
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const CHROME = process.env.VERIFY_CHROME ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
const APP_URL = process.env.VERIFY_APP_URL ?? "http://127.0.0.1:5193/";
const DEBUG_PORT = process.env.VERIFY_DEBUG_PORT ?? "9333";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitForDebugEndpoint() {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${DEBUG_PORT}/json/version`);
      if (response.ok) {
        return true;
      }
    } catch {
      // retry
    }
    await sleep(200);
  }
  return false;
}

async function createTarget() {
  // Chrome 111+ 要求 PUT /json/new
  const response = await fetch(`http://127.0.0.1:${DEBUG_PORT}/json/new?${encodeURIComponent(APP_URL)}`, {
    method: "PUT",
  });
  if (!response.ok) {
    throw new Error(`/json/new failed: ${response.status}`);
  }
  return response.json();
}

function connect(wsUrl) {
  const ws = new WebSocket(wsUrl);
  let nextId = 1;
  const pending = new Map();
  const eventListeners = [];
  ws.addEventListener("message", (message) => {
    const payload = JSON.parse(String(message.data));
    if (payload.id !== undefined && pending.has(payload.id)) {
      const { resolve, reject } = pending.get(payload.id);
      pending.delete(payload.id);
      if (payload.error) {
        reject(new Error(`${payload.error.message} (${payload.error.code})`));
      } else {
        resolve(payload.result);
      }
      return;
    }
    if (payload.method) {
      for (const listener of eventListeners) {
        listener(payload);
      }
    }
  });
  const opened = new Promise((resolve, reject) => {
    ws.addEventListener("open", resolve, { once: true });
    ws.addEventListener("error", () => reject(new Error("ws error")), { once: true });
  });
  return {
    opened,
    send(method, params = {}) {
      const id = nextId;
      nextId += 1;
      ws.send(JSON.stringify({ id, method, params }));
      return new Promise((resolve, reject) => {
        pending.set(id, { resolve, reject });
      });
    },
    onEvent(listener) {
      eventListeners.push(listener);
    },
    close() {
      ws.close();
    },
  };
}

function main() {
  const profileDir = mkdtempSync(join(tmpdir(), "gsp-verify-"));
  const chrome = spawn(
    CHROME,
    [
      "--headless=new",
      "--no-first-run",
      "--no-default-browser-check",
      "--disable-gpu",
      `--remote-debugging-port=${DEBUG_PORT}`,
      `--user-data-dir=${profileDir}`,
      "--window-size=1512,945",
      "about:blank",
    ],
    { stdio: "ignore" },
  );
  return { chrome, profileDir };
}

const results = { steps: [], consoleErrors: [], jsExceptions: [] };
let exitCode = 1;
const { chrome, profileDir } = main();

function record(step, ok, detail = "") {
  results.steps.push({ step, ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"} ${step}${detail ? ` — ${detail}` : ""}`);
}

function isExpectedNetworkError(text) {
  return (
    text.includes("/api/") ||
    text.includes("Failed to load resource") ||
    text.includes("ECONNREFUSED") ||
    text.includes("net::ERR") ||
    text.includes("socket")
  );
}

try {
  if (!(await waitForDebugEndpoint())) {
    throw new Error("Chrome debug endpoint did not come up");
  }
  const target = await createTarget();
  const cdp = connect(target.webSocketDebuggerUrl);
  await cdp.opened;

  cdp.onEvent((payload) => {
    if (payload.method === "Runtime.consoleAPICalled" && payload.params.type === "error") {
      const text = payload.params.args
        .map((arg) => arg.value ?? arg.description ?? "")
        .join(" ");
      results.consoleErrors.push(text);
    } else if (payload.method === "Runtime.exceptionThrown") {
      const detail = payload.params.exceptionDetails;
      results.jsExceptions.push(detail.exception?.description ?? detail.text ?? "exception");
    } else if (payload.method === "Log.entryAdded" && payload.params.entry.level === "error") {
      const text = `${payload.params.entry.source}: ${payload.params.entry.text}`;
      (isExpectedNetworkError(text) ? results.consoleErrors : results.jsExceptions).push(text);
    }
  });

  await cdp.send("Runtime.enable");
  await cdp.send("Log.enable");
  await cdp.send("Page.enable");

  const evaluate = async (expression) => {
    const result = await cdp.send("Runtime.evaluate", {
      expression,
      returnByValue: true,
      awaitPromise: true,
    });
    if (result.exceptionDetails) {
      throw new Error(`evaluate failed: ${result.exceptionDetails.text}`);
    }
    return result.result.value;
  };

  const waitFor = async (expression, timeoutMs, label) => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (await evaluate(expression)) {
        return true;
      }
      await sleep(250);
    }
    return false;
  };

  const pressCombo = async (key, code, keyCode, modifiers) => {
    await cdp.send("Input.dispatchKeyEvent", {
      type: "rawKeyDown",
      key,
      code,
      windowsVirtualKeyCode: keyCode,
      modifiers,
    });
    await cdp.send("Input.dispatchKeyEvent", {
      type: "keyUp",
      key,
      code,
      windowsVirtualKeyCode: keyCode,
      modifiers,
    });
  };

  // 等应用壳层挂载（路由就绪后主导航出现）。
  if (!(await waitFor(`Boolean(document.querySelector('[data-shell-group="navigation"]'))`, 45000, "shell"))) {
    throw new Error("workbench shell did not mount");
  }
  record("应用壳层挂载", true);
  // 等一拍，让启动期的网络请求尘埃落定，采集基线之后的增量。
  await sleep(3000);
  const baselineErrors = results.consoleErrors.length;
  const baselineExceptions = results.jsExceptions.length;
  console.log(`基线：网络类 console=${baselineErrors}，JS 异常=${baselineExceptions}`);

  // ---- 主路径 1：Ctrl+K 开面板 ----
  await pressCombo("k", "KeyK", 75, 2); // modifiers: Ctrl=2
  const paletteOpened = await waitFor(
    `Boolean(document.querySelector('[data-testid="vui-command-palette"]'))`,
    5000,
    "palette",
  );
  record("Ctrl+K 打开全局命令面板", paletteOpened);

  // ---- 主路径 2：Esc 关面板 ----
  await pressCombo("Escape", "Escape", 27, 0);
  const paletteClosed = await waitFor(
    `!document.querySelector('[data-testid="vui-command-palette"]')`,
    5000,
    "palette-close",
  );
  record("Esc 关闭命令面板", paletteClosed);

  // ---- 主路径 3：Ctrl+P 开会话搜索 ----
  await pressCombo("p", "KeyP", 80, 2);
  const searchOpened = await waitFor(
    `Boolean(document.querySelector('[data-testid="vui-session-search-dialog"]'))`,
    5000,
    "search",
  );
  record("Ctrl+P 打开会话搜索", searchOpened);
  // 给 server 查询与渲染留点时间。
  await sleep(2500);

  const newErrors = results.consoleErrors.slice(baselineErrors);
  const newExceptions = results.jsExceptions.slice(baselineExceptions);
  const unexpectedErrors = newErrors.filter((text) => !isExpectedNetworkError(text));
  record(
    "console 无新增 JS 异常/错误",
    unexpectedErrors.length === 0 && newExceptions.length === 0,
    `网络类（后端未启动，环境预期）=${newErrors.length - unexpectedErrors.length}，未预期=${unexpectedErrors.length}，JS 异常=${newExceptions.length}`,
  );
  if (unexpectedErrors.length > 0 || newExceptions.length > 0) {
    for (const text of [...unexpectedErrors, ...newExceptions]) {
      console.error(`[unexpected] ${text.slice(0, 300)}`);
    }
  }

  exitCode = results.steps.every((step) => step.ok) ? 0 : 1;
  cdp.close();
} catch (error) {
  console.error(`[verify] FAILED: ${String(error)}`);
  exitCode = 1;
} finally {
  chrome.kill();
  await sleep(1000);
  try {
    rmSync(profileDir, { recursive: true, force: true, maxRetries: 10, retryDelay: 500 });
  } catch (cleanupError) {
    console.warn(`[verify] profile cleanup skipped: ${String(cleanupError).slice(0, 120)}`);
  }
  console.log(JSON.stringify({ exitCode, steps: results.steps }, null, 2));
  process.exit(exitCode);
}
