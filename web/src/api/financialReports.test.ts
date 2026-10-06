// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";
import { FetchJsonHttpError, resetControlTokenForTests, seedControlTokenForTests } from "./client";
import { downloadFinancialReportExport, exportFinancialReport, isFinancialReportNotFoundError, MAX_FINANCIAL_REPORT_EXPORT_CHARS, printFinancialReportExport } from "./financialReports";

let cleanupPrintMocks = () => {};
afterEach(() => {
  cleanupPrintMocks();
  cleanupPrintMocks = () => {};
  resetControlTokenForTests();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

const response = {
  sessionId: "session-1", turnId: "turn-1", format: "markdown" as const,
  fileName: "stock-research-2026-10-06.md", mediaType: "text/markdown; charset=utf-8",
  encoding: "utf8" as const, content: "## 结论\n研究结果",
};

function stubPrintIframe() {
  const url = "blob:http://localhost/stock-report";
  const originalCreate = Object.getOwnPropertyDescriptor(URL, "createObjectURL");
  const originalRevoke = Object.getOwnPropertyDescriptor(URL, "revokeObjectURL");
  const createObjectUrl = vi.fn(() => url);
  const revokeObjectUrl = vi.fn();
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: createObjectUrl });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: revokeObjectUrl });

  const print = vi.fn();
  const focus = vi.fn();
  const frameWindow = Object.assign(new EventTarget(), {
    location: { href: "about:blank" },
    document: { URL: "about:blank", readyState: "complete" },
    print,
    focus,
  });
  const createElement = document.createElement.bind(document);
  const append = document.body.append.bind(document.body);
  let frame: HTMLIFrameElement | null = null;
  const removeFrame = vi.fn();
  const appendFrame = vi.spyOn(document.body, "append").mockImplementation((...nodes) => {
    if (frame && nodes.some((node) => node === frame)) return;
    append(...nodes);
  });
  vi.spyOn(document, "createElement").mockImplementation(((tagName: string) => {
    const element = createElement(tagName);
    if (tagName.toLowerCase() === "iframe") {
      frame = element as HTMLIFrameElement;
      let src = "";
      Object.defineProperty(frame, "src", { configurable: true, get: () => src, set: (value: string) => { src = String(value); } });
      Object.defineProperty(frame, "contentWindow", { configurable: true, value: frameWindow });
      vi.spyOn(frame, "remove").mockImplementation(removeFrame);
    }
    return element;
  }) as typeof document.createElement);

  cleanupPrintMocks = () => {
    if (originalCreate) Object.defineProperty(URL, "createObjectURL", originalCreate);
    else Reflect.deleteProperty(URL, "createObjectURL");
    if (originalRevoke) Object.defineProperty(URL, "revokeObjectURL", originalRevoke);
    else Reflect.deleteProperty(URL, "revokeObjectURL");
  };
  return {
    url,
    frameWindow,
    print,
    focus,
    createObjectUrl,
    revokeObjectUrl,
    appendFrame,
    removeFrame,
    get frame() { return frame; },
    markLoaded() {
      frameWindow.location.href = url;
      frameWindow.document.URL = url;
    },
  };
}

async function waitForPrintFrame(frame: ReturnType<typeof stubPrintIframe>) {
  for (let attempt = 0; attempt < 20 && !frame.frame; attempt += 1) await Promise.resolve();
  expect(frame.frame).not.toBeNull();
  return frame.frame!;
}

