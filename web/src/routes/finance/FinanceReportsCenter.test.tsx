// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { FetchJsonHttpError } from "../../api/client";
import { downloadFinancialReportsExport, exportFinancialReport, fetchFinancialReports } from "../../api/financialReports";
import { markSessionDeleteTombstone, resetSessionDeleteTombstonesForTests } from "../sessionDeleteTombstone";
import { FinanceReportsCenter } from "./FinanceReportsCenter";

vi.mock("../../api/financialReports", async (importOriginal) => ({ ...await importOriginal<typeof import("../../api/financialReports")>(), fetchFinancialReports: vi.fn(), exportFinancialReport: vi.fn(), downloadFinancialReportsExport: vi.fn(), financialReportKeys: { catalog: (id: string, filters: unknown) => ["catalog", id, filters] } }));
vi.mock("./FinanceReportExport", () => ({ FinanceReportExport: ({ turnId }: { turnId: string }) => <span data-export-turn={turnId} /> }));
vi.mock("../../components/conversation/LazyConversationMarkdownRenderer", () => ({ LazyConversationMarkdownRenderer: ({ content }: { content: string }) => <article>{content}</article> }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let cleanup = async () => {};
afterEach(async () => { await cleanup(); resetSessionDeleteTombstonesForTests(); vi.clearAllMocks(); });

async function mountCenter(props: Parameters<typeof FinanceReportsCenter>[0]) {
  const node = document.createElement("div"), root = createRoot(node), client = new QueryClient(); document.body.append(node);
  cleanup = async () => { await act(async () => root.unmount()); client.clear(); node.remove(); };
  await act(async () => root.render(<QueryClientProvider client={client}><FinanceReportsCenter {...props} /></QueryClientProvider>));
  return node;
}

async function waitForQuery() {
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 25)); });
}

function setInputValue(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  setter?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

it("labels report search with the fields the catalog indexes", async () => {
  vi.mocked(fetchFinancialReports).mockResolvedValue({ items: [], nextCursor: null, scannedSessions: 0, order: "session_recency" });
  const node = await mountCenter({ agentId: "agent-1", cases: [], onSaveCases: vi.fn(async () => undefined), onOpenSession: vi.fn(), pending: false, zh: true });
  expect(node.querySelector<HTMLInputElement>('[aria-label="报告搜索"]')?.placeholder).toBe("代码 / 标题 / 摘要");
});

it("shows a clearable no-match state when searching saved cases", async () => {
  const node = await mountCenter({
    agentId: "agent-1",
    cases: [{ id: "case-1", sessionId: "session-1", turnId: "turn-1", title: "英伟达财报复盘", tags: ["NVDA", "AI"], note: "关注现金流" }],
    onSaveCases: vi.fn(async () => undefined), onOpenSession: vi.fn(), pending: false, zh: true, casesOnly: true,
  });
  const search = node.querySelector<HTMLInputElement>('[aria-label="案例搜索"]');
  expect(search).not.toBeNull();
  await act(async () => setInputValue(search!, "没有这条案例"));
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 275)); });

  expect(node.textContent).toContain("没有匹配的复盘案例");
  expect(node.textContent).toContain("试试其他标题、标签或备注关键词。");
  const clear = [...node.querySelectorAll("button")].find((button) => button.textContent === "清除搜索");
  expect(clear).toBeDefined();
  await act(async () => clear!.click());

  expect(node.textContent).toContain("英伟达财报复盘");
  expect(node.textContent).not.toContain("没有匹配的复盘案例");
});

