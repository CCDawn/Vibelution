import { afterEach, expect, it, vi } from "vitest";
import { bulkPurgeAgents, bulkUpdateAgentConfig, bulkUpdateAgentPromptTemplate, purgeArchivedAgent, resetAgent } from "./agents";
import { resetControlTokenForTests, seedControlTokenForTests } from "./client";

afterEach(() => {
  vi.useRealTimers(); vi.unstubAllGlobals(); resetControlTokenForTests();
});

it.each([
  ["bulk config", () => bulkUpdateAgentConfig({ agentIds: ["a", "b"], applyFields: ["displayName"], patch: { displayName: "test" } })],
  ["bulk template", () => bulkUpdateAgentPromptTemplate({ agentIds: ["a", "b"], promptTemplateId: "test" })],
  ["bulk purge", () => bulkPurgeAgents(["a", "b"])],
  ["single purge", () => purgeArchivedAgent("a")],
  ["reset", () => resetAgent("a", {})],
] as const)("%s stops waiting on a hung response without retrying the write", async (_name, write) => {
  vi.useFakeTimers(); seedControlTokenForTests();
  const fetchMock = vi.fn(() => new Promise<Response>(() => {}));
  vi.stubGlobal("fetch", fetchMock);
  let settled = false, outcome: unknown;
  void write().then(value => { settled = true; outcome = value; }, error => { settled = true; outcome = error; });
  await vi.advanceTimersByTimeAsync(60_001);
  expect(settled).toBe(true);
  expect(outcome).toBeInstanceOf(Error);
  expect((outcome as Error).message).toContain("尚未确认");
  expect(fetchMock).toHaveBeenCalledTimes(1);
});
