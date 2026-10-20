// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as api from "../../api/financialPreferences";
import type { ConversationMessage } from "../../api/types";
import type { FinancialWorkspaceSettings } from "../../api/types/financialPreferences";
import { FinanceAdvisorPanel } from "./FinanceAdvisorPanel";

vi.mock("../../api/financialPreferences", async original => ({
  ...await original<typeof import("../../api/financialPreferences")>(),
  fetchFinancialWorkspace: vi.fn(), fetchFinancialAdvisorProposal: vi.fn(),
  financialAdvisorCommand: vi.fn(), checkFinancialAdvisorPlan: vi.fn(),
}));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root, host: HTMLDivElement, client: QueryClient, state: FinancialWorkspaceSettings;
const fingerprint = "a".repeat(64);
const message = { role: "assistant", status: "completed", turnId: "turn",
  turnItems: [{ type: "agent_message", phase: "final_answer", status: "completed", text: "```investment-proposal\n{}\n```" }],
} as ConversationMessage;
beforeEach(() => {
  vi.resetAllMocks();
  state = { schemaVersion: 1, agentId: "a", revision: 3, updatedAt: "", selectedStock: null, watchlist: [], profiles: [], manualPositions: [], reviewCases: [], investmentProfile: { budgetCny: 6000 }, investmentPlans: [], investmentStateFingerprint: fingerprint };
  vi.mocked(api.fetchFinancialWorkspace).mockImplementation(async () => state);
  vi.mocked(api.fetchFinancialAdvisorProposal).mockResolvedValue({ proposal: { kind: "profile", baseFingerprint: fingerprint, profile: { budgetCny: 8000 } } });
  vi.mocked(api.financialAdvisorCommand).mockImplementation(async () => ({ ...state, revision: 4, investmentProfile: { budgetCny: 8000 } }));
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});
afterEach(async () => { await act(async () => root.unmount()); client.clear(); host.remove(); });
async function settle() { await act(async () => new Promise(resolve => setTimeout(resolve, 25))); }
async function render(messages: ConversationMessage[] = [message]) {
  await act(async () => root.render(<QueryClientProvider client={client}><FinanceAdvisorPanel agentId="a" zh view={{ sessionId: "session", agentId: "a", title: "", status: "idle", busy: false, stopping: false, messages }} onConditions={vi.fn()} onResearch={vi.fn()} /></QueryClientProvider>));
  await settle();
}
async function click(label: string) {
  await act(async () => [...document.querySelectorAll("button")].find(button => button.textContent?.includes(label))!.click());
  await settle();
}
it("shows the change before explicit confirmation and never writes while reading", async () => {
  await render(); await click("查看待确认内容");
  expect(document.body.textContent).toContain("8,000 CNY");
  expect(document.body.textContent).toContain("原来：6,000 CNY");
  expect(api.financialAdvisorCommand).not.toHaveBeenCalled();
  await click("确认保存");
  expect(api.financialAdvisorCommand).toHaveBeenCalledWith("a", { action: "confirm_proposal", expectedRevision: 3, sessionId: "session", turnId: "turn" });
  expect(document.body.textContent).toContain("已保存");
});
it("blocks a proposal based on old investment state", async () => {
  state.investmentStateFingerprint = "b".repeat(64);
  await render(); await click("查看待确认内容");
  expect([...document.querySelectorAll("button")].find(button => button.textContent === "确认保存")?.disabled).toBe(true);
  expect(api.financialAdvisorCommand).not.toHaveBeenCalled();
});
it("does not discover a proposal in user, tool, or incomplete output", async () => {
  await render([{ ...message, role: "user" }, { ...message, status: "running" }] as ConversationMessage[]);
  expect(api.fetchFinancialAdvisorProposal).not.toHaveBeenCalled();
});
it("keeps adoption disabled until the numeric check passes and preserves failure feedback", async () => {
  state.investmentPlans = [{ id: "p", title: "观察", rationale: "等待", orders: [], reviewAfter: null, status: "proposed", createdAt: "", updatedAt: "", source: { sessionId: "old", turnId: "old" }, stateFingerprint: fingerprint, needsReview: false }];
  vi.mocked(api.checkFinancialAdvisorPlan).mockResolvedValue({ passed: false, blockers: ["现金未确认"], warnings: [], feesCny: 0, cashAfterCny: null, orders: [] });
  await render([]); await click("当前方案");
  expect([...document.querySelectorAll("button")].find(button => button.textContent === "采纳方案")?.disabled).toBe(true);
  await click("核算金额与仓位");
  expect(document.body.textContent).toContain("现金未确认");
  expect(api.financialAdvisorCommand).not.toHaveBeenCalled();
});
it("freezes the execution form revision and stops submission after another page changes state", async () => {
  state.investmentPlans = [{ id: "p", title: "已采纳", rationale: "等待", orders: [], reviewAfter: null, status: "adopted", createdAt: "", updatedAt: "", source: { sessionId: "old", turnId: "old" }, stateFingerprint: fingerprint, needsReview: false }];
  await render([]); await click("当前方案"); await click("记录实际执行");
  await act(async () => client.setQueryData(api.financialWorkspaceKey("a"), { ...state, revision: 4, investmentProfile: { budgetCny: 9000 } }));
  await settle();
  expect(document.body.textContent).toContain("记录期间投资状态发生变化");
  const cash = document.querySelector<HTMLInputElement>('input[aria-label="实际可用现金（元）"]');
  expect(cash?.disabled).toBe(true);
  expect(api.financialAdvisorCommand).not.toHaveBeenCalled();
  await click("关闭执行表单");
  expect(document.body.textContent).not.toContain("记录期间投资状态发生变化");
});
