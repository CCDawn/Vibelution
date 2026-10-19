// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { listKnowledgeItems, fetchKnowledgeTrace } from "../../api/knowledge";
import { fetchKnowledgeItemBody } from "../../api/knowledgeLifecycle";
import type { FinancialAssistant } from "../../api/financialAssistant";
import type { StockIdentity } from "../../api/financialMarket";
import { FinanceReportLibrary } from "./FinanceReportLibrary";
import type { ReportCitation } from "./stockResearchModel";

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
async function render(row = assistant, citation: ReportCitation | null = null, currentStock?: StockIdentity) {
  await act(async () => root.render(<QueryClientProvider client={client}><MemoryRouter><FinanceReportLibrary assistant={row} citation={citation} currentStock={currentStock} zh returnTo="/finance?session=s" /></MemoryRouter></QueryClientProvider>));
  for (let step = 0; step < 3; step += 1) await act(async () => new Promise((resolve) => setTimeout(resolve, 20)));
}
async function settleScope() { for (let step = 0; step < 10; step += 1) await act(async () => new Promise((resolve) => setTimeout(resolve, 20))); }
async function expandExcerpt() {
  const toggle = node.querySelector<HTMLButtonElement>('button[aria-controls$="-excerpt"]');
  expect(toggle).not.toBeNull();
  if (toggle!.getAttribute("aria-expanded") === "false") await act(async () => toggle!.click());
  expect(toggle!.getAttribute("aria-expanded")).toBe("true");
  for (let step = 0; step < 3; step += 1) await act(async () => new Promise((resolve) => setTimeout(resolve, 20)));
}
describe("financial report library", () => {
  it("shows reviewed local items and original text returned for a scoped Agent library", async () => {
    const scopedId = "agent:finance:financial-kb";
    const ownership = { ownerType: "agent", ownerId: "finance", agentId: "finance" };
    vi.mocked(listKnowledgeItems).mockResolvedValue({ items: [
      { ...item, ...ownership },
      { ...item, ...ownership, knowledgeItemId: "foreign", ownerId: "another-agent", agentId: "another-agent", title: "其他Agent私有财报" },
    ] });
    vi.mocked(fetchKnowledgeTrace).mockResolvedValue({ nodes: { sourceArtifacts: [{ ...source, ...ownership }] } });
    vi.mocked(fetchKnowledgeItemBody).mockResolvedValue({
      knowledgeBaseId: scopedId, scopedKnowledgeBaseId: scopedId, knowledgeItemId: "item",
      sourceArtifactIds: ["source"], sourceBodyStatus: "source_body_available", content: "已审核PDF原文", hasMore: false,
    } as Awaited<ReturnType<typeof fetchKnowledgeItemBody>>);
    await render({ ...assistant, knowledgeBaseId: scopedId });
    await expandExcerpt();
    expect(node.textContent).toContain("年度财报");
    expect(node.textContent).not.toContain("暂无有效财报");
    expect(node.textContent).not.toContain("其他Agent私有财报");
    expect(fetchKnowledgeTrace).toHaveBeenCalledWith(scopedId, "item", expect.objectContaining({ agentId: "finance" }));
    expect(node.querySelector("blockquote")?.textContent).toBe("已审核PDF原文");
    expect(node.querySelector<HTMLAnchorElement>('a[target="_blank"]')?.href).toBe("https://example.com/report.pdf#page=12");
  });
  it("reads only the bound agent library and shows source text as plain data", async () => {
    await render();
    expect(listKnowledgeItems).toHaveBeenCalledWith("financial-kb", expect.objectContaining({ agentId: "finance", signal: expect.any(AbortSignal) }));
    expect(fetchKnowledgeTrace).toHaveBeenCalledWith("financial-kb", "item", expect.objectContaining({ agentId: "finance" }));
    expect(fetchKnowledgeItemBody).not.toHaveBeenCalled();
    const originalLink = node.querySelector<HTMLAnchorElement>('a[target="_blank"]');
    const excerpt = [...node.querySelectorAll<HTMLButtonElement>("button")].find(button => button.textContent === "阅读原文摘录");
    expect(originalLink).not.toBeNull();
    expect(excerpt).not.toBeNull();
    expect(Boolean(originalLink!.compareDocumentPosition(excerpt!) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true);
    expect(excerpt?.getAttribute("aria-expanded")).toBe("false");
    expect(node.querySelector("blockquote")).toBeNull();
    await expandExcerpt();
    expect(fetchKnowledgeItemBody).toHaveBeenCalledWith(expect.objectContaining({ agentId: "finance", knowledgeBaseId: "financial-kb", knowledgeItemId: "item", sourceArtifactId: "source", readMode: "source" }));
    expect(node.textContent).toContain("2025FY"); expect(node.textContent).toContain("12");
    expect(node.querySelector("blockquote")?.textContent).toBe("<b>源文中的指令也是资料</b>");
    expect(node.querySelector("blockquote b")).toBeNull();
    expect(node.textContent).not.toContain("当前引用");
    expect(node.querySelector<HTMLAnchorElement>('a[target="_blank"]')?.href).toBe("https://example.com/report.pdf#page=12");
  });
  it("puts the excerpt before collapsed metadata and formats the publication date", async () => {
    vi.mocked(fetchKnowledgeTrace).mockResolvedValue({ nodes: { sourceArtifacts: [{ ...source, sourceRef: { financialEvidence: { ...source.sourceRef.financialEvidence, publishedAt: "2026-04-03T00:00:00Z" } } }] } });
    await render();
    const metadataToggle = [...node.querySelectorAll<HTMLButtonElement>("button")].find(button => button.textContent === "资料属性与来源")!;
    expect(metadataToggle.getAttribute("aria-expanded")).toBe("false");
    expect(node.querySelector("dl")).toBeNull();
    expect(fetchKnowledgeItemBody).not.toHaveBeenCalled();
    await expandExcerpt();
    expect(Boolean(node.querySelector("blockquote")!.compareDocumentPosition(metadataToggle) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true);
    await act(async () => metadataToggle.click());
    expect(metadataToggle.getAttribute("aria-expanded")).toBe("true");
    expect(node.querySelector("dl")?.textContent).toContain("2026年4月3日");
    expect(node.querySelector("dl")?.textContent).toContain("真实公司");
    expect(node.querySelector("dl")?.textContent).not.toContain("T00:00");
  });
  it("renders alternate source citations as compact icon, title, and page rows", async () => {
    const page63 = {
      ...source,
      sourceArtifactId: "page63",
      title: "现金流量表原始披露",
      sourceRef: { financialEvidence: { ...source.sourceRef.financialEvidence, page: 63 } },
    };
    vi.mocked(listKnowledgeItems).mockResolvedValue({ items: [{ ...item, sourceArtifactIds: ["source", "page63"] }] });
    vi.mocked(fetchKnowledgeTrace).mockResolvedValue({ nodes: { sourceArtifacts: [source, page63] } });
    await render();
    const row = [...node.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent?.includes("现金流量表原始披露"));

    expect(row?.className).toContain("!min-h-8");
    expect(row?.querySelector("svg")).not.toBeNull();
    expect(row?.querySelector("strong")?.title).toBe("现金流量表原始披露");
    expect(row?.textContent).toContain("第63页");
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
    expect(node.querySelector("dl")).toBeNull();
    await act(async () => node.querySelector<HTMLButtonElement>('button[aria-controls$="-metadata"]')!.click());
    expect(node.querySelector("dl")!.textContent).not.toContain("12");
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
    await act(async () => [...node.querySelectorAll<HTMLButtonElement>("button")].find(button => button.textContent === "资料属性与来源")!.click());
    expect(node.textContent).toContain("真实公司");
    expect(node.textContent).not.toContain("资料加载失败");
  });

  it("selects the owned source matching the cited PDF URL and page", async () => {
    const targetItem = { ...item, knowledgeItemId: "cashflow", title: "现金流原文", sourceArtifactIds: ["page42", "page63"] };
    const page42Source = {
      ...source,
      sourceArtifactId: "page42",
      title: "经营现金流补充披露",
      sourceRef: { financialEvidence: { ...source.sourceRef.financialEvidence, page: 42 } },
    };
    const targetSource = { ...source, sourceArtifactId: "page63", sourceRef: { financialEvidence: { ...source.sourceRef.financialEvidence, page: 63 } } };
    vi.mocked(listKnowledgeItems).mockResolvedValue({ items: [item, targetItem] });
    vi.mocked(fetchKnowledgeTrace).mockImplementation(async (_kb, id) => ({ nodes: { sourceArtifacts: id === "cashflow" ? [page42Source, targetSource] : [source] } }));
    vi.mocked(fetchKnowledgeItemBody).mockImplementation(async (request) => ({
      knowledgeBaseId: "financial-kb", knowledgeItemId: request.knowledgeItemId, sourceArtifactIds: [request.sourceArtifactId!],
      sourceBodyStatus: "source_body_available", content: request.sourceArtifactId === "page63" ? "第63页经营现金流" : request.sourceArtifactId === "page42" ? "第42页补充披露" : "第12页原文", hasMore: false,
    } as Awaited<ReturnType<typeof fetchKnowledgeItemBody>>));
    await render(assistant, { url: "https://example.com/report.pdf", page: "63", label: "PDF · 第 63 页" });
    await expandExcerpt();
    expect(node.querySelector("blockquote")?.textContent).toBe("第63页经营现金流");
    expect([...node.querySelectorAll<HTMLAnchorElement>('a[target="_blank"]')].map((link) => link.href)).toEqual(["https://example.com/report.pdf#page=63", "https://example.com/report.pdf#page=63"]);
    expect(node.textContent).not.toContain("当前库未找到对应页原文");
    expect(fetchKnowledgeItemBody).toHaveBeenCalledWith(expect.objectContaining({ agentId: "finance", knowledgeItemId: "cashflow", sourceArtifactId: "page63", readMode: "source" }));

    const alternateSource = [...node.querySelectorAll<HTMLButtonElement>("button")]
      .find((button) => button.textContent?.includes("经营现金流补充披露"));
    await act(async () => alternateSource?.click());
    for (let step = 0; step < 3; step += 1) await act(async () => new Promise((resolve) => setTimeout(resolve, 20)));
    await expandExcerpt();
    expect(node.querySelector("blockquote")?.textContent).toBe("第42页补充披露");
    expect(fetchKnowledgeItemBody).toHaveBeenCalledWith(expect.objectContaining({ agentId: "finance", knowledgeItemId: "cashflow", sourceArtifactId: "page42", readMode: "source" }));
    expect([...node.querySelectorAll<HTMLAnchorElement>('a[target="_blank"]')].map((link) => link.href)).toEqual(["https://example.com/report.pdf#page=63", "https://example.com/report.pdf#page=42"]);
  });

  it("continues citation lookup in bounded batches beyond the first 20 library items", async () => {
    const lateItems = Array.from({ length: 24 }, (_, index) => ({
      ...item,
      knowledgeItemId: `item-${index + 1}`,
      title: `财报${index + 1}`,
      sourceArtifactIds: [`source-${index + 1}`],
    }));
    const lateSource = {
      ...source,
      sourceArtifactId: "source-24",
      sourceRef: { financialEvidence: { ...source.sourceRef.financialEvidence, page: 24, sourceUrl: "https://example.com/archive.pdf" } },
    };
    vi.mocked(listKnowledgeItems).mockResolvedValue({ items: lateItems });
    vi.mocked(fetchKnowledgeTrace).mockImplementation(async (_knowledgeBaseId, id) => ({
      nodes: { sourceArtifacts: id === "item-24" ? [lateSource] : [] },
    }));
    vi.mocked(fetchKnowledgeItemBody).mockImplementation(async (request) => ({
      knowledgeBaseId: request.knowledgeBaseId,
      knowledgeItemId: request.knowledgeItemId,
      sourceArtifactIds: [request.sourceArtifactId!],
      sourceBodyStatus: "source_body_available",
      content: "第24条资料摘录",
      hasMore: false,
    } as Awaited<ReturnType<typeof fetchKnowledgeItemBody>>));

    await render(assistant, { url: "https://example.com/archive.pdf", page: "24", label: "PDF · 第 24 页" });
    await expandExcerpt();
    for (let step = 0; step < 8; step += 1) await act(async () => new Promise((resolve) => setTimeout(resolve, 20)));

    expect(fetchKnowledgeTrace).toHaveBeenCalledTimes(24);
    expect(fetchKnowledgeTrace).toHaveBeenCalledWith("financial-kb", "item-24", expect.objectContaining({ agentId: "finance" }));
    expect(node.querySelector("blockquote")?.textContent).toBe("第24条资料摘录");
    expect(node.textContent).not.toContain("当前库未找到对应页原文");
  });

  it("skips a failed source, finds a later citation, and retries the failed source on refresh", async () => {
    const items = Array.from({ length: 24 }, (_, index) => ({ ...item, knowledgeItemId: `item-${index + 1}`, sourceArtifactIds: [`source-${index + 1}`] }));
    const lateSource = { ...source, sourceArtifactId: "source-24", sourceRef: { financialEvidence: { ...source.sourceRef.financialEvidence, page: 24, sourceUrl: "https://example.com/archive.pdf" } } };
    let unavailable = true;
    let failedReads = 0;
    vi.mocked(listKnowledgeItems).mockResolvedValue({ items });
    vi.mocked(fetchKnowledgeTrace).mockImplementation(async (_baseId, id) => {
      if (id === "item-20") {
        failedReads += 1;
        if (unavailable) throw new Error("temporary source failure");
      }
      return { nodes: { sourceArtifacts: id === "item-24" ? [lateSource] : [] } };
    });
    vi.mocked(fetchKnowledgeItemBody).mockImplementation(async (request) => ({
      knowledgeBaseId: request.knowledgeBaseId,
      knowledgeItemId: request.knowledgeItemId,
      sourceArtifactIds: [request.sourceArtifactId!],
      sourceBodyStatus: "source_body_available",
      content: "第24条资料摘录",
      hasMore: false,
    } as Awaited<ReturnType<typeof fetchKnowledgeItemBody>>));
    await render(assistant, { url: "https://example.com/archive.pdf", page: "24", label: "PDF · 第 24 页" });
    await expandExcerpt();
    for (let step = 0; step < 8; step += 1) await act(async () => new Promise((resolve) => setTimeout(resolve, 20)));

    expect(fetchKnowledgeTrace).toHaveBeenCalledTimes(24);
    expect(failedReads).toBe(1);
    expect(node.querySelector("blockquote")?.textContent).toBe("第24条资料摘录");
    expect(node.textContent).not.toContain("部分资料来源读取失败");
    expect(node.textContent).not.toContain("当前库未找到对应页原文");
    unavailable = false;
    await act(async () => node.querySelector<HTMLButtonElement>('[aria-label="刷新财报资料"]')!.click());
    for (let step = 0; step < 8; step += 1) await act(async () => new Promise((resolve) => setTimeout(resolve, 20)));
    expect(failedReads).toBe(2);
    expect(node.textContent).not.toContain("部分资料来源读取失败");
    await expandExcerpt();
    expect(node.querySelector("blockquote")?.textContent).toBe("第24条资料摘录");
  });

  it("does not label an unrelated or expired source as the selected citation", async () => {
    vi.mocked(fetchKnowledgeTrace).mockResolvedValue({ nodes: { sourceArtifacts: [{ ...source, expiresAt: "2020-01-01" }] } });
    await render(assistant, { url: "https://example.com/report.pdf", page: "12", label: "PDF · 第 12 页" });
    expect(node.textContent).toContain("当前库未找到对应页原文");
    expect(fetchKnowledgeItemBody).not.toHaveBeenCalled();
    expect(node.querySelector("blockquote")).toBeNull();
  });

  it("defaults to exact current-stock sources and labels cross-company rows in all-materials mode", async () => {
    const foreignItem = { ...item, knowledgeItemId: "foreign-company", title: "其他公司财报", sourceArtifactIds: ["foreign-source"] };
    const foreignSource = { ...source, sourceArtifactId: "foreign-source", sourceRef: { financialEvidence: { ...source.sourceRef.financialEvidence, company: "另一家公司", ticker: "600002" } } };
    vi.mocked(listKnowledgeItems).mockResolvedValue({ items: [item, foreignItem] });
    vi.mocked(fetchKnowledgeTrace).mockImplementation(async (_kb, id) => ({ nodes: { sourceArtifacts: id === "foreign-company" ? [foreignSource] : [source] } }));
    await render(assistant, null, { symbol: "sh600001", ticker: "600001", name: "真实公司", market: "上交所" });
    await settleScope();

    expect(node.textContent).toContain("年度财报");
    expect(node.textContent).not.toContain("其他公司财报");
    expect(node.querySelector("blockquote")).toBeNull();
    expect(fetchKnowledgeItemBody).not.toHaveBeenCalled();

    await act(async () => node.querySelector<HTMLButtonElement>('[aria-label="资料范围"]')?.click());
    await act(async () => [...document.querySelectorAll<HTMLElement>('[data-slot="select-item"]')].find((option) => option.textContent?.includes("全部资料"))?.click());
    for (let step = 0; step < 4; step += 1) await act(async () => new Promise((resolve) => setTimeout(resolve, 20)));
    expect(node.textContent).toContain("全部资料仅供查阅");
    expect(node.textContent).toContain("其他公司财报");
    expect(node.textContent).toContain("另一家公司 · 600002");
  });

  it("shows an explicit current-stock empty state instead of falling back to another company", async () => {
    vi.mocked(fetchKnowledgeTrace).mockResolvedValue({ nodes: { sourceArtifacts: [{ ...source, sourceRef: { financialEvidence: { company: "其他公司", ticker: "600002" } } }] } });
    await render(assistant, null, { symbol: "sh000003", ticker: "000003", name: "未入库公司", market: "上交所" });
    await settleScope();
    expect(node.textContent).toContain("暂无 未入库公司（000003）的匹配资料");
    expect(node.textContent).not.toContain("年度财报");
    expect(node.querySelector('section[aria-label="资料来源"]')).toBeNull();
    expect(fetchKnowledgeItemBody).not.toHaveBeenCalled();
  });

  it("matches the verified ticker when original filings use a legal company name", async () => {
    vi.mocked(listKnowledgeItems).mockResolvedValue({ items: [{ ...item, summary: "Financial PDF excerpt awaiting source review." }] });
    vi.mocked(fetchKnowledgeTrace).mockResolvedValue({ nodes: { sourceArtifacts: [{ ...source, sourceRef: { financialEvidence: { ...source.sourceRef.financialEvidence, company: "贵州茅台酒股份有限公司", ticker: "600519" } } }] } });
    await render(assistant, null, { symbol: "sh600519", ticker: "600519", name: "贵州茅台", market: "上交所" });
    await settleScope();
    expect(node.textContent).toContain("年度财报");
    expect(node.textContent).not.toContain("awaiting source review");
    await act(async () => node.querySelector<HTMLButtonElement>('button[aria-controls$="-metadata"]')!.click());
    expect(node.textContent).toContain("贵州茅台酒股份有限公司");
  });

  it("excludes unverified current-stock items and retries a failed scope trace on refresh", async () => {
    let failed = true;
    vi.mocked(fetchKnowledgeTrace).mockImplementation(async () => {
      if (failed) throw new Error("temporary source trace failure");
      return { nodes: { sourceArtifacts: [source] } };
    });
    await render(assistant, null, { symbol: "sh600001", ticker: "600001", name: "真实公司", market: "上交所" });
    await settleScope();
    expect(node.textContent).toContain("当前股票范围可能不完整");
    expect(node.textContent).not.toContain("年度财报");
    failed = false;
    await act(async () => node.querySelector<HTMLButtonElement>('[aria-label="刷新财报资料"]')?.click());
    for (let step = 0; step < 10; step += 1) await act(async () => new Promise((resolve) => setTimeout(resolve, 20)));
    expect(node.textContent).toContain("年度财报");
    expect(node.textContent).not.toContain("当前股票范围可能不完整");
  });

  it("keeps an unmatched external quote focused instead of showing the default Maotai report", async () => {
    const maotaiItem = {
      ...item,
      knowledgeItemId: "maotai-report",
      title: "贵州茅台年度报告",
      summary: "茅台第5页营业收入与净利润",
      sourceArtifactIds: ["maotai-page-5"],
    };
    const maotaiSource = {
      ...source,
      sourceArtifactId: "maotai-page-5",
      title: "茅台第5页",
      sourceRef: { financialEvidence: {
        company: "贵州茅台", ticker: "600519", reportPeriod: "2024FY", reportVersion: "v1", page: 5,
        sourceUrl: "https://example.com/maotai-2024.pdf",
      } },
    };
    vi.mocked(listKnowledgeItems).mockResolvedValue({ items: [maotaiItem] });
    vi.mocked(fetchKnowledgeTrace).mockResolvedValue({ nodes: { sourceArtifacts: [maotaiSource] } });
    vi.mocked(fetchKnowledgeItemBody).mockResolvedValue({
      knowledgeBaseId: "financial-kb", knowledgeItemId: "maotai-report", sourceArtifactIds: ["maotai-page-5"],
      sourceBodyStatus: "source_body_available", content: "茅台第5页财报指标", hasMore: false,
    } as Awaited<ReturnType<typeof fetchKnowledgeItemBody>>);

    await render(assistant, { url: "https://gu.qq.com/sz000001/gp", page: "", label: "平安银行 · 000001" });

    const quoteLink = [...node.querySelectorAll<HTMLAnchorElement>('a[target="_blank"]')]
      .find((link) => link.textContent?.includes("打开原文"));
    expect(quoteLink?.href).toBe("https://gu.qq.com/sz000001/gp");
    expect(node.textContent).toContain("当前库未找到对应页原文");
    expect(node.textContent).toContain("贵州茅台年度报告");
    expect(node.querySelector('section[aria-label="资料来源"]')).toBeNull();
    expect(node.querySelector("dl")).toBeNull();
    expect(node.querySelector("blockquote")).toBeNull();
    expect(fetchKnowledgeItemBody).not.toHaveBeenCalled();

    const reportRow = [...node.querySelectorAll<HTMLButtonElement>("button")]
      .find((button) => button.textContent?.includes("贵州茅台年度报告"));
    await act(async () => reportRow?.click());
    for (let step = 0; step < 3; step += 1) await act(async () => new Promise((resolve) => setTimeout(resolve, 20)));
    await expandExcerpt();
    expect(node.querySelector("blockquote")?.textContent).toBe("茅台第5页财报指标");

    await render(assistant, { url: "https://gu.qq.com/sz000001/gp", page: "", label: "平安银行 · 000001" });
    expect(node.querySelector('a[target="_blank"]')?.href).toBe("https://gu.qq.com/sz000001/gp");
    expect(node.querySelector('section[aria-label="资料来源"]')).toBeNull();
    expect(node.querySelector("blockquote")).toBeNull();
  });

  it("keeps default report details hidden while citation lookup is pending", async () => {
    vi.mocked(fetchKnowledgeTrace).mockImplementation(() => new Promise(() => {}));
    await render(assistant, { url: "https://gu.qq.com/sz000001/gp", page: "", label: "平安银行 · 000001" });
    expect(node.textContent).toContain("平安银行 · 000001");
    expect(node.querySelector('section[aria-label="资料来源"]')).toBeNull();
    expect(node.querySelector("blockquote")).toBeNull();
    expect(node.textContent).not.toContain("茅台第5页财报指标");
  });

  it("reports partial source-read uncertainty only after an unmatched citation scan completes", async () => {
    const items = Array.from({ length: 21 }, (_, index) => ({ ...item, knowledgeItemId: `item-${index + 1}`, sourceArtifactIds: [`source-${index + 1}`] }));
    vi.mocked(listKnowledgeItems).mockResolvedValue({ items });
    vi.mocked(fetchKnowledgeTrace).mockImplementation(async (_baseId, id) => {
      if (id === "item-20") throw new Error("temporary source failure");
      return { nodes: { sourceArtifacts: [] } };
    });

    await render(assistant, { url: "https://example.com/unmatched.pdf", page: "1", label: "未入库报告 · 第1页" });
    for (let step = 0; step < 6; step += 1) await act(async () => new Promise((resolve) => setTimeout(resolve, 20)));

    expect(fetchKnowledgeTrace).toHaveBeenCalledTimes(21);
    expect(node.textContent).toContain("部分资料来源读取失败，无法确认库内原文");
    expect(node.textContent).not.toContain("当前库未找到对应页原文");
    expect(node.querySelector('section[aria-label="资料来源"]')).toBeNull();
    expect(node.querySelector("blockquote")).toBeNull();
    expect(fetchKnowledgeItemBody).not.toHaveBeenCalled();
  });
});
