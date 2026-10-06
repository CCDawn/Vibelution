import { fetchJson, isFetchJsonHttpError } from "./client";
import type { FinancialReportExportRequest, FinancialReportExportResponse } from "./types/financialReports";
import type { FinancialReportFilters, FinancialReportPage, FinancialReportsExportResponse } from "./types/financialReports";

export type { FinancialReportExportRequest, FinancialReportExportResponse, FinancialReportFormat } from "./types/financialReports";
export type { FinancialReportFilters, FinancialReportPage, FinancialReportSummary } from "./types/financialReports";

export function isFinancialReportNotFoundError(error: unknown): boolean {
  return isFetchJsonHttpError(error) && error.status === 404;
}

export const financialReportKeys = { catalog: (agentId: string, filters: FinancialReportFilters) => ["finance", "report-catalog", agentId, filters] as const };
export function fetchFinancialReports(agentId: string, filters: FinancialReportFilters = {}, options?: { signal?: AbortSignal }): Promise<FinancialReportPage> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value !== undefined && value !== "") params.set(key, String(value));
  return fetchJson(`/api/financial-reports/${encodeURIComponent(agentId)}?${params}`, { signal: options?.signal });
}

export async function downloadFinancialReportsExport(agentId: string, targets: Array<Pick<FinancialReportExportRequest, "sessionId" | "turnId">>, format: "markdown" | "json" | "docx") {
  if (!targets.length || targets.length > 20) throw new Error("一次最多导出20份报告");
  const result = await fetchJson<FinancialReportsExportResponse>(`/api/financial-reports/${encodeURIComponent(agentId)}/export-batch`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ targets, format }) });
  if (result.encoding !== "base64" || result.mediaType !== "application/zip" || result.count !== targets.length || typeof result.content !== "string" || result.content.length > 12_000_000 || result.fileName !== "stock-research-bundle.zip") throw new Error("批量导出响应无效");
  const binary = atob(result.content), bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], { type: "application/zip" }));
  const link = document.createElement("a"); link.href = url; link.download = result.fileName; link.hidden = true;
  document.body.append(link); link.click(); link.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

export type FinancialReportExportTarget = FinancialReportExportRequest & {
  assistantAgentId: string;
};

export const MAX_FINANCIAL_REPORT_EXPORT_CHARS = 2_000_000;

export function exportFinancialReport(target: FinancialReportExportTarget, options?: { signal?: AbortSignal }) {
  const { assistantAgentId, sessionId, turnId, format } = target;
  return fetchJson<FinancialReportExportResponse>(
    `/api/financial-reports/${encodeURIComponent(assistantAgentId)}/export`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionId, turnId, format }),
      signal: options?.signal,
    },
  );
}

function assertBoundedExport(response: FinancialReportExportResponse, expected: FinancialReportExportRequest) {
  if (
    !response
    || typeof response !== "object"
    || response.format !== expected.format
    || response.sessionId !== expected.sessionId
    || response.turnId !== expected.turnId
    || typeof response.content !== "string"
    || response.content.length > MAX_FINANCIAL_REPORT_EXPORT_CHARS
    || typeof response.fileName !== "string"
    || response.fileName.length > 120
    || /[\\/\u0000-\u001f]/.test(response.fileName)
    || typeof response.mediaType !== "string"
  ) {
    throw new Error("研究报告导出响应无效或超过大小限制");
  }
  if (expected.format === "docx") {
    if (response.encoding !== "base64" || !response.mediaType.startsWith("application/vnd.openxmlformats-officedocument.wordprocessingml.document")) {
      throw new Error("DOCX 导出响应格式无效");
    }
  } else if (response.encoding !== "utf8") {
    throw new Error("研究报告导出编码无效");
  }
  const acceptedMediaTypes: Record<FinancialReportExportRequest["format"], string> = {
    markdown: "text/markdown",
    json: "application/json",
    docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    pdf: "text/html",
  };
  if (!response.mediaType.toLowerCase().startsWith(acceptedMediaTypes[expected.format])) {
    throw new Error("研究报告导出媒体类型无效");
  }
}

function throwIfAborted(signal?: AbortSignal) {
  if (signal?.aborted) {
    const error = new Error("The operation was aborted");
    error.name = "AbortError";
    throw error;
  }
}

