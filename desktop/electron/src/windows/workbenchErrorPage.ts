/**
 * Local, dependency-free bilingual status documents for the Workbench window.
 *
 * When the Workbench backend is not reachable, the window must never be
 * destroyed silently (the user saw a one-frame flash with no explanation).
 * Instead the shell loads a data: URL document into the same window so the
 * user sees what happened, the original cause, and what to do next — in
 * Chinese and English. A data: URL needs no protocol handler, no file on
 * disk, and no second design system; it is the smallest local document that
 * Electron's loadURL accepts.
 *
 * Two variants share one visual style:
 *
 * - The WAITING variant is shown first. The shell keeps polling the backend
 *   in the background and reloads the real workbench origin automatically
 *   once it answers (see workbenchWaitingRecovery). A data: URL is skipped by
 *   the already-open-window watchdog, so without this variant a failed open
 *   never recovers on its own and the user has to reopen by hand.
 * - The ERROR variant is the terminal state: shown when the bounded wait ran
 *   out (or recovery itself failed) and carries the original cause.
 *
 * Both carry an HTML comment marker so the window provider can recognise
 * them from the window URL alone and keep them out of the "ready" state.
 */

const ERROR_PAGE_MARKER = "<!--vibelution-workbench-error-page-->";
const WAITING_PAGE_MARKER = "<!--vibelution-workbench-waiting-page-->";

export const WORKBENCH_ERROR_DETAIL_MAX_CHARS = 300;

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

const STATUS_PAGE_STYLE = [
  "<style>",
  "body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;",
  "background:#f7fafc;color:#1a202c;font-family:'Segoe UI','Microsoft YaHei',system-ui,sans-serif;}",
  ".card{max-width:640px;padding:40px 48px;background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;",
  "box-shadow:0 4px 16px rgba(0,0,0,0.06);}",
  "h1{font-size:20px;margin:0 0 12px;}",
  "p{font-size:14px;line-height:1.7;margin:6px 0;}",
  ".hint{color:#4a5568;}",
  "code{background:#edf2f7;border-radius:4px;padding:2px 6px;font-size:12px;word-break:break-all;}",
  "hr{border:none;border-top:1px solid #e2e8f0;margin:20px 0;}",
  ".en{color:#718096;}",
  ".elapsed{font-variant-numeric:tabular-nums;}",
  "</style>"
].join("\n");

export function renderWorkbenchErrorPage(input: {
  origin: string;
  detail: string;
}): string {
  const origin = escapeHtml(input.origin.trim() || "unknown origin");
  const detail = escapeHtml(input.detail.trim().slice(0, WORKBENCH_ERROR_DETAIL_MAX_CHARS) || "unknown error");
  return [
    "<!DOCTYPE html>",
    ERROR_PAGE_MARKER,
    '<html lang="zh-CN">',
    "<head>",
    '<meta charset="utf-8">',
    "<title>Vibelution</title>",
    STATUS_PAGE_STYLE,
    "</head>",
    "<body>",
    '<div class="card">',
    "<h1>工作台暂时无法连接</h1>",
    `<p>工作台后端（<code>${origin}</code>）未就绪或连接失败。</p>`,
    '<p class="hint">可以稍后从启动器再次点击「打开窗口」重试；如果后端未启动，请先从启动器启动项目。</p>',
    "<hr>",
    '<p class="en">The Workbench backend is not ready or could not be reached.</p>',
    `<p class="en">Try "Open Window" again from the Launcher in a moment. If the backend is not running, start the project from the Launcher first.</p>`,
    "<hr>",
    `<p class="hint">错误详情 / Detail: <code>${detail}</code></p>`,
    "</div>",
    "</body>",
    "</html>"
  ].join("\n");
}

/**
 * The waiting variant: bilingual "backend is starting, hold on" status with a
 * live elapsed-seconds counter. The counter is a tiny inline script (no
 * external assets, no user-controlled text reaches it) so the user can tell
 * the page is alive and the shell is still polling rather than frozen.
 */
export function renderWorkbenchWaitingPage(input: { origin: string }): string {
  const origin = escapeHtml(input.origin.trim() || "unknown origin");
  return [
    "<!DOCTYPE html>",
    WAITING_PAGE_MARKER,
    '<html lang="zh-CN">',
    "<head>",
    '<meta charset="utf-8">',
    "<title>Vibelution</title>",
    STATUS_PAGE_STYLE,
    "</head>",
    "<body>",
    '<div class="card">',
    "<h1>正在等待工作台后端启动…</h1>",
    `<p>工作台后端（<code>${origin}</code>）尚未就绪。桌面壳会持续检测，后端可用后将自动重新加载此窗口，无需手动操作。</p>`,
    '<p class="hint">已等待 <span class="elapsed" data-wait-seconds>0</span> 秒。如果等待时间过长，稍后会显示详细错误信息。</p>',
    "<hr>",
    '<p class="en">Waiting for the Workbench backend… The desktop shell keeps polling and reloads this window automatically once the backend is ready.</p>',
    '<p class="en">Waited <span class="elapsed" data-wait-seconds>0</span>s. If the wait runs too long, a detailed error will be shown instead.</p>',
    "</div>",
    "<script>",
    "(function(){",
    "var started=Date.now();",
    "var nodes=document.querySelectorAll('[data-wait-seconds]');",
    "function tick(){",
    "var s=Math.max(0,Math.floor((Date.now()-started)/1000));",
    "for(var i=0;i<nodes.length;i++){nodes[i].textContent=String(s);}",
    "}",
    "tick();",
    "setInterval(tick,1000);",
    "})();",
    "</script>",
    "</body>",
    "</html>"
  ].join("\n");
}

export function workbenchErrorPageDataUrl(input: { origin: string; detail: string }): string {
  return `data:text/html;charset=utf-8,${encodeURIComponent(renderWorkbenchErrorPage(input))}`;
}

export function workbenchWaitingPageDataUrl(input: { origin: string }): string {
  return `data:text/html;charset=utf-8,${encodeURIComponent(renderWorkbenchWaitingPage(input))}`;
}

/**
 * Whether a window URL is our own terminal error document. The Workbench
 * window provider uses this to keep the error window out of the "ready"
 * state: sendToWorkbench, attention overlays, and focus tracking must stay
 * disabled while the error page is on screen, and the next open action must
 * reload the real workbench origin instead of trusting the error document.
 */
export function isWorkbenchErrorPageUrl(url: string): boolean {
  return dataPageCarriesMarker(url, ERROR_PAGE_MARKER);
}

/**
 * Whether a window URL is our own waiting document. Same ready-state
 * exclusion as the error page; additionally tells the recovery loop that the
 * window still shows the page it is responsible for (a user retry or a
 * successful reload replaces it and must stop the loop).
 */
export function isWorkbenchWaitingPageUrl(url: string): boolean {
  return dataPageCarriesMarker(url, WAITING_PAGE_MARKER);
}

/** Either shell-owned status document (waiting or error): never a ready workbench. */
export function isWorkbenchStatusPageUrl(url: string): boolean {
  return isWorkbenchErrorPageUrl(url) || isWorkbenchWaitingPageUrl(url);
}

function dataPageCarriesMarker(url: string, marker: string): boolean {
  const candidate = url.trim();
  if (!candidate.toLowerCase().startsWith("data:text/html")) {
    return false;
  }
  const comma = candidate.indexOf(",");
  if (comma < 0) {
    return false;
  }
  const body = candidate.slice(comma + 1, comma + 1 + 800);
  try {
    return decodeURIComponent(body).includes(marker);
  } catch {
    return body.includes(encodeURIComponent(marker));
  }
}
