// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { revokeFinancialLesson, reviseFinancialLesson } from "../../api/financialEvaluation";
import type { FinancialClaim } from "../../api/types/financialEvaluation";
import { FinanceLessonManager } from "./FinanceLessonManager";

const api = vi.hoisted(() => ({ claims: vi.fn(), preferences: vi.fn(), revise: vi.fn(), revoke: vi.fn() }));
vi.mock("../../api/financialEvaluation", async (importOriginal) => ({
  ...await importOriginal<typeof import("../../api/financialEvaluation")>(),
  fetchFinancialClaims: api.claims,
  reviseFinancialLesson: api.revise,
  revokeFinancialLesson: api.revoke,
}));
vi.mock("../../api/financialPreferences", async (importOriginal) => ({
  ...await importOriginal<typeof import("../../api/financialPreferences")>(),
  fetchFinancialPreferences: api.preferences,
}));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const claim = (overrides: Partial<FinancialClaim> = {}): FinancialClaim => ({
  id: "validation-1", agentId: "finance-agent", sessionId: "source-session", turnId: "source-turn",
  symbol: "sh600519", analysisDate: "2024-10-09", dueDate: "2024-11-09", direction: "up", thresholdPct: 5,
  claimText: "贵州茅台上涨至少5%", status: "verified", registeredBeforeDue: true, retrospective: false,
  outcome: "hit", checkedAt: "2024-11-10", revision: 1, evidence: null, error: null,
  lesson: { id: "lesson-new", text: "修订后的现金流教训", createdAt: "2024-11-11T08:00:00Z", refs: [] },
  lessonState: "active",
  lessonHistory: [
    { lessonId: "lesson-old", text: "旧版现金流教训", state: "superseded", createdAt: "2024-11-10T08:00:00Z", supersededBy: "lesson-new" },
    { lessonId: "lesson-new", text: "修订后的现金流教训", state: "active", createdAt: "2024-11-11T08:00:00Z" },
  ],
  ...overrides,
});

let root: Root;
let node: HTMLDivElement;
let client: QueryClient;

