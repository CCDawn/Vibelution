// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { previewFinancialPdf, stageFinancialPdf } from "../../api/financialEvidence";
import { reviewKnowledgeSourceInbox } from "../../api/knowledge";
import { FinanceEvidenceImport } from "./FinanceEvidenceImport";

vi.mock("../../api/financialEvidence", () => ({ previewFinancialPdf: vi.fn(), stageFinancialPdf: vi.fn() }));
vi.mock("../../api/knowledge", () => ({ reviewKnowledgeSourceInbox: vi.fn() }));
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const url = "https://static.cninfo.com.cn/finalpage/report.PDF";
const preview = { documentSha256: "a".repeat(64), sourceUrl: url, pageCount: 80, byteSize: 400, pages: [{ page: 5, excerpt: "真实PDF第5页原文", excerptSha256: "b".repeat(64) }], warnings: [], numericValidation: "not_performed" as const };

describe("financial PDF import and native review", () => {
  let root: Root, node: HTMLDivElement;
  beforeEach(async () => {
    vi.mocked(previewFinancialPdf).mockReset().mockResolvedValue(preview);
    vi.mocked(stageFinancialPdf).mockReset().mockResolvedValue({ status: "pending_review", source: { inboxSourceId: "source-1", title: "茅台2026H1 p.5", status: "pending" } });
    vi.mocked(reviewKnowledgeSourceInbox).mockReset().mockResolvedValue({});
    node = document.createElement("div"); document.body.append(node); root = createRoot(node);
    await act(async () => root.render(<MemoryRouter><QueryClientProvider client={new QueryClient()}><FinanceEvidenceImport agentId="finance" knowledgeBaseId="agent:finance:kb-financial-reports" stock={{ symbol: "sh600519", ticker: "600519", name: "贵州茅台", market: "上交所" }} sourceUrl={url} zh /></QueryClientProvider></MemoryRouter>));
    await click("导入财报");
  });
  afterEach(() => { act(() => root.unmount()); document.body.replaceChildren(); });
  function button(text: string) { return [...document.querySelectorAll<HTMLButtonElement>("button")].find(b => b.textContent === text)!; }
  async function click(text: string) { await act(async () => button(text).click()); }
  async function input(label: string, value: string) {
    const field = document.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`)!;
    await act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(field, value); field.dispatchEvent(new Event("input", { bubbles: true })); field.dispatchEvent(new Event("change", { bubbles: true })); });
  }
  async function ready() { await input("财报报告期", "2026H1"); await input("财报披露日期", "2026-08-15"); await click("读取原文预览"); }

  it("previews without staging and requires a separate reviewed ingestion", async () => {
    expect(button("提交本页审核").disabled).toBe(true);
    await ready();
    expect(document.body.textContent).toContain(preview.pages[0].excerpt);
    expect(stageFinancialPdf).not.toHaveBeenCalled();
    await click("提交本页审核");
    expect(stageFinancialPdf).toHaveBeenCalledWith("finance", expect.objectContaining({ company: "贵州茅台", ticker: "600519", page: 5, expectedDocumentSha256: preview.documentSha256 }));
    expect(reviewKnowledgeSourceInbox).not.toHaveBeenCalled();
    expect(button("确认原文并入库").disabled).toBe(true);
    await act(async () => document.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
    await click("确认原文并入库");
    expect(reviewKnowledgeSourceInbox).toHaveBeenCalledWith("agent", "finance", "source-1", expect.objectContaining({ decision: "accepted", reviewedByAgentId: "finance", knowledgeBaseId: "agent:finance:kb-financial-reports", knowledgeContent: preview.pages[0].excerpt }));
    expect(document.body.textContent).toContain("本页原文已审核入库");
  });

  it("invalidates an old preview when the original source changes", async () => {
    await ready();
    await input("财报官方PDF链接", "https://static.cninfo.com.cn/other.PDF");
    expect(button("提交本页审核").disabled).toBe(true);
    expect(document.body.textContent).not.toContain(preview.pages[0].excerpt);
    expect(stageFinancialPdf).not.toHaveBeenCalled();
  });

  it("shows source failures and never stages a missing original", async () => {
    vi.mocked(previewFinancialPdf).mockRejectedValueOnce(new Error("PDF没有可读取的文本页"));
    await ready();
    expect(document.body.textContent).toContain("PDF没有可读取的文本页");
    expect(button("提交本页审核").disabled).toBe(true);
    expect(reviewKnowledgeSourceInbox).not.toHaveBeenCalled();
  });

  it("does not review again when the same original page is already filed", async () => {
    vi.mocked(stageFinancialPdf).mockResolvedValueOnce({ status: "already_staged", source: { inboxSourceId: "source-1", title: "existing", status: "accepted", knowledgeItemId: "item-1" } });
    await ready(); await click("提交本页审核");
    expect(document.body.textContent).toContain("本页原文已审核入库");
    expect(reviewKnowledgeSourceInbox).not.toHaveBeenCalled();
  });
});