describe("financial report export transport", () => {
  it("classifies only HTTP 404 responses as a missing financial report", () => {
    expect(isFinancialReportNotFoundError(new FetchJsonHttpError("report missing", { status: 404 }))).toBe(true);
    expect(isFinancialReportNotFoundError(new FetchJsonHttpError("forbidden", { status: 403 }))).toBe(false);
    expect(isFinancialReportNotFoundError(new Error("network disconnected"))).toBe(false);
  });

  it("posts an exact Agent/Session/Turn export request through the shared client", async () => {
    seedControlTokenForTests("test-token");
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(response), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(exportFinancialReport({ assistantAgentId: "agent/a", sessionId: "session-1", turnId: "turn-1", format: "markdown" })).resolves.toEqual(response);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/financial-reports/agent%2Fa/export");
    expect(init?.method).toBe("POST");
    expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
    expect(JSON.parse(String(init?.body))).toEqual({ sessionId: "session-1", turnId: "turn-1", format: "markdown" });
  });

  it("does not require a popup and prints only after the sandboxed report document loads", async () => {
    seedControlTokenForTests("test-token");
    const printResponse = {
      ...response, format: "pdf" as const, fileName: "stock-research-2026-10-06.html",
      mediaType: "text/html; charset=utf-8", content: "<!doctype html><html><body>research</body></html>",
    };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(printResponse), { status: 200 })));
    const printFrame = stubPrintIframe();
    const popup = vi.spyOn(window, "open").mockReturnValue(null);
    const operation = printFinancialReportExport({ assistantAgentId: "agent-1", sessionId: "session-1", turnId: "turn-1", format: "pdf" });
    const iframe = await waitForPrintFrame(printFrame);

    expect(iframe.getAttribute("sandbox")).toBe("allow-same-origin allow-modals");
    expect(iframe.getAttribute("sandbox")).not.toContain("allow-scripts");
    expect(iframe.src).toBe(printFrame.url);
    iframe.dispatchEvent(new Event("load"));
    expect(printFrame.print).not.toHaveBeenCalled();

    printFrame.markLoaded();
    iframe.dispatchEvent(new Event("load"));
    expect(printFrame.focus).toHaveBeenCalledOnce();
    expect(printFrame.print).toHaveBeenCalledOnce();
    expect(printFrame.appendFrame).toHaveBeenCalledWith(iframe);
    expect(document.body.contains(iframe)).toBe(false);
    const completed = expect(operation).resolves.toBeUndefined();
    printFrame.frameWindow.dispatchEvent(new Event("afterprint"));
    await completed;
    expect(printFrame.removeFrame).toHaveBeenCalledOnce();
    expect(printFrame.createObjectUrl).toHaveBeenCalledOnce();
    expect(printFrame.revokeObjectUrl).toHaveBeenCalledExactlyOnceWith(printFrame.url);
    expect(popup).not.toHaveBeenCalled();
  });

  it("keeps the response-processing size limit explicit", () => {
    expect(MAX_FINANCIAL_REPORT_EXPORT_CHARS).toBe(2_000_000);
  });

  it("rejects oversized response content before creating a download", async () => {
    seedControlTokenForTests("test-token");
    const oversized = { ...response, content: "x".repeat(MAX_FINANCIAL_REPORT_EXPORT_CHARS + 1) };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(oversized), { status: 200 })));
    await expect(downloadFinancialReportExport({ assistantAgentId: "agent-1", sessionId: "session-1", turnId: "turn-1", format: "markdown" })).rejects.toThrow("超过大小限制");
  });

  it("cleans up the iframe and blob URL when the frame reports a load error", async () => {
    seedControlTokenForTests("test-token");
    const printResponse = {
      ...response, format: "pdf" as const, fileName: "stock-research-2026-10-06.html",
      mediaType: "text/html; charset=utf-8", content: "<!doctype html><html><body>research</body></html>",
    };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(printResponse), { status: 200 })));
    const printFrame = stubPrintIframe();
    const operation = printFinancialReportExport({ assistantAgentId: "agent-1", sessionId: "session-1", turnId: "turn-1", format: "pdf" });
    const iframe = await waitForPrintFrame(printFrame);
    const rejected = expect(operation).rejects.toThrow("打印报告加载失败");
    iframe.dispatchEvent(new Event("error"));
    await rejected;
    expect(printFrame.removeFrame).toHaveBeenCalledOnce();
    expect(printFrame.revokeObjectUrl).toHaveBeenCalledExactlyOnceWith(printFrame.url);
  });

  it("cleans up the iframe and blob URL when the print is aborted", async () => {
    seedControlTokenForTests("test-token");
    const printResponse = {
      ...response, format: "pdf" as const, fileName: "stock-research-2026-10-06.html",
      mediaType: "text/html; charset=utf-8", content: "<!doctype html><html><body>research</body></html>",
    };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(printResponse), { status: 200 })));
    const printFrame = stubPrintIframe();
    const controller = new AbortController();
    const operation = printFinancialReportExport({ assistantAgentId: "agent-1", sessionId: "session-1", turnId: "turn-1", format: "pdf" }, { signal: controller.signal });
    const iframe = await waitForPrintFrame(printFrame);
    const rejected = expect(operation).rejects.toMatchObject({ name: "AbortError" });
    controller.abort();
    await rejected;
    expect(printFrame.removeFrame).toHaveBeenCalledOnce();
    expect(printFrame.revokeObjectUrl).toHaveBeenCalledExactlyOnceWith(printFrame.url);
  });

  it("cleans up the iframe and blob URL when the owning document unloads", async () => {
    seedControlTokenForTests("test-token");
    const printResponse = {
      ...response, format: "pdf" as const, fileName: "stock-research-2026-10-06.html",
      mediaType: "text/html; charset=utf-8", content: "<!doctype html><html><body>research</body></html>",
    };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(printResponse), { status: 200 })));
    const printFrame = stubPrintIframe();
    const operation = printFinancialReportExport({ assistantAgentId: "agent-1", sessionId: "session-1", turnId: "turn-1", format: "pdf" });
    const iframe = await waitForPrintFrame(printFrame);
    const rejected = expect(operation).rejects.toThrow("页面即将关闭");
    window.dispatchEvent(new Event("beforeunload"));
    await rejected;
    expect(printFrame.removeFrame).toHaveBeenCalledOnce();
    expect(printFrame.revokeObjectUrl).toHaveBeenCalledExactlyOnceWith(printFrame.url);
  });

  it("rejects a blank-only load after the load timeout and reclaims its URL", async () => {
    vi.useFakeTimers();
    seedControlTokenForTests("test-token");
    const printResponse = {
      ...response, format: "pdf" as const, fileName: "stock-research-2026-10-06.html",
      mediaType: "text/html; charset=utf-8", content: "<!doctype html><html><body>research</body></html>",
    };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(printResponse), { status: 200 })));
    const printFrame = stubPrintIframe();
    const operation = printFinancialReportExport({ assistantAgentId: "agent-1", sessionId: "session-1", turnId: "turn-1", format: "pdf" });
    const iframe = await waitForPrintFrame(printFrame);
    iframe.dispatchEvent(new Event("load"));
    expect(printFrame.print).not.toHaveBeenCalled();
    const rejected = expect(operation).rejects.toThrow("打印报告加载超时");
    await vi.advanceTimersByTimeAsync(15_000);
    await rejected;
    expect(printFrame.removeFrame).toHaveBeenCalledOnce();
    expect(printFrame.revokeObjectUrl).toHaveBeenCalledExactlyOnceWith(printFrame.url);
  });

  it("reclaims the iframe and URL if afterprint never arrives", async () => {
    vi.useFakeTimers();
    seedControlTokenForTests("test-token");
    const printResponse = {
      ...response, format: "pdf" as const, fileName: "stock-research-2026-10-06.html",
      mediaType: "text/html; charset=utf-8", content: "<!doctype html><html><body>research</body></html>",
    };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(printResponse), { status: 200 })));
    const printFrame = stubPrintIframe();
    const operation = printFinancialReportExport({ assistantAgentId: "agent-1", sessionId: "session-1", turnId: "turn-1", format: "pdf" });
    const iframe = await waitForPrintFrame(printFrame);
    printFrame.markLoaded();
    iframe.dispatchEvent(new Event("load"));
    expect(printFrame.print).toHaveBeenCalledOnce();
    const rejected = expect(operation).rejects.toThrow("打印等待超时");
    await vi.advanceTimersByTimeAsync(60_000);
    await rejected;
    expect(printFrame.removeFrame).toHaveBeenCalledOnce();
    expect(printFrame.revokeObjectUrl).toHaveBeenCalledExactlyOnceWith(printFrame.url);
  });
});
