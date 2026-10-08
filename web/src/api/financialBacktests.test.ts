import { expect, it, vi } from "vitest";
import { fetchJson } from "./client";
import { fetchAIBacktests, resumeAIBacktest, startAIBacktest, stopAIBacktest } from "./financialBacktests";
vi.mock("./client", () => ({ fetchJson: vi.fn().mockResolvedValue({}) }));
it("keeps owner/run identifiers escaped and reuses structured idempotent commands", async () => {
  await startAIBacktest("agent/a", "preview", "request");
  expect(fetchJson).toHaveBeenLastCalledWith("/api/financial-backtests/agent%2Fa/runs", expect.objectContaining({ method: "POST", body: JSON.stringify({ previewId: "preview", clientRequestId: "request" }) }));
  await stopAIBacktest("a", "run/1"); expect(fetchJson).toHaveBeenLastCalledWith("/api/financial-backtests/a/runs/run%2F1/stop", expect.objectContaining({ method: "POST" }));
  const confirmation = { retryUnknownDecisionDate: "2026-09-01", confirmPossibleDuplicateCharge: true };
  await resumeAIBacktest("a", "run/1", confirmation); expect(fetchJson).toHaveBeenLastCalledWith("/api/financial-backtests/a/runs/run%2F1/resume", expect.objectContaining({ body: JSON.stringify(confirmation) }));
  const controller = new AbortController(); await fetchAIBacktests("a", "older", controller.signal);
  expect(fetchJson).toHaveBeenLastCalledWith("/api/financial-backtests/a/runs?limit=20&cursor=older", { signal: controller.signal });
});
