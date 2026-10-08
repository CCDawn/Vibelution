// @vitest-environment happy-dom

import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FetchJsonHttpError } from "../../api/client";
import type { FinancialPortfolioProposal, FinancialPortfolioPosition } from "../../api/types/financialPortfolio";

const api = vi.hoisted(() => ({
  approve: vi.fn(),
  create: vi.fn(),
  fetchProposal: vi.fn(),
  fetchProposals: vi.fn(),
  preview: vi.fn(),
  fetchReports: vi.fn(),
}));

vi.mock("../../api/financialPortfolio", async (importOriginal) => ({
  ...await importOriginal<typeof import("../../api/financialPortfolio")>(),
  approveFinancialPortfolioProposal: api.approve,
  createFinancialPortfolioProposal: api.create,
  fetchFinancialPortfolioProposal: api.fetchProposal,
  fetchFinancialPortfolioProposals: api.fetchProposals,
  previewFinancialPortfolioProposal: api.preview,
  isFinancialPortfolioProposalNotFound: (error: unknown) => error instanceof FetchJsonHttpError && error.status === 404,
}));
vi.mock("../../api/financialReports", () => ({
  fetchFinancialReports: api.fetchReports,
  financialReportKeys: { catalog: (agentId: string, filters: unknown) => ["finance", "report-catalog", agentId, filters] },
}));
vi.mock("./FinanceReportExport", () => ({
  FinanceReportExport: ({ sessionId, turnId }: { sessionId: string; turnId: string }) => <span data-export-session={sessionId} data-export-turn={turnId} />,
}));

import { FinanceRebalance } from "./FinanceRebalance";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const report = {
  sessionId: "session-1", turnId: "turn-8", title: "浦发银行研究", sessionTitle: "浦发银行",
  ticker: "600000", marketCode: "CN" as const, completedAt: "2026-10-08T08:00:00Z",
  preview: "盈利质量改善，关注资产质量。", chars: 1200, kind: "research" as const,
};
const position: FinancialPortfolioPosition = {
  symbol: "sh600519", ticker: "600519", name: "贵州茅台", market: "上交所", quantity: 100,
  markPriceYuan: "1500.00", marketValueYuan: "150000.00", unrealizedPnlYuan: "1000.00", weightPercent: "15.00",
  valuationStatus: "fresh", quoteTimestamp: "2026-10-08T15:00:00+08:00", quoteFetchedAt: "2026-10-08T07:00:00Z",
  source: "腾讯财经", sourceUrl: "https://gu.qq.com/", returnSeriesStatus: "available",
};
const readyProposal = (overrides: Partial<FinancialPortfolioProposal> = {}): FinancialPortfolioProposal => ({
  proposalId: "11111111-1111-4111-8111-111111111111", agentId: "agent-1", status: "ready",
  createdAt: "2026-10-08T08:00:00Z", expiresAt: "2099-10-08T09:00:00Z", modelId: "model-1",
  reportRefs: [{ sessionId: report.sessionId, turnId: report.turnId, contentHash: "source-hash" }],
  targets: [{ symbol: "sh600519", weightPct: 20, reason: "降低集中度" }], summaryReason: "基于已完成报告和当前模拟持仓。",
  riskChecks: [{ code: "cash", label: "现金储备", passed: true, detail: "预计现金满足最低比例" }],
  orders: [{ symbol: "sh600519", name: "贵州茅台", side: "sell", quantity: 100, priceYuan: "1500.00", grossAmountYuan: "150000.00", feeYuan: "50.00", reason: "降低集中度" }],
  metrics: { equityYuan: "1000000.00", cashAfterYuan: "250000.00", turnoverPct: "15.00", feesYuan: "50.00" },
  policy: { maxPositionPct: 30, minCashPct: 10, maxTurnoverPct: 100, maxQuoteAgeHours: 72 },
  planHash: "plan-hash-1", error: null, execution: null, ...overrides,
});

let root: Root;
let node: HTMLDivElement;
let client: QueryClient;

function button(text: string): HTMLButtonElement {
  const found = Array.from(document.querySelectorAll("button")).find((item) => item.textContent?.includes(text));
  if (!found) throw new Error(`Button not found: ${text}`);
  return found;
}

