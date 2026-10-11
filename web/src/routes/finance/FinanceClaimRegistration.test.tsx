// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FinanceClaimRegistration } from "./FinanceClaimRegistration";
import * as api from "../../api/financialEvaluation";

vi.mock("../../api/financialEvaluation", () => ({ createFinancialClaim: vi.fn(), financialEvaluationKeys: { claims: (id: string) => ["finance", "validation", id] } }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root, node: HTMLDivElement, client: QueryClient;
beforeEach(() => {
  vi.resetAllMocks();
  node = document.createElement("div"); document.body.append(node); root = createRoot(node);
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
});
afterEach(async () => { await act(async () => root.unmount()); client.clear(); node.remove(); });
function button(text: string) { return [...document.querySelectorAll("button")].find(item => item.textContent === text)!; }
async function click(text: string) { await act(async () => { button(text).click(); }); }
async function fill(label: string, value: string) {
  const field = document.querySelector(`[aria-label="${label}"]`) as HTMLInputElement | HTMLTextAreaElement;
  const prototype = field instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  await act(async () => {
    Object.getOwnPropertyDescriptor(prototype, "value")!.set!.call(field, value);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function open() {
  await act(async () => root.render(<QueryClientProvider client={client}><FinanceClaimRegistration agentId="a" sessionId="session" turnId="turn" zh initialSymbol="sh600519" /></QueryClientProvider>));
  await click("登记到期核验");
  await fill("核验截止日", "2026-12-31"); await fill("核验判断", "现金流改善");
}
it.each(["", "-1", "101"])("explains invalid threshold %s and prevents silent save", async value => {
  await open(); await fill("核验涨跌阈值", value);
  expect(document.body.textContent).toContain("涨跌阈值须为 0–100 的数字");
  expect(document.querySelector('[aria-label="核验涨跌阈值"]')?.getAttribute("aria-invalid")).toBe("true");
  expect(button("保存判据").disabled).toBe(true);
  await click("保存判据"); expect(api.createFinancialClaim).not.toHaveBeenCalled();
  await fill("核验涨跌阈值", "5");
  expect(document.body.textContent).not.toContain("涨跌阈值须为 0–100 的数字");
  expect(button("保存判据").disabled).toBe(false);
  await click("保存判据");
  expect(api.createFinancialClaim).toHaveBeenCalledWith("a", expect.objectContaining({ thresholdPct: 5, sessionId: "session", turnId: "turn" }));
});
it("keeps the same request identity after a rejected save with unchanged fields", async () => {
  vi.mocked(api.createFinancialClaim).mockRejectedValueOnce(new Error("暂时无法保存"));
  await open(); await click("保存判据");
  expect(document.body.textContent).toContain("暂时无法保存");
  await click("保存判据");
  const calls = vi.mocked(api.createFinancialClaim).mock.calls;
  expect(calls).toHaveLength(2);
  expect(calls[1][1].clientRequestId).toBe(calls[0][1].clientRequestId);
});
it.each(["0", "100"])("accepts the supported threshold boundary %s", async value => {
  await open(); await fill("核验涨跌阈值", value);
  expect(button("保存判据").disabled).toBe(false);
  await click("保存判据");
  expect(api.createFinancialClaim).toHaveBeenCalledWith("a", expect.objectContaining({ thresholdPct: Number(value) }));
});