it("opens the selected historical Turn rather than the latest answer in the same session", async () => {
  const reports = ["latest", "older"].map((id) => ({ sessionId: "session-1", turnId: id, title: `${id}研究`, sessionTitle: "同一会话", ticker: "AAPL", marketCode: "US" as const, completedAt: "2026-10-06T12:00:00+08:00", preview: "结果", chars: 20, kind: "research" as const }));
  vi.mocked(fetchFinancialReports).mockResolvedValue({ items: reports, nextCursor: null, scannedSessions: 1, order: "session_recency" });
  vi.mocked(exportFinancialReport).mockImplementation(async (target) => ({ sessionId: target.sessionId, turnId: target.turnId, format: "markdown", fileName: "report.md", mediaType: "text/markdown", encoding: "utf8", content: `${target.turnId}原始报告正文` }));
  const node = document.createElement("div"), root = createRoot(node), client = new QueryClient(); document.body.append(node);
  cleanup = async () => { await act(async () => root.unmount()); client.clear(); node.remove(); };
  const openSession = vi.fn();
  await act(async () => root.render(<QueryClientProvider client={client}><FinanceReportsCenter agentId="agent-1" cases={[]} onSaveCases={vi.fn()} onOpenSession={openSession} pending={false} zh /></QueryClientProvider>));
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
  const button = [...node.querySelectorAll("button")].find((item) => item.textContent?.includes("older研究"));
  expect(button).toBeDefined();
  await act(async () => button!.click());
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
  expect(vi.mocked(exportFinancialReport).mock.calls[0][0]).toMatchObject({ assistantAgentId: "agent-1", sessionId: "session-1", turnId: "older" });
  expect(node.querySelector("article")?.textContent).toBe("older原始报告正文");
  expect(node.querySelector("[data-export-turn=older]")).not.toBeNull();
  await act(async () => [...node.querySelectorAll("button")].find((item) => item.textContent === "打开原会话 / 追问")!.click());
  expect(openSession).toHaveBeenCalledWith("session-1");
});

it("marks a tombstoned review case as deleted while keeping its edit and remove actions", async () => {
  markSessionDeleteTombstone("session-deleted");
  const saveCases = vi.fn(async () => undefined);
  const node = await mountCenter({ agentId: "agent-1", cases: [{ id: "case-1", sessionId: "session-deleted", turnId: "turn-1", title: "已删除报告复盘", tags: ["复盘"], note: "保留这条备注" }], onSaveCases: saveCases, onOpenSession: vi.fn(), pending: false, zh: true, casesOnly: true });
  expect(node.textContent).toContain("原报告已删除，仍可编辑备注或删除此案例。");
  expect(node.textContent).toContain("保留这条备注");
  expect(vi.mocked(exportFinancialReport)).not.toHaveBeenCalled();
  const buttons = [...node.querySelectorAll("button")];
  const edit = buttons.find((button) => button.textContent === "编辑书签");
  const remove = buttons.find((button) => button.textContent === "删除书签");
  expect(edit?.disabled).toBe(false);
  expect(remove?.disabled).toBe(false);
  await act(async () => remove!.click());
  expect(saveCases).toHaveBeenCalled();
  const currentEdit = [...node.querySelectorAll("button")].find((button) => button.textContent === "编辑书签");
  await act(async () => currentEdit!.click());
  expect(document.body.querySelector('[aria-label="案例标题"]')).not.toBeNull();
});

it("marks an exact-report 404 as deleted and hides report export and session follow-up", async () => {
  vi.mocked(exportFinancialReport).mockRejectedValue(new FetchJsonHttpError("financial report not found", { status: 404, code: "financial_report_not_found" }));
  const node = await mountCenter({ agentId: "agent-1", cases: [{ id: "case-1", sessionId: "session-deleted", turnId: "turn-1", title: "已删除报告复盘", tags: [], note: "备注仍在" }], onSaveCases: vi.fn(async () => undefined), onOpenSession: vi.fn(), pending: false, zh: true, casesOnly: true });
  const openCase = [...node.querySelectorAll("button")].find((button) => button.textContent === "已删除报告复盘");
  await act(async () => openCase!.click());
  await waitForQuery();
  expect(node.textContent).toContain("原报告已删除");
  expect(node.textContent).toContain("备注仍在");
  expect(node.querySelector("[data-export-turn]" )).toBeNull();
  expect([...node.querySelectorAll("button")].some((button) => button.textContent === "打开原会话 / 追问")).toBe(false);
  expect([...node.querySelectorAll("button")].some((button) => button.textContent === "编辑书签" && !button.disabled)).toBe(true);
  expect([...node.querySelectorAll("button")].some((button) => button.textContent === "删除书签" && !button.disabled)).toBe(true);
});