function input(label: string): HTMLInputElement | HTMLTextAreaElement {
  const found = node.querySelector<HTMLInputElement | HTMLTextAreaElement>(`[aria-label="${label}"]`);
  if (!found) throw new Error(`Input not found: ${label}`);
  return found;
}

async function settle() {
  await act(async () => { await Promise.resolve(); await new Promise((resolve) => setTimeout(resolve, 0)); });
}

async function render(agentId = "agent-1") {
  await act(async () => root.render(<QueryClientProvider client={client}><FinanceRebalance agentId={agentId} positions={[position]} zh /></QueryClientProvider>));
  await settle();
}

async function setValue(element: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  await act(async () => {
    Object.getOwnPropertyDescriptor(prototype, "value")?.set?.call(element, value);
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.stubGlobal("crypto", { randomUUID: () => "11111111-1111-4111-8111-111111111111" });
  api.fetchReports.mockResolvedValue({ items: [report], nextCursor: null, scannedSessions: 1, order: "session_recency" });
  api.fetchProposals.mockResolvedValue({ items: [] });
  api.fetchProposal.mockResolvedValue(readyProposal());
  api.create.mockResolvedValue(readyProposal());
  api.preview.mockImplementation(async (_agent: string, id: string, request: { targets: unknown[]; policy: unknown }) => readyProposal({
    proposalId: id,
    targets: request.targets as FinancialPortfolioProposal["targets"],
    policy: request.policy as FinancialPortfolioProposal["policy"],
    planHash: "plan-hash-2",
  }));
  api.approve.mockResolvedValue(readyProposal({ status: "executed", execution: { batchId: "batch-1", executedAt: "2026-10-08T08:30:00Z" } }));
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  node = document.createElement("div"); document.body.appendChild(node); root = createRoot(node);
});

afterEach(async () => {
  await act(async () => root.unmount());
  client.clear(); node.remove(); vi.unstubAllGlobals();
});

describe("FinanceRebalance", () => {
  it("refreshes the completed report list in place", async () => {
    await render();
    expect(api.fetchReports).toHaveBeenCalledTimes(1);

    await act(async () => button("刷新报告").click());
    await settle();

    expect(api.fetchReports).toHaveBeenCalledTimes(2);
  });

  it("uses the exact selected completed report and current holdings to create an idempotent proposal", async () => {
    await render();
    expect(input("候选股票代码").value).toBe("sh600519");
    const reportCheckbox = node.querySelector<HTMLInputElement>(`input[aria-label="选择报告 ${report.title}"]`);
    expect(reportCheckbox).not.toBeNull();
    await act(async () => reportCheckbox!.click());
    await setValue(input("组合目标"), "降低单股集中度并保留现金");
    await act(async () => button("生成建议").click());
    await settle();

    expect(api.create).toHaveBeenCalledTimes(1);
    expect(api.create).toHaveBeenCalledWith("agent-1", {
      clientRequestId: "11111111-1111-4111-8111-111111111111",
      symbols: ["SH600519"],
      reports: [{ sessionId: "session-1", turnId: "turn-8" }],
      instruction: "降低单股集中度并保留现金",
      policy: { maxPositionPct: 30, minCashPct: 10, maxTurnoverPct: 100, maxQuoteAgeHours: 72 },
    });
    expect(node.textContent).toContain("浦发银行研究");
    expect(node.querySelector('[aria-label="模拟订单"]')).not.toBeNull();
    expect(node.querySelector('[data-export-session="session-1"][data-export-turn="turn-8"]')).not.toBeNull();
    expect(node.querySelector('span[title*="浦发银行研究"]')?.getAttribute("title")).toMatch(/2026/);
    expect(node.textContent).toContain("模型 model-1");
  });

  it("does not read a proposal until its create request has returned", async () => {
    let resolveCreate!: (value: FinancialPortfolioProposal) => void;
    api.create.mockImplementation(() => new Promise<FinancialPortfolioProposal>((resolve) => { resolveCreate = resolve; }));
    await render();
    await act(async () => node.querySelector<HTMLInputElement>(`input[aria-label="选择报告 ${report.title}"]`)!.click());
    await setValue(input("组合目标"), "保留有证据的仓位");

    await act(async () => button("生成建议").click());
    await settle();

    expect(api.create).toHaveBeenCalledTimes(1);
    expect(api.fetchProposal).not.toHaveBeenCalled();
    expect(node.textContent).not.toContain("组合建议不存在");

    await act(async () => resolveCreate(readyProposal()));
    await settle();
    expect(node.textContent).toContain("建议详情");
  });

  it("shows a source as unavailable instead of substituting another report from the same session", async () => {
    const missingSource = readyProposal({ reportRefs: [{ sessionId: report.sessionId, turnId: "turn-older", contentHash: "older-hash" }] });
    api.fetchProposals.mockResolvedValue({ items: [missingSource] });
    api.fetchProposal.mockResolvedValue(missingSource);
    await render();
    await act(async () => button("待批准").click());
    await settle();

    const sourceList = node.querySelector('[aria-label="参考报告"]');
    expect(sourceList?.textContent).toContain("报告暂不可用");
    expect(sourceList?.textContent).not.toContain("浦发银行研究");
    expect(node.textContent).toContain("模型 model-1");
    expect(node.querySelector("[data-export-session]")).toBeNull();
  });

  it("clamps long report previews and model summaries while preserving their source text", async () => {
    const longPreview = "来源内容。".repeat(50);
    const longSummary = "模型依据。".repeat(80);
    api.fetchReports.mockResolvedValue({ items: [{ ...report, preview: longPreview }], nextCursor: null, scannedSessions: 1, order: "session_recency" });
    const proposal = readyProposal({ summaryReason: longSummary });
    api.fetchProposals.mockResolvedValue({ items: [proposal] });
    api.fetchProposal.mockResolvedValue(proposal);
    await render();
    await act(async () => button("待批准").click());
    await settle();

    const preview = node.querySelector<HTMLElement>("[data-report-preview]");
    const summary = node.querySelector<HTMLElement>("[data-model-summary]");
    expect(preview?.className).toContain("truncate");
    expect(preview?.className).toContain("whitespace-nowrap");
    expect(preview?.textContent).toBe(longPreview);
    expect(summary?.className).toContain("line-clamp-3");
    expect(summary?.textContent).toBe(longSummary);

    await act(async () => node.querySelector<HTMLButtonElement>('button[aria-label="展开报告摘要 浦发银行研究"]')!.click());
    await act(async () => node.querySelector<HTMLButtonElement>('button[aria-label="展开模型摘要"]')!.click());
    expect(node.querySelector("[data-report-preview]")?.className).not.toContain("truncate");
    expect(node.querySelector("[data-report-preview]")?.className).not.toContain("whitespace-nowrap");
    expect(node.querySelector("[data-model-summary]")?.className).not.toContain("line-clamp-3");
  });

  it("requires a fresh server plan hash and a second explicit confirmation before simulated execution", async () => {
    const proposal = readyProposal();
    api.fetchProposals.mockResolvedValue({ items: [proposal] });
    api.fetchProposal.mockResolvedValue(proposal);
    await render();
    await act(async () => button("待批准").click());
    await settle();
    const approveButton = button("核对订单");
    expect(approveButton.disabled).toBe(false);

    await setValue(input("sh600519目标仓位"), "18");
    await settle();
    expect(button("核对订单").disabled).toBe(true);
    await act(async () => button("重新检查计划").click());
    await settle();
    expect(api.preview).toHaveBeenCalledWith("agent-1", proposal.proposalId, {
      targets: [{ symbol: "sh600519", weightPct: 18, reason: "降低集中度" }],
      policy: proposal.policy,
    });
    expect(button("核对订单").disabled).toBe(false);
    await act(async () => button("核对订单").click());
    expect(document.body.textContent).toContain("确认模拟成交");
    expect(document.body.textContent).toContain("卖出 贵州茅台 · sh600519");
    await act(async () => button("确认模拟成交").click());
    await settle();

    expect(api.approve).toHaveBeenCalledWith("agent-1", proposal.proposalId, { planHash: "plan-hash-2", confirmSimulation: true });
    expect(node.textContent).toContain("已模拟执行");
  });

  it("reads an ambiguous create by its UUID before allowing the identical retry", async () => {
    api.create.mockRejectedValueOnce(new Error("network disconnected")).mockResolvedValueOnce(readyProposal());
    await render();
    const checkbox = node.querySelector<HTMLInputElement>(`input[aria-label="选择报告 ${report.title}"]`)!;
    await act(async () => checkbox.click());
    await setValue(input("组合目标"), "按证据降低集中度");
    await act(async () => button("生成建议").click());
    await settle();
    expect(api.create).toHaveBeenCalledTimes(1);
    expect(api.fetchProposal).not.toHaveBeenCalled();
    expect(node.textContent).not.toContain("组合建议不存在");

    api.fetchProposal.mockRejectedValueOnce(new FetchJsonHttpError("组合建议不存在", { status: 404 }));
    await act(async () => button("查询结果").click());
    await settle();
    expect(button("重试生成")).not.toBeNull();
    await act(async () => button("重试生成").click());
    await settle();

    expect(api.create).toHaveBeenCalledTimes(2);
    expect(api.create.mock.calls[0]).toEqual(api.create.mock.calls[1]);
  });

  it("refreshes proposal history after a successful create readback", async () => {
    const recovered = readyProposal();
    const responses = [
      { items: [] },
      { items: [] },
      { items: [recovered] },
    ];
    api.fetchProposals.mockImplementation(async () => responses.shift() ?? { items: [recovered] });
    api.create.mockRejectedValueOnce(new Error("network disconnected"));
    await render();
    await act(async () => node.querySelector<HTMLInputElement>(`input[aria-label="选择报告 ${report.title}"]`)!.click());
    await setValue(input("组合目标"), "按证据降低集中度");
    await act(async () => button("生成建议").click());
    await settle();

    const fetchCountBeforeReadback = api.fetchProposals.mock.calls.length;
    expect(fetchCountBeforeReadback).toBeGreaterThanOrEqual(1);
    await act(async () => button("查询结果").click());
    await settle();

    expect(api.fetchProposals).toHaveBeenCalledTimes(fetchCountBeforeReadback + 1);
    expect(client.getQueryData(["financial-portfolio", "agent-1", "proposals"])).toEqual({ items: [recovered] });
    expect(node.textContent).toContain("建议详情");
  });

  it("keeps expired and blocked plans from reaching the approval dialog", async () => {
    const blocked = readyProposal({ status: "blocked", riskChecks: [{ code: "cash", label: "现金储备", passed: false, detail: "现金低于下限" }] });
    api.fetchProposals.mockResolvedValue({ items: [blocked] });
    api.fetchProposal.mockImplementation(async (_agent: string, id: string) => id === "22222222-2222-4222-8222-222222222222" ? readyProposal({ proposalId: id, expiresAt: "2000-01-01T00:00:00Z" }) : blocked);
    await render();
    await act(async () => button("风控阻断").click());
    await settle();
    expect(button("核对订单").disabled).toBe(true);

    const expired = readyProposal({ proposalId: "22222222-2222-4222-8222-222222222222", expiresAt: "2000-01-01T00:00:00Z" });
    await act(async () => {
      client.setQueryData(["financial-portfolio", "agent-1", "proposals"], { items: [expired] });
      client.setQueryData(["financial-portfolio", "agent-1", "proposal", expired.proposalId], expired);
    });
    await act(async () => root.render(<QueryClientProvider client={client}><FinanceRebalance agentId="agent-1" positions={[position]} zh /></QueryClientProvider>));
    await settle();
    await act(async () => button("待批准").click());
    await settle();
    expect(button("核对订单").disabled).toBe(true);
    expect(node.textContent).toContain("建议已过期");
    expect(button("重新检查计划").disabled).toBe(false);

    await act(async () => button("重新检查计划").click());
    await settle();
    expect(api.preview).toHaveBeenCalledWith("agent-1", expired.proposalId, {
      targets: expired.targets,
      policy: expired.policy,
    });
    expect(button("核对订单").disabled).toBe(false);
  });

  it("does not show an expired warning or review action for an executed proposal", async () => {
    const executed = readyProposal({
      status: "executed",
      expiresAt: "2000-01-01T00:00:00Z",
      execution: { batchId: "batch-3", executedAt: "2026-10-08T08:40:00Z" },
    });
    api.fetchProposals.mockResolvedValue({ items: [executed] });
    api.fetchProposal.mockResolvedValue(executed);
    await render();
    await act(async () => button("已模拟执行").click());
    await settle();

    expect(node.textContent).not.toContain("建议已过期");
    expect(node.textContent).toContain("模拟成交");
    expect(Array.from(node.querySelectorAll("button")).some((item) => item.textContent?.includes("核对订单"))).toBe(false);
  });

  it("reads back an uncertain approval and invalidates the paper account if it executed", async () => {
    const proposal = readyProposal();
    const executed = readyProposal({ status: "executed", execution: { batchId: "batch-2", executedAt: "2026-10-08T08:35:00Z" } });
    api.fetchProposals.mockResolvedValue({ items: [proposal] });
    api.fetchProposal.mockResolvedValueOnce(proposal).mockResolvedValueOnce(executed);
    api.approve.mockRejectedValueOnce(new Error("network disconnected"));
    client.setDefaultOptions({ queries: { retry: false, gcTime: 60_000 } });
    await act(async () => {
      client.setQueryData(["financial-paper", "agent-1", "account"], { cashYuan: "100" });
      client.setQueryData(["financial-paper", "agent-1", "review", "2026-10"], { summary: {} });
      client.setQueryData(["financial-portfolio", "agent-1", "research"], { positions: [] });
    });
    await render();
    await act(async () => button("待批准").click());
    await settle();
    await act(async () => button("核对订单").click());
    await act(async () => button("确认模拟成交").click());
    await settle();

    expect(api.approve).toHaveBeenCalledTimes(1);
    expect(api.fetchProposal).toHaveBeenCalledTimes(2);
    expect(node.textContent).toContain("已模拟执行");
    expect(client.getQueryState(["financial-paper", "agent-1", "account"])?.isInvalidated).toBe(true);
    expect(client.getQueryState(["financial-paper", "agent-1", "review", "2026-10"])?.isInvalidated).toBe(true);
    expect(client.getQueryState(["financial-portfolio", "agent-1", "research"])?.isInvalidated).toBe(true);
  });

  it("invalidates only the previous Agent's caches when an approval succeeds after switching", async () => {
    const proposal = readyProposal();
    const executed = readyProposal({ status: "executed", execution: { batchId: "batch-4", executedAt: "2026-10-08T08:45:00Z" } });
    let resolveApproval!: (value: FinancialPortfolioProposal) => void;
    api.fetchProposals.mockResolvedValue({ items: [proposal] });
    api.approve.mockImplementation(() => new Promise<FinancialPortfolioProposal>((resolve) => { resolveApproval = resolve; }));
    client.setDefaultOptions({ queries: { retry: false, gcTime: 60_000 } });
    await act(async () => {
      for (const agentId of ["agent-1", "agent-2"]) {
        client.setQueryData(["financial-paper", agentId, "account"], { cashYuan: "100" });
        client.setQueryData(["financial-paper", agentId, "review", "2026-10"], { summary: {} });
        client.setQueryData(["financial-portfolio", agentId, "research"], { positions: [] });
        client.setQueryData(["financial-portfolio", agentId, "proposals"], { items: agentId === "agent-1" ? [proposal] : [] });
        client.setQueryData(["financial-portfolio", agentId, "proposal", proposal.proposalId], agentId === "agent-1" ? proposal : readyProposal({ agentId }));
      }
    });

    await render();
    await act(async () => button("待批准").click());
    await settle();
    await act(async () => button("核对订单").click());
    await act(async () => button("确认模拟成交").click());
    await settle();
    expect(api.approve).toHaveBeenCalledTimes(1);

    await render("agent-2");
    await act(async () => resolveApproval(executed));
    await settle();

    for (const key of [
      ["financial-paper", "agent-1", "account"],
      ["financial-paper", "agent-1", "review", "2026-10"],
      ["financial-portfolio", "agent-1", "research"],
      ["financial-portfolio", "agent-1", "proposals"],
      ["financial-portfolio", "agent-1", "proposal", proposal.proposalId],
    ]) {
      expect(client.getQueryState(key)?.isInvalidated).toBe(true);
    }
    for (const key of [
      ["financial-paper", "agent-2", "account"],
      ["financial-paper", "agent-2", "review", "2026-10"],
      ["financial-portfolio", "agent-2", "research"],
      ["financial-portfolio", "agent-2", "proposals"],
      ["financial-portfolio", "agent-2", "proposal", proposal.proposalId],
    ]) {
      expect(client.getQueryState(key)?.isInvalidated).not.toBe(true);
    }
    expect(api.fetchProposals.mock.calls.some(([agentId]) => agentId === "agent-2")).toBe(false);
    expect(node.querySelector('[aria-label="模拟订单"]')).toBeNull();
    expect(node.textContent).not.toContain("已模拟执行");
  });

  it("invalidates only the old Agent's caches when an approval readback confirms execution after switching", async () => {
    const proposal = readyProposal();
    const executed = readyProposal({ status: "executed", execution: { batchId: "batch-5", executedAt: "2026-10-08T08:50:00Z" } });
    let resolveReadback!: (value: FinancialPortfolioProposal) => void;
    api.fetchProposals.mockResolvedValue({ items: [proposal] });
    api.fetchProposal.mockResolvedValueOnce(proposal).mockImplementationOnce(() => new Promise<FinancialPortfolioProposal>((resolve) => { resolveReadback = resolve; }));
    api.approve.mockRejectedValueOnce(new Error("network disconnected"));
    client.setDefaultOptions({ queries: { retry: false, gcTime: 60_000 } });
    await act(async () => {
      for (const agentId of ["agent-1", "agent-2"]) {
        client.setQueryData(["financial-paper", agentId, "account"], { cashYuan: "100" });
        client.setQueryData(["financial-paper", agentId, "review", "2026-10"], { summary: {} });
        client.setQueryData(["financial-portfolio", agentId, "research"], { positions: [] });
        client.setQueryData(["financial-portfolio", agentId, "proposals"], { items: agentId === "agent-1" ? [proposal] : [] });
        client.setQueryData(["financial-portfolio", agentId, "proposal", proposal.proposalId], agentId === "agent-1" ? proposal : readyProposal({ agentId }));
      }
    });

    await render();
    await act(async () => button("待批准").click());
    await settle();
    await act(async () => button("核对订单").click());
    await act(async () => button("确认模拟成交").click());
    await settle();
    expect(api.approve).toHaveBeenCalledTimes(1);
    expect(api.fetchProposal).toHaveBeenCalledTimes(2);

    await render("agent-2");
    await act(async () => resolveReadback(executed));
    await settle();

    for (const key of [
      ["financial-paper", "agent-1", "account"],
      ["financial-paper", "agent-1", "review", "2026-10"],
      ["financial-portfolio", "agent-1", "research"],
      ["financial-portfolio", "agent-1", "proposals"],
      ["financial-portfolio", "agent-1", "proposal", proposal.proposalId],
    ]) {
      expect(client.getQueryState(key)?.isInvalidated).toBe(true);
    }
    for (const key of [
      ["financial-paper", "agent-2", "account"],
      ["financial-paper", "agent-2", "review", "2026-10"],
      ["financial-portfolio", "agent-2", "research"],
      ["financial-portfolio", "agent-2", "proposals"],
      ["financial-portfolio", "agent-2", "proposal", proposal.proposalId],
    ]) {
      expect(client.getQueryState(key)?.isInvalidated).not.toBe(true);
    }
    expect(api.fetchProposals.mock.calls.some(([agentId]) => agentId === "agent-2")).toBe(false);
    expect(node.querySelector('[aria-label="模拟订单"]')).toBeNull();
    expect(node.textContent).not.toContain("已模拟执行");
  });

  it("does not let a late create response from one Agent replace the next Agent's view", async () => {
    let resolveCreate!: (value: FinancialPortfolioProposal) => void;
    api.create.mockImplementation(() => new Promise<FinancialPortfolioProposal>((resolve) => { resolveCreate = resolve; }));
    await render();
    await act(async () => node.querySelector<HTMLInputElement>(`input[aria-label="选择报告 ${report.title}"]`)!.click());
    await setValue(input("组合目标"), "保留现有仓位");
    await act(async () => button("生成建议").click());
    await render("agent-2");
    await act(async () => { resolveCreate(readyProposal()); });
    await settle();

    expect(node.textContent).not.toContain("建议详情");
    expect(node.textContent).not.toContain("model-1");
    expect(api.create).toHaveBeenCalledTimes(1);
  });
});
