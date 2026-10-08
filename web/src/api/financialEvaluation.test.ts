import { expect, it, vi } from "vitest";
import { fetchJson } from "./client";
import { checkFinancialClaim, createFinancialClaim, fetchFinancialReflection, runFinancialBacktest, saveFinancialLesson } from "./financialEvaluation";

vi.mock("./client", () => ({ fetchJson: vi.fn().mockResolvedValue({}) }));
it("uses the private report owner and structured exact-report payload", async () => {
  const payload = { clientRequestId: "request", sessionId: "session", turnId: "turn", symbol: "sz000001", dueDate: "2026-10-10", direction: "up" as const, thresholdPct: 2, claimText: "原报告判断" };
  await createFinancialClaim("agent/a", payload);
  expect(fetchJson).toHaveBeenLastCalledWith("/api/financial-reports/agent%2Fa/validations", expect.objectContaining({ method: "POST", body: JSON.stringify(payload) }));
  await checkFinancialClaim("agent/a", "claim/1");
  expect(fetchJson).toHaveBeenLastCalledWith("/api/financial-reports/agent%2Fa/validations/claim%2F1/check", expect.objectContaining({ method: "POST" }));
  await saveFinancialLesson("a", "c", "核实数据时间", "request-2");
  expect(fetchJson).toHaveBeenLastCalledWith("/api/financial-reports/a/validations/c/lesson", expect.objectContaining({ body: JSON.stringify({ text: "核实数据时间", clientRequestId: "request-2" }) }));
  await fetchFinancialReflection("a", "sz000001", "2026-09-01");
  expect(fetchJson).toHaveBeenLastCalledWith("/api/financial-reports/a/reflection-context?symbol=sz000001&analysisDate=2026-09-01", expect.any(Object));
  const params = { symbol: "sz000001", startDate: "2026-08-01", endDate: "2026-09-01", window: 20, commissionBps: 3, slippageBps: 5 };
  await runFinancialBacktest("a", params);
  expect(fetchJson).toHaveBeenLastCalledWith("/api/financial-reports/a/backtest", expect.objectContaining({ body: JSON.stringify(params) }));
});
