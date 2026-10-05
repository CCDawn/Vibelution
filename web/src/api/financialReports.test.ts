// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";
import { resetControlTokenForTests, seedControlTokenForTests } from "./client";
import { downloadFinancialReportExport, exportFinancialReport, MAX_FINANCIAL_REPORT_EXPORT_CHARS, printFinancialReportExport } from "./financialReports";

afterEach(() => {
  resetControlTokenForTests();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const response = {
  sessionId: "session-1", turnId: "turn-1", format: "markdown" as const,
  fileName: "stock-research-2026-10-06.md", mediaType: "text/markdown; charset=utf-8",
  encoding: "utf8" as const, content: "## 结论\n研究结果",
};

describe("financial report export transport", () => {
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

  it("rejects blocked print popups before making an API request", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(window, "open").mockReturnValue(null);
    await expect(printFinancialReportExport({ assistantAgentId: "agent-1", sessionId: "session-1", turnId: "turn-1", format: "pdf" })).rejects.toThrow("阻止了打印窗口");
    expect(fetchMock).not.toHaveBeenCalled();
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

  it("loads print HTML in a sandboxed iframe without script permission", async () => {
    seedControlTokenForTests("test-token");
    const printResponse = {
      ...response, format: "pdf" as const, fileName: "stock-research-2026-10-06.html",
      mediaType: "text/html; charset=utf-8", content: "<!doctype html><html><body>research</body></html>",
    };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(printResponse), { status: 200 })));
    const printDocument = document.implementation.createHTMLDocument("print");
    const replaceChildren = printDocument.body.replaceChildren.bind(printDocument.body);
    let iframeSrcAtInsertion = "";
    vi.spyOn(printDocument.body, "replaceChildren").mockImplementation((...nodes: (Node | string)[]) => {
      const frame = nodes.find((node): node is HTMLIFrameElement => node instanceof HTMLIFrameElement);
      if (frame) iframeSrcAtInsertion = frame.getAttribute("src") ?? "";
      replaceChildren(...nodes);
    });
    const popup = {
      document: printDocument,
      opener: window,
      closed: false,
      setTimeout: window.setTimeout.bind(window),
      addEventListener: vi.fn(),
      close: vi.fn(),
    } as unknown as Window;
    vi.spyOn(window, "open").mockReturnValue(popup);
    const originalCreate = Object.getOwnPropertyDescriptor(URL, "createObjectURL");
    const originalRevoke = Object.getOwnPropertyDescriptor(URL, "revokeObjectURL");
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "about:blank") });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
    try {
      await printFinancialReportExport({ assistantAgentId: "agent-1", sessionId: "session-1", turnId: "turn-1", format: "pdf" });
      const frame = printDocument.querySelector("iframe");
      expect(frame?.getAttribute("sandbox")).toBe("allow-same-origin allow-modals");
      expect(frame?.getAttribute("sandbox")).not.toContain("allow-scripts");
      expect(frame?.getAttribute("src")).toContain("about:blank");
      expect(iframeSrcAtInsertion).toContain("about:blank");
    } finally {
      printDocument.body.replaceChildren();
      if (originalCreate) Object.defineProperty(URL, "createObjectURL", originalCreate);
      else Reflect.deleteProperty(URL, "createObjectURL");
      if (originalRevoke) Object.defineProperty(URL, "revokeObjectURL", originalRevoke);
      else Reflect.deleteProperty(URL, "revokeObjectURL");
    }
  });
});