function exportBlob(response: FinancialReportExportResponse): Blob {
  if (response.encoding === "base64") {
    const binary = atob(response.content);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
    return new Blob([bytes], { type: response.mediaType });
  }
  return new Blob([response.content], { type: response.mediaType });
}

function safeFileName(response: FinancialReportExportResponse) {
  const fallback = `stock-research.${response.format === "markdown" ? "md" : response.format}`;
  return response.fileName.trim() || fallback;
}

function safePrintHtmlFileName(response: FinancialReportExportResponse) {
  const stem = safeFileName(response).replace(/\.[^.]*$/, "");
  return `${stem || "stock-research"}.html`;
}

export async function downloadFinancialReportPrintHtml(target: FinancialReportExportTarget, options?: { signal?: AbortSignal }) {
  if (target.format !== "pdf") throw new Error("仅打印版报告可以下载 HTML");
  const response = await exportFinancialReport(target, options);
  throwIfAborted(options?.signal);
  assertBoundedExport(response, target);
  if (response.format !== "pdf" || response.encoding !== "utf8" || !response.mediaType.toLowerCase().startsWith("text/html")) {
    throw new Error("打印版导出响应格式无效");
  }
  if (!response.content.trim()) throw new Error("打印版报告内容为空");

  const url = URL.createObjectURL(new Blob([response.content], { type: response.mediaType }));
  const link = document.createElement("a");
  link.href = url;
  link.download = safePrintHtmlFileName(response);
  link.rel = "noopener";
  link.hidden = true;
  try {
    document.body.append(link);
    link.click();
  } finally {
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
  }
}

function downloadStandalonePrintHtml(response: FinancialReportExportResponse, reason: "unsupported" | "timeout" | "load-error" | "afterprint-timeout"): Error {
  let message = "嵌入式打印不可用，已尝试下载单份报告 HTML；下载后可用浏览器打开并打印。";
  if (reason === "unsupported") {
    message = "当前窗口不支持嵌入式打印，已尝试下载单份报告 HTML；下载后可用浏览器打开并打印。";
  } else if (reason === "timeout") {
    message = "打印页加载超时，已尝试下载单份报告 HTML；下载后可用浏览器打开并打印。";
  } else if (reason === "afterprint-timeout") {
    message = "未收到打印完成确认，已尝试下载单份报告 HTML；请在浏览器打开该 HTML 后打印，本次没有生成 PDF。";
  }

  try {
    const url = URL.createObjectURL(new Blob([response.content], { type: "text/html;charset=utf-8" }));
    try {
      const link = document.createElement("a");
      link.href = url;
      link.download = safePrintHtmlFileName(response);
      link.rel = "noopener";
      link.hidden = true;
      try {
        document.body.append(link);
        link.click();
      } finally {
        link.remove();
      }
    } finally {
      window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
    }
  } catch {
    message = "此窗口无法打开打印页或下载报告，请用桌面浏览器打开报告中心后重试。";
  }
  return new Error(message);
}

