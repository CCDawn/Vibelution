/**
 * 预览截图脚本 —— 无第三方依赖：直接驱动本机 Chrome headless 一次性截图。
 * 用法：先起 dev server（见 README），再 `node scripts/capture-screens.mjs`。
 * 环境变量：GSP_BASE_URL（默认 http://127.0.0.1:5196）、GSP_CHROME（默认 Chrome 安装路径）。
 */
import { spawnSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";

const outDir = fileURLToPath(new URL("../screenshots/", import.meta.url));
const baseUrl = process.env.GSP_BASE_URL ?? "http://127.0.0.1:5196";
const chromePath =
  process.env.GSP_CHROME ??
  "C:/Program Files/Google/Chrome/Application/chrome.exe";

const PREVIEW = `${baseUrl}/preview/global-shortcuts/index.html`;

/** [文件名, 查询参数, 说明] */
const SHOTS = [
  ["01-desktop-main.png", "", "桌面主视口（默认态）"],
  ["02-palette-open.png", "?state=palette", "Cmd+K 命令面板打开"],
  ["03-palette-empty.png", "?state=palette-empty", "命令面板空态（预置零命中查询）"],
  ["04-search-open.png", "?state=search", "Cmd+P 会话搜索（全部结果 + 加载更多）"],
  ["05-search-filtered.png", "?state=search-filtered", "会话搜索过滤命中 + 高亮"],
  ["06-search-empty.png", "?state=search-empty", "会话搜索空态"],
  ["07-conflict-banner.png", "?state=conflict", "占用冲突拒绝提示"],
  ["08-recording.png", "?state=recording", "录制新绑定态"],
  ["09-cleared-binding.png", "?state=cleared", "显式空数组清除绑定（未设置）"],
];

mkdirSync(outDir, { recursive: true });

const userDataDir = resolve(outDir, ".chrome-profile");

for (const [file, query, label] of SHOTS) {
  const args = [
    "--headless=new",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-gpu",
    "--hide-scrollbars",
    `--user-data-dir=${userDataDir}`,
    "--window-size=1512,945",
    "--virtual-time-budget=8000",
    `--screenshot=${resolve(outDir, file)}`,
    `${PREVIEW}${query}`,
  ];
  const result = spawnSync(chromePath, args, { stdio: "ignore", timeout: 60000 });
  if (result.status !== 0 && result.error === undefined) {
    console.error(`[capture] ${label} 退出码 ${result.status}`);
  } else {
    console.log(`[capture] ${file} — ${label}`);
  }
}
