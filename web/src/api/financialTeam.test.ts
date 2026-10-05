import { beforeEach, describe, expect, it, vi } from "vitest";

const fetchJson = vi.hoisted(() => vi.fn());
vi.mock("./client", () => ({ fetchJson }));

import {
  createFinancialTeamRun,
  fetchFinancialTeam,
  fetchFinancialTeamRun,
  fetchFinancialTeamRuns,
  financialTeamKeys,
  provisionFinancialTeam,
  recordFinancialTeamTurn,
  submitFinancialTeamPrimaryRole,
  submitFinancialTeamDebate,
  submitFinancialTeamSynthesis,
} from "./financialTeam";

describe("financial team API", () => {
  beforeEach(() => fetchJson.mockReset());

  it("keeps team and run reads behind the financial-team domain transport", async () => {
    fetchJson.mockResolvedValueOnce({ status: "ready" }).mockResolvedValueOnce({ runs: [] }).mockResolvedValueOnce({ runId: "run/1" });
    await fetchFinancialTeam("agent/1");
    await fetchFinancialTeamRuns("agent/1", { limit: 12 });
    await fetchFinancialTeamRun("agent/1", "run/1");
    expect(fetchJson).toHaveBeenNthCalledWith(1, "/api/financial-team/agent%2F1", { signal: undefined });
    expect(fetchJson).toHaveBeenNthCalledWith(2, "/api/financial-team/agent%2F1/runs?limit=12", { signal: undefined });
    expect(fetchJson).toHaveBeenNthCalledWith(3, "/api/financial-team/agent%2F1/runs/run%2F1", { signal: undefined });
    expect(financialTeamKeys.run("agent/1", "run/1")).toEqual(["financial-team", "agent/1", "run", "run/1"]);
  });

  it("uses explicit setup, stable native turn references, and server-checked synthesis", async () => {
    const run = { runId: "run-1" };
    fetchJson.mockResolvedValue(run);
    await provisionFinancialTeam("agent-1");
    await createFinancialTeamRun("agent-1", { symbol: "sh600519", periodDays: 30, researchDate: "2026-10-05", depth: "detailed" }, "request-key-20261005-0001");
    await recordFinancialTeamTurn("agent-1", "run-1", "market", {
      sessionId: "session-market",
      clientSubmissionId: "submission-market",
      turnId: "turn-market",
    });
    await submitFinancialTeamSynthesis("agent-1", "run-1");
    await submitFinancialTeamDebate("agent-1", "run-1");
    expect(fetchJson).toHaveBeenNthCalledWith(1, "/api/financial-team/agent-1/provision", { method: "POST" });
    expect(fetchJson).toHaveBeenNthCalledWith(2, "/api/financial-team/agent-1/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": "request-key-20261005-0001" },
      body: JSON.stringify({ symbol: "sh600519", periodDays: 30, researchDate: "2026-10-05", depth: "detailed" }),
    });
    expect(fetchJson).toHaveBeenNthCalledWith(3, "/api/financial-team/agent-1/runs/run-1/turns/market", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionId: "session-market", clientSubmissionId: "submission-market", turnId: "turn-market" }),
    });
    expect(fetchJson).toHaveBeenNthCalledWith(4, "/api/financial-team/agent-1/runs/run-1/synthesis", { method: "POST" });
    expect(fetchJson).toHaveBeenNthCalledWith(5, "/api/financial-team/agent-1/runs/run-1/debate", { method: "POST" });
  });

  it("submits each primary analyst role through the guarded Team API", async () => {
    fetchJson.mockResolvedValue({ runId: "run-1" });
    await submitFinancialTeamPrimaryRole("agent/1", "run/1", "market");
    expect(fetchJson).toHaveBeenCalledWith(
      "/api/financial-team/agent%2F1/runs/run%2F1/analysts/market/submit",
      { method: "POST" },
    );
  });
});