export async function downloadFinancialReportExport(target: FinancialReportExportTarget, options?: { signal?: AbortSignal }) {
  if (target.format === "pdf") throw new Error("打印版报告必须通过浏览器打印打开");
  const response = await exportFinancialReport(target, options);
  throwIfAborted(options?.signal);
  assertBoundedExport(response, target);
  const url = URL.createObjectURL(exportBlob(response));
  const link = document.createElement("a");
  link.href = url;
  link.download = safeFileName(response);
  link.rel = "noopener";
  link.hidden = true;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

const PRINT_FRAME_LOAD_TIMEOUT_MS = 15_000;
const PRINT_AFTERPRINT_TIMEOUT_MS = 60_000;

export async function printFinancialReportExport(target: FinancialReportExportTarget, options?: { signal?: AbortSignal }): Promise<void> {
  if (target.format !== "pdf") throw new Error("仅打印版报告可以打开打印窗口");
  throwIfAborted(options?.signal);
  const response = await exportFinancialReport(target, options);
  throwIfAborted(options?.signal);
  assertBoundedExport(response, target);
  if (response.format !== "pdf" || response.encoding !== "utf8" || !response.mediaType.startsWith("text/html")) {
    throw new Error("打印版导出响应格式无效");
  }
  if (!response.content.trim()) throw new Error("打印版报告内容为空");
  if (typeof window === "undefined" || typeof document === "undefined" || !document.body) {
    throw new Error("当前环境无法打开打印文档");
  }
  const restoreFocusTarget = document.activeElement instanceof HTMLButtonElement
    ? document.activeElement
    : null;

  await new Promise<void>((resolve, reject) => {
    let frame: HTMLIFrameElement | null = null;
    let frameWindow: Window | null = null;
    let loadTimer: number | null = null;
    let afterPrintTimer: number | null = null;
    let settled = false;
    let printStarted = false;

    const cleanup = () => {
      if (loadTimer !== null) window.clearTimeout(loadTimer);
      if (afterPrintTimer !== null) window.clearTimeout(afterPrintTimer);
      options?.signal?.removeEventListener("abort", onAbort);
      window.removeEventListener("beforeunload", onBeforeUnload);
      frame?.removeEventListener("load", onLoad);
      frame?.removeEventListener("error", onLoadError);
      frameWindow?.removeEventListener("afterprint", onAfterPrint);
      frame?.remove();
    };
    const finish = (error?: Error, frameHadFocus = Boolean(frame && document.activeElement === frame)) => {
      if (settled) return;
      settled = true;
      const shouldRestoreFocus = frameHadFocus && Boolean(restoreFocusTarget?.isConnected);
      cleanup();
      if (shouldRestoreFocus) {
        window.requestAnimationFrame(() => {
          if (
            restoreFocusTarget?.isConnected
            && !restoreFocusTarget.disabled
            && document.activeElement === document.body
          ) {
            restoreFocusTarget.focus();
          }
        });
      }
      if (error) reject(error);
      else resolve();
    };
    const finishWithHtmlFallback = (reason: "unsupported" | "timeout" | "load-error" | "afterprint-timeout") => {
      const frameHadFocus = Boolean(frame && document.activeElement === frame);
      finish(downloadStandalonePrintHtml(response, reason), frameHadFocus);
    };
    const onAbort = () => {
      const error = new Error("The operation was aborted");
      error.name = "AbortError";
      finish(error);
    };
    const onBeforeUnload = () => finish(new Error("打印已取消：页面即将关闭"));
    const onAfterPrint = () => finish();
    const onLoadError = () => finishWithHtmlFallback("load-error");
    const onLoad = () => {
      if (!frame) return;
      try {
        const candidate = frame.contentWindow;
        if (
          !candidate
          || candidate.location.href !== "about:srcdoc"
          || candidate.document.URL !== "about:srcdoc"
          || candidate.document.readyState !== "complete"
          || candidate.document.documentElement?.tagName.toLowerCase() !== "html"
          || !candidate.document.body
        ) {
          // Ignore the initial about:blank and any document other than our srcdoc.
          return;
        }
        if (printStarted) return;
        printStarted = true;
        frameWindow = candidate;
        if (loadTimer !== null) window.clearTimeout(loadTimer);
        frameWindow.addEventListener("afterprint", onAfterPrint, { once: true });
        frameWindow.focus();
        afterPrintTimer = window.setTimeout(
          () => finishWithHtmlFallback("afterprint-timeout"),
          PRINT_AFTERPRINT_TIMEOUT_MS,
        );
        frameWindow.print();
      } catch (cause) {
        finish(cause instanceof Error ? cause : new Error("打印报告失败，请重试。"));
      }
    };

    try {
      options?.signal?.addEventListener("abort", onAbort, { once: true });
      window.addEventListener("beforeunload", onBeforeUnload, { once: true });
      frame = document.createElement("iframe");
      frame.setAttribute("sandbox", "allow-same-origin allow-modals");
      frame.title = response.fileName;
      frame.setAttribute("aria-hidden", "true");
      frame.style.cssText = "position:fixed;inset:0;width:100%;height:100%;border:0;background:white;z-index:-1";
      frame.addEventListener("load", onLoad);
      frame.addEventListener("error", onLoadError);
      loadTimer = window.setTimeout(
        () => finishWithHtmlFallback("timeout"),
        PRINT_FRAME_LOAD_TIMEOUT_MS,
      );
      if (!("srcdoc" in frame)) {
        finishWithHtmlFallback("unsupported");
        return;
      }
      frame.srcdoc = response.content;
      document.body.append(frame);
      if (options?.signal?.aborted) onAbort();
    } catch (cause) {
      finish(cause instanceof Error ? cause : new Error("无法创建打印文档，请重试。"));
    }
  });
}
