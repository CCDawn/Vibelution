/**
 * Local, dependency-free bilingual error document for the Workbench window.
 *
 * When the Workbench backend is not reachable, the window must never be
 * destroyed silently (the user saw a one-frame flash with no explanation).
 * Instead the shell loads this data: URL document into the same window so the
 * user sees what happened, the original cause, and what to do next — in
 * Chinese and English. A data: URL needs no protocol handler, no file on
 * disk, and no second design system; it is the smallest local document that
 * Electron's loadURL accepts.
 */

const ERROR_PAGE_MARKER = "<!--vibelution-workbench-error-page-->";

export const WORKBENCH_ERROR_DETAIL_MAX_CHARS = 300;

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

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
    "</style>",
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

export function workbenchErrorPageDataUrl(input: { origin: string; detail: string }): string {
  return `data:text/html;charset=utf-8,${encodeURIComponent(renderWorkbenchErrorPage(input))}`;
}

/**
 * Whether a window URL is one of our own error documents. The Workbench
 * window provider uses this to keep the error window out of the "ready"
 * state: sendToWorkbench, attention overlays, and focus tracking must stay
 * disabled while the error page is on screen, and the next open action must
 * reload the real workbench origin instead of trusting the error document.
 */
export function isWorkbenchErrorPageUrl(url: string): boolean {
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
    return decodeURIComponent(body).includes(ERROR_PAGE_MARKER);
  } catch {
    return body.includes(encodeURIComponent(ERROR_PAGE_MARKER));
  }
}
