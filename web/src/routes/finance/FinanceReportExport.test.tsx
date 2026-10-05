// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FinanceReportExport } from "./FinanceReportExport";
import { downloadFinancialReportExport, printFinancialReportExport } from "../../api/financialReports";

vi.mock("../../api/financialReports", () => ({
  downloadFinancialReportExport: vi.fn().mockResolvedValue(undefined),
  printFinancialReportExport: vi.fn().mockResolvedValue(undefined),
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let cleanup = async () => {};
let rerender = async (_props: Partial<React.ComponentProps<typeof FinanceReportExport>>) => {};
afterEach(async () => {
  await cleanup();
  rerender = async () => {};
  vi.clearAllMocks();
});

async function render(props: Partial<React.ComponentProps<typeof FinanceReportExport>> = {}) {
  const node = document.createElement("div");
  document.body.appendChild(node);
  const root = createRoot(node);
  cleanup = async () => { await act(async () => root.unmount()); node.remove(); };
  const merged = { assistantAgentId: "agent-1", sessionId: "session-1", turnId: "turn-1", zh: true, ...props };
  await act(async () => root.render(<FinanceReportExport {...merged} />));
  rerender = async (nextProps) => {
    await act(async () => root.render(<FinanceReportExport {...merged} {...nextProps} />));
  };
  return node;
}

async function openMenu(node: HTMLElement) {
  const trigger = node.querySelector("button");
  if (!trigger) throw new Error("Export button missing");
  await act(async () => {
    trigger.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, button: 0 }));
    trigger.dispatchEvent(new MouseEvent("pointerup", { bubbles: true, button: 0 }));
    trigger.click();
  });
}

describe("FinanceReportExport", () => {
  it("offers all four report formats from the shared VUI menu", async () => {
    const node = await render();
    await openMenu(node);
    const menu = document.querySelector('[role="menu"]');
    expect(menu?.textContent).toContain("Markdown (.md)");
    expect(menu?.textContent).toContain("JSON (.json)");
    expect(menu?.textContent).toContain("Word (.docx)");
    expect(menu?.textContent).toContain("打印 / PDF");
  });

  it("binds downloads and print to the exact Agent, Session, and Turn", async () => {
    const node = await render();
    await openMenu(node);
    const docx = Array.from(document.querySelectorAll('[role="menuitem"]')).find((item) => item.textContent?.includes("Word (.docx)"));
    await act(async () => { (docx as HTMLElement).click(); });
    expect(downloadFinancialReportExport).toHaveBeenCalledWith(
      { assistantAgentId: "agent-1", sessionId: "session-1", turnId: "turn-1", format: "docx" },
      { signal: expect.any(AbortSignal) },
    );

    await openMenu(node);
    const pdf = Array.from(document.querySelectorAll('[role="menuitem"]')).find((item) => item.textContent?.includes("打印 / PDF"));
    await act(async () => { (pdf as HTMLElement).click(); });
    expect(printFinancialReportExport).toHaveBeenCalledWith(
      { assistantAgentId: "agent-1", sessionId: "session-1", turnId: "turn-1", format: "pdf" },
      { signal: expect.any(AbortSignal) },
    );
  });

  it("shows export failures accessibly", async () => {
    vi.mocked(downloadFinancialReportExport).mockRejectedValueOnce(new Error("研究尚未成功完成，暂不能导出"));
    const node = await render();
    await openMenu(node);
    const markdown = Array.from(document.querySelectorAll('[role="menuitem"]')).find((item) => item.textContent?.includes("Markdown (.md)"));
    await act(async () => { (markdown as HTMLElement).click(); });
    expect(node.querySelector('[role="alert"]')?.textContent).toContain("研究尚未成功完成");
  });

  it("uses a synchronous gate for duplicate same-tick selections", async () => {
    let resolve: (() => void) | undefined;
    vi.mocked(downloadFinancialReportExport).mockImplementationOnce(() => new Promise<void>((done) => { resolve = done; }));
    const node = await render();
    await openMenu(node);
    const markdown = Array.from(document.querySelectorAll('[role="menuitem"]')).find((item) => item.textContent?.includes("Markdown (.md)")) as HTMLElement;
    await act(async () => {
      markdown.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, button: 0 }));
      markdown.dispatchEvent(new MouseEvent("pointerup", { bubbles: true, button: 0 }));
      markdown.click();
      markdown.click();
    });
    expect(downloadFinancialReportExport).toHaveBeenCalledTimes(1);
    await act(async () => resolve?.());
  });

  it("does not carry an old turn's delayed failure to a changed identity", async () => {
    let reject: ((reason?: unknown) => void) | undefined;
    vi.mocked(downloadFinancialReportExport).mockImplementationOnce(() => new Promise<void>((_resolve, fail) => { reject = fail; }));
    const node = await render();
    await openMenu(node);
    const markdown = Array.from(document.querySelectorAll('[role="menuitem"]')).find((item) => item.textContent?.includes("Markdown (.md)")) as HTMLElement;
    await act(async () => markdown.click());
    await rerender({ turnId: "turn-2" });
    await act(async () => reject?.(new Error("old turn failed")));
    expect(node.querySelector('[role="alert"]')).toBeNull();
  });
});
