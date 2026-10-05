import { fetchJson } from "./client";
import type { FinancialReportExportRequest, FinancialReportExportResponse } from "./types/financialReports";

export type { FinancialReportExportRequest, FinancialReportExportResponse, FinancialReportFormat } from "./types/financialReports";

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

export function printFinancialReportExport(target: FinancialReportExportTarget, options?: { signal?: AbortSignal }) {
  // Open synchronously in the menu click handler so popup protection does not
  // discard the print window after the asynchronous API response arrives.
  if (target.format !== "pdf") return Promise.reject(new Error("仅打印版报告可以打开打印窗口"));
  const printWindow = typeof window !== "undefined" ? window.open("about:blank", "_blank") : null;
  if (!printWindow) return Promise.reject(new Error("浏览器阻止了打印窗口，请允许弹窗后重试。"));
  printWindow.opener = null;
  return exportFinancialReport(target, options).then((response) => {
    throwIfAborted(options?.signal);
    assertBoundedExport(response, target);
    if (response.format !== "pdf" || response.encoding !== "utf8" || !response.mediaType.startsWith("text/html")) {
      throw new Error("打印版导出响应格式无效");
    }
    if (printWindow.closed) throw new Error("打印窗口已关闭，请重新导出");
    const url = URL.createObjectURL(new Blob([response.content], { type: "text/html;charset=utf-8" }));
    let released = false;
    const releaseUrl = () => {
      if (!released) {
        released = true;
        URL.revokeObjectURL(url);
      }
    };
    const frame = printWindow.document.createElement("iframe");
    frame.setAttribute("sandbox", "allow-same-origin allow-modals");
    frame.title = response.fileName;
    frame.style.cssText = "position:fixed;inset:0;width:100%;height:100%;border:0;background:white";
    frame.addEventListener("load", () => {
      const printDocument = frame.contentWindow;
      if (!printDocument) {
        releaseUrl();
        printWindow.close();
        return;
      }
      printDocument.addEventListener("afterprint", releaseUrl, { once: true });
      printDocument.focus();
      printDocument.print();
      printWindow.setTimeout(releaseUrl, 60_000);
    }, { once: true });
    frame.addEventListener("error", () => {
      releaseUrl();
      printWindow.close();
    }, { once: true });
    printWindow.addEventListener("beforeunload", releaseUrl, { once: true });
    printWindow.document.title = response.fileName.replace(/\.html$/i, "");
    frame.src = url;
    printWindow.document.body.replaceChildren(frame);
  }).catch((error: unknown) => {
    printWindow.close();
    throw error;
  });
}