async function settle() { await act(async () => new Promise((resolve) => setTimeout(resolve, 10))); }
async function render(agentId = "finance-agent") {
  await act(async () => root.render(<MemoryRouter initialEntries={["/finance?session=current-session"]}><QueryClientProvider client={client}><FinanceLessonManager agentId={agentId} zh /></QueryClientProvider></MemoryRouter>));
  await settle();
}
function button(label: string) { return [...document.querySelectorAll("button")].find((item) => item.textContent?.includes(label))!; }
async function setTextarea(value: string) {
  const input = document.querySelector<HTMLTextAreaElement>("textarea")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

beforeEach(() => {
  vi.resetAllMocks();
  node = document.createElement("div"); document.body.append(node); root = createRoot(node);
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  api.claims.mockResolvedValue({ agentId: "finance-agent", items: [claim()], limit: 100 });
  api.preferences.mockResolvedValue({ agentId: "finance-agent", memoryEnabled: true, items: [], limit: 200 });
});
afterEach(async () => { await act(async () => root.unmount()); client.clear(); node.remove(); });

it("shows structured lesson versions and links to the exact source report", async () => {
  await render();
  expect(node.textContent).toContain("沪市 600519");
  expect(node.textContent).toContain("分析日 2024-10-09");
  expect(node.textContent).toContain("旧版现金流教训");
  expect(node.textContent).toContain("已替代");
  expect(node.textContent).toContain("修订后的现金流教训");
  expect(node.textContent).toContain("有效");
  const link = [...node.querySelectorAll<HTMLAnchorElement>("a")].find((item) => item.textContent?.includes("打开原报告"))!;
  const params = new URL(link.href).searchParams;
  expect(params.get("finance_area")).toBe("reports");
  expect(params.get("finance_tab")).toBe("report");
  expect(params.get("finance_report_session")).toBe("source-session");
  expect(params.get("finance_report_turn")).toBe("source-turn");
  expect(params.get("session")).toBe("current-session");
});

it("exposes loading and empty states", async () => {
  let resolve!: (value: { agentId: string; items: FinancialClaim[]; limit: number }) => void;
  api.claims.mockImplementation(() => new Promise((done) => { resolve = done; }));
  await act(async () => root.render(<MemoryRouter initialEntries={["/finance"]}><QueryClientProvider client={client}><FinanceLessonManager agentId="finance-agent" zh /></QueryClientProvider></MemoryRouter>));
  expect(node.textContent).toContain("读取股票复盘教训");
  await act(async () => resolve({ agentId: "finance-agent", items: [], limit: 100 }));
  await settle();
  expect(node.textContent).toContain("暂无已确认的股票教训");
});

it("shows a retryable error when validation-backed lessons cannot be loaded", async () => {
  api.claims.mockRejectedValue(new Error("核验服务不可用"));
  await render();
  expect(node.textContent).toContain("核验服务不可用");
  expect(button("重试")).toBeTruthy();
});

it("allows revocation with memory disabled while blocking revision", async () => {
  api.preferences.mockResolvedValue({ agentId: "finance-agent", memoryEnabled: false, items: [], limit: 200 });
  api.revoke.mockResolvedValue(claim({ lesson: null, lessonState: "revoked" }));
  await render();
  expect(node.textContent).toContain("个人记忆已关闭");
  expect(button("修订").disabled).toBe(true);
  expect(button("作废").disabled).toBe(false);
  await act(async () => button("作废").click());
  expect(document.body.textContent).toContain("原报告和核验记录不会改变");
  await act(async () => button("确认作废").click());
  await settle();
  expect(revokeFinancialLesson).toHaveBeenCalledWith("finance-agent", "validation-1", expect.objectContaining({ expectedLessonId: "lesson-new", clientRequestId: expect.stringMatching(/^[\da-f-]{36}$/) }));
});

it("keeps a stable idempotency key when retrying a rejected revision", async () => {
  api.revise.mockRejectedValueOnce(new Error("版本已过期" )).mockResolvedValue(claim());
  await render();
  await act(async () => button("修订").click());
  await setTextarea("检查现金流中的应收变化");
  await act(async () => button("保存修订").click());
  await settle();
  expect(document.body.textContent).toContain("版本已过期");
  await act(async () => button("保存修订").click());
  await settle();
  expect(reviseFinancialLesson).toHaveBeenCalledTimes(2);
  expect(reviseFinancialLesson).toHaveBeenNthCalledWith(1, "finance-agent", "validation-1", expect.objectContaining({ text: "检查现金流中的应收变化", expectedLessonId: "lesson-new" }));
  expect(reviseFinancialLesson.mock.calls[0][2].clientRequestId).toBe(reviseFinancialLesson.mock.calls[1][2].clientRequestId);
});

it("prevents duplicate revision clicks while a request is pending", async () => {
  let resolve!: (value: FinancialClaim) => void;
  api.revise.mockImplementation(() => new Promise((done) => { resolve = done; }));
  await render();
  await act(async () => button("修订").click());
  await setTextarea("关注经营现金流质量");
  await act(async () => { button("保存修订").click(); button("保存修订").click(); });
  expect(reviseFinancialLesson).toHaveBeenCalledTimes(1);
  await act(async () => resolve(claim()));
  await settle();
});

it("does not let a late response for one Agent close the next Agent's editor", async () => {
  let resolve!: (value: FinancialClaim) => void;
  api.revise.mockImplementation(() => new Promise((done) => { resolve = done; }));
  await render();
  await act(async () => button("修订").click());
  await setTextarea("旧助手教训修订");
  await act(async () => button("保存修订").click());

  await render("finance-agent-2");
  await act(async () => button("修订").click());
  await act(async () => resolve(claim()));
  await settle();
  expect(button("保存修订")).toBeTruthy();
  expect(document.querySelector("textarea")).toBeTruthy();
});