it.each([
  ["403", new FetchJsonHttpError("forbidden", { status: 403 })],
  ["network", new Error("network disconnected")],
])("does not treat %s failures as a deleted report", async (_kind, failure) => {
  vi.mocked(exportFinancialReport).mockRejectedValue(failure);
  const node = await mountCenter({ agentId: "agent-1", cases: [{ id: "case-1", sessionId: "session-1", turnId: "turn-1", title: "可访问性待确认", tags: [], note: "" }], onSaveCases: vi.fn(async () => undefined), onOpenSession: vi.fn(), pending: false, zh: true, casesOnly: true });
  const openCase = [...node.querySelectorAll("button")].find((button) => button.textContent === "可访问性待确认");
  await act(async () => openCase!.click());
  await waitForQuery();
  expect(node.textContent).toContain("报告不可用");
  expect(node.textContent).not.toContain("原报告已删除");
  expect(node.textContent).toContain("重试");
  expect(node.querySelector("[data-export-turn]" )).not.toBeNull();
  expect([...node.querySelectorAll("button")].some((button) => button.textContent === "打开原会话 / 追问")).toBe(true);
});

it("removes a report confirmed missing from selection and excludes it from batch export", async () => {
  const reports = [
    { sessionId: "session-deleted", turnId: "turn-missing", title: "缺失报告", sessionTitle: "删除的会话", ticker: "AAPL", marketCode: "US" as const, completedAt: "2026-10-06T12:00:00+08:00", preview: "结果", chars: 20, kind: "research" as const },
    { sessionId: "session-valid", turnId: "turn-valid", title: "有效报告", sessionTitle: "保留的会话", ticker: "MSFT", marketCode: "US" as const, completedAt: "2026-10-06T12:00:00+08:00", preview: "结果", chars: 20, kind: "research" as const },
  ];
  vi.mocked(fetchFinancialReports).mockResolvedValue({ items: reports, nextCursor: null, scannedSessions: 2, order: "session_recency" });
  vi.mocked(exportFinancialReport).mockRejectedValue(new FetchJsonHttpError("financial report not found", { status: 404, code: "financial_report_not_found" }));
  vi.mocked(downloadFinancialReportsExport).mockResolvedValue(undefined);
  const node = await mountCenter({ agentId: "agent-1", cases: [], onSaveCases: vi.fn(async () => undefined), onOpenSession: vi.fn(), pending: false, zh: true });
  await waitForQuery();
  const missingCheckbox = node.querySelector<HTMLInputElement>('input[aria-label="选择 缺失报告 turn-missing"]');
  const validCheckbox = node.querySelector<HTMLInputElement>('input[aria-label="选择 有效报告 turn-valid"]');
  expect(missingCheckbox).not.toBeNull();
  expect(validCheckbox).not.toBeNull();
  await act(async () => missingCheckbox!.click());
  await act(async () => validCheckbox!.click());
  const reportButton = [...node.querySelectorAll("button")].find((button) => button.textContent?.includes("缺失报告"));
  await act(async () => reportButton!.click());
  await waitForQuery();
  expect(missingCheckbox!.checked).toBe(false);
  expect(missingCheckbox!.disabled).toBe(true);
  expect(validCheckbox!.checked).toBe(true);
  const batchButton = [...node.querySelectorAll("button")].find((button) => button.textContent?.includes("导出选中 1/20"));
  await act(async () => batchButton!.click());
  expect(vi.mocked(downloadFinancialReportsExport)).toHaveBeenCalledWith("agent-1", [{ sessionId: "session-valid", turnId: "turn-valid" }], "markdown");
});
