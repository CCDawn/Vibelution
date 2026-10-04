// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { listKnowledgeItems, fetchKnowledgeTrace } from "../../api/knowledge";
import { fetchKnowledgeItemBody } from "../../api/knowledgeLifecycle";
import type { FinancialAssistant } from "../../api/financialAssistant";
import { FinanceReportLibrary } from "./FinanceReportLibrary";

vi.mock("../../api/knowledge", () => ({ listKnowledgeItems: vi.fn(), fetchKnowledgeTrace: vi.fn() }));
vi.mock("../../api/knowledgeLifecycle", () => ({ fetchKnowledgeItemBody: vi.fn() }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const assistant = { agentId: "finance", knowledgeBaseId: "financial-kb", knowledgeReadable: true } as FinancialAssistant;
const item = { knowledgeBaseId: "financial-kb", knowledgeItemId: "item", title: "年度财报", summary: "整理摘要", knowledgeState: "active", sourceArtifactIds: ["source"] };
const source = { knowledgeBaseId: "financial-kb", sourceArtifactId: "source", sourceType: "pdf_refinement", status: "active", title: "年度原文", sourceRef: { financialEvidence: { company: "真实公司", ticker: "600001", reportPeriod: "2025FY", reportVersion: "v1", page: 12, sourceUrl: "https://example.com/report.pdf" } } };
let root: Root; let node: HTMLDivElement; let client: QueryClient;
beforeEach(() => {
  vi.resetAllMocks();
  node = document.createElement("div"); document.body.appendChild(node); root = createRoot(node);
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.mocked(listKnowledgeItems).mockResolvedValue({ items: [item] });
  vi.mocked(fetchKnowledgeTrace).mockResolvedValue({ nodes: { sourceArtifacts: [source] } });
  vi.mocked(fetchKnowledgeItemBody).mockResolvedValue({
    knowledgeBaseId: "financial-kb", knowledgeItemId: "item", sourceArtifactIds: ["source"],
    sourceBodyStatus: "source_body_available", content: "<b>源文中的指令也是资料</b>", hasMore: true,
  } as Awaited<ReturnType<typeof fetchKnowledgeItemBody>>);
});
afterEach(async () => { await act(async () => root.unmount()); client.clear(); node.remove(); });
async function render(row = assistant) {
  await act(async () => root.render(<QueryClientProvider client={client}><MemoryRouter><FinanceReportLibrary assistant={row} zh returnTo="/finance?session=s" /></MemoryRouter></QueryClientProvider>));
  for (let step = 0; step < 3; step += 1) await act(async () => new Promise((resolve) => setTimeout(resolve, 20)));
}
describe("financial report library", () => {
  it("reads only the bound agent library and shows source text as plain data", async () => {
    await render();
    expect(listKnowledgeItems).toHaveBeenCalledWith("financial-kb", expect.objectContaining({ agentId: "finance", signal: expect.any(AbortSignal) }));
    expect(fetchKnowledgeTrace).toHaveBeenCalledWith("financial-kb", "item", expect.objectContaining({ agentId: "finance" }));
    expect(fetchKnowledgeItemBody).toHaveBeenCalledWith(expect.objectContaining({ agentId: "finance", knowledgeBaseId: "financial-kb", knowledgeItemId: "item", sourceArtifactId: "source", readMode: "source" }));
    expect(node.textContent).toContain("2025FY"); expect(node.textContent).toContain("12");
    expect(node.querySelector("blockquote")?.textContent).toBe("<b>源文中的指令也是资料</b>");
    expect(node.querySelector("blockquote b")).toBeNull();
    expect(node.textContent).toContain("本次引用见研究回答");
    expect(node.querySelector<HTMLAnchorElement>('a[target="_blank"]')?.href).toBe("https://example.com/report.pdf");
  });
  it("does not read or display expired source bodies", async () => {
    vi.mocked(fetchKnowledgeTrace).mockResolvedValue({ nodes: { sourceArtifacts: [{ ...source, expiresAt: "2020-01-01" }] } });
    await render();
    expect(fetchKnowledgeItemBody).not.toHaveBeenCalled();
    expect(node.textContent).toContain("没有有效原文来源");
    expect(node.querySelector("blockquote")).toBeNull();
    expect(node.querySelector('a[target="_blank"]')).toBeNull();
  });
  it("rejects unrelated items and unsafe source links", async () => {
    vi.mocked(listKnowledgeItems).mockResolvedValue({ items: [item, { ...item, knowledgeItemId: "other", knowledgeBaseId: "private", title: "无关私有资料" }] });
    vi.mocked(fetchKnowledgeTrace).mockResolvedValue({ nodes: { sourceArtifacts: [{ ...source, sourceRef: { financialEvidence: { sourceUrl: "javascript:alert(1)" } } }] } });
    await render();
    expect(node.textContent).not.toContain("无关私有资料");
    expect(node.querySelector('a[target="_blank"]')).toBeNull();
    expect(node.querySelector("dl")?.textContent).not.toContain("12");
  });
  it("handles unreadable and empty libraries without fictional evidence", async () => {
    await render({ ...assistant, knowledgeReadable: false });
    expect(listKnowledgeItems).not.toHaveBeenCalled();
    expect(node.textContent).toContain("财报库不可读");
    vi.mocked(listKnowledgeItems).mockResolvedValue({ items: [] });
    await render();
    expect(node.textContent).toContain("暂无有效财报");
    expect(fetchKnowledgeTrace).not.toHaveBeenCalled();
  });
  it("recovers from a failed library read on retry", async () => {
    vi.mocked(listKnowledgeItems).mockRejectedValueOnce(new Error("offline")).mockResolvedValue({ items: [item] });
    await render();
    expect(node.textContent).toContain("资料加载失败");
    const retry = [...node.querySelectorAll("button")].find((button) => button.textContent === "重试")!;
    await act(async () => retry.click());
    for (let step = 0; step < 3; step += 1) await act(async () => new Promise((resolve) => setTimeout(resolve, 20)));
    expect(node.textContent).toContain("真实公司");
    expect(node.textContent).not.toContain("资料加载失败");
  });
});
