// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { fetchFinancialWorkspace, updateFinancialWorkspace } from "../../api/financialPreferences";
import { FinanceInvestmentSettings } from "./FinanceInvestmentSettings";

vi.mock("../../api/financialPreferences", async original => ({
  ...await original<typeof import("../../api/financialPreferences")>(),
  fetchFinancialWorkspace: vi.fn(), updateFinancialWorkspace: vi.fn(),
}));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root, host: HTMLDivElement, client: QueryClient;
const state = { schemaVersion: 1 as const, agentId: "a", revision: 2, updatedAt: "", selectedStock: null, watchlist: [], profiles: [], manualPositions: [], reviewCases: [], investmentProfile: null };
beforeEach(() => {
  vi.resetAllMocks();
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  vi.mocked(fetchFinancialWorkspace).mockResolvedValue(state);
  vi.mocked(updateFinancialWorkspace).mockImplementation(async (_id, revision, patch) => ({ ...state, ...patch, ...(patch.investmentProfile ? { investmentProfile: { flexibleHorizon: patch.investmentProfile.flexibleHorizon, ...patch.investmentProfile } } : {}), revision: revision + 1 }));
});
afterEach(async () => { await act(async () => root.unmount()); client.clear(); host.remove(); });
async function render() {
  await act(async () => root.render(<QueryClientProvider client={client}><FinanceInvestmentSettings agentId="a" zh /></QueryClientProvider>));
  await act(async () => new Promise(resolve => setTimeout(resolve, 20)));
}
async function input(label: string, value: string) {
  const field = host.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`)!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(field, value);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function save() {
  await act(async () => [...host.querySelectorAll("button")].find(button => button.textContent === "保存投资条件")!.click());
  await act(async () => new Promise(resolve => setTimeout(resolve, 20)));
}
it("keeps unknown conditions empty and saves an explicit budget only to the owning agent", async () => {
  await render();
  expect(host.querySelector('input[aria-label="最大可接受亏损（元）"]')?.getAttribute("value")).not.toBe("600");
  expect(host.querySelector('input[aria-label="保留现金（元）"]')).toBeNull();
  await input("投资预算（元）", "6000");
  await save();
  expect(updateFinancialWorkspace).toHaveBeenCalledWith("a", 2, {
    investmentProfile: { budgetCny: 6000, horizonMonths: null, maxLossCny: null, cashReserveCny: null, maxPositionPct: null, flexibleHorizon: null, market: "CN", holdingsStatus: "unknown" },
  });
  expect(host.textContent).toContain("已保存");
  await save();
  expect(updateFinancialWorkspace).toHaveBeenCalledTimes(2);
});
it("does not overwrite a profile changed in another window", async () => {
  await render();
  await input("投资预算（元）", "6000");
  vi.mocked(updateFinancialWorkspace).mockRejectedValueOnce(Object.assign(new Error("revision conflict"), { status: 409 }));
  vi.mocked(fetchFinancialWorkspace).mockResolvedValue({ ...state, revision: 3, investmentProfile: { budgetCny: 8000, market: "CN", holdingsStatus: "unknown" } });
  await save();
  expect(updateFinancialWorkspace).toHaveBeenCalledTimes(1);
  expect(host.textContent).toContain("已在其他页面修改");
  expect(host.textContent).not.toContain("已保存");
});
it("keeps entered values after a failed save and never reports success", async () => {
  await render();
  await input("投资预算（元）", "6000");
  vi.mocked(updateFinancialWorkspace).mockRejectedValueOnce(new Error("离线"));
  await save();
  expect(host.textContent).toContain("离线");
  expect(host.textContent).not.toContain("已保存");
  expect(host.querySelector<HTMLInputElement>('input[aria-label="投资预算（元）"]')?.value).toBe("6000");
});
