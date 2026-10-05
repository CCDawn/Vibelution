import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchJsonMock } = vi.hoisted(() => ({ fetchJsonMock: vi.fn() }));
vi.mock("./client", () => ({ fetchJson: fetchJsonMock }));

import {
  cancelAgentPerceptionRun,
  fetchAgentPerceptionConfiguration,
  fetchAgentPerceptionRuntime,
  saveAgentPerceptionConfiguration,
} from "./agentPerception";

describe("Agent perception API client", () => {
  beforeEach(() => fetchJsonMock.mockReset());

  it("reads the selected Agent policy with cancellation support", async () => {
    const signal = new AbortController().signal;
    fetchJsonMock.mockResolvedValueOnce({ agentId: "agent/a" });

    await fetchAgentPerceptionConfiguration("agent/a", { signal });

    expect(fetchJsonMock).toHaveBeenCalledWith(
      "/api/agents/agent%2Fa/perception/configuration",
      { signal },
    );
  });

  it("saves the complete policy against the Agent configuration revision", async () => {
    const policy = { schemaVersion: 1, enabled: false } as never;
    fetchJsonMock.mockResolvedValueOnce({ agentId: "agent-1" });

    await saveAgentPerceptionConfiguration("agent-1", policy, "updated-at-1");

    expect(fetchJsonMock).toHaveBeenCalledWith(
      "/api/agents/agent-1/perception/configuration",
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ policy, expectedAgentUpdatedAt: "updated-at-1" }),
      },
    );
  });

  it("reads the runtime projection separately from policy decisions", async () => {
    fetchJsonMock.mockResolvedValueOnce({ agentId: "agent-1" });

    await fetchAgentPerceptionRuntime("agent-1");

    expect(fetchJsonMock).toHaveBeenCalledWith(
      "/api/agents/agent-1/perception/runtime",
      { signal: undefined },
    );
  });

  it("cancels the active run through the runtime command endpoint", async () => {
    fetchJsonMock.mockResolvedValueOnce({ agentId: "agent-1", runId: "run-1" });

    await cancelAgentPerceptionRun("agent-1", "run-1");

    expect(fetchJsonMock).toHaveBeenCalledWith(
      "/api/agents/agent-1/perception/cancel",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ runId: "run-1" }),
      },
    );
  });
});