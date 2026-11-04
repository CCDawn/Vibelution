import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchSessionUsageSummary, fetchUsageSummary } from "./usage";

import apiSource from "./usage.ts?raw";
import routeSource from "../routes/UsageRoute.tsx?raw";

const transport = vi.hoisted(() => vi.fn());
vi.mock("./client", () => ({ fetchJson: transport }));
afterEach(() => vi.resetAllMocks());

describe("session usage summary identity", () => {
  it("sends an explicit session scope and safely encodes both owners", async () => {
    const sessionId = "session/a &?中文";
    const agentId = "agent/b #+中文";
    const expected = { scope: "session_agent", filters: { sessionId, agentId } };
    transport.mockResolvedValueOnce(expected);
    await expect(fetchSessionUsageSummary(sessionId, agentId)).resolves.toBe(expected);
    expect(transport).toHaveBeenCalledTimes(1);
    const [path, options] = transport.mock.calls[0];
    const url = new URL(path, "http://127.0.0.1");
    expect(url.pathname).toBe("/api/usage/summary");
    expect([...url.searchParams.entries()]).toEqual([["scope", "session_agent"], ["sessionId", sessionId], ["agentId", agentId]]);
    expect(url.hash).toBe("");
    expect(options?.method ?? "GET").toBe("GET");
    expect(options?.body).toBeUndefined();
  });

  it.each([["", "agent-a"], ["session-a", ""], ["", ""]])(
    "rejects empty owners before transport (%j, %j)", async (sessionId, agentId) => {
      await expect(fetchSessionUsageSummary(sessionId, agentId)).rejects.toThrow("SESSION_USAGE_IDENTITY_REQUIRED");
      expect(transport).not.toHaveBeenCalled();
    },
  );

  it.each([
    { scope: "session", filters: { sessionId: "session-a", agentId: "agent-a" } },
    { scope: "global", filters: { sessionId: "session-a", agentId: "agent-a" } },
    { scope: "session_agent", filters: { sessionId: "foreign", agentId: "agent-a" } },
    { scope: "session_agent", filters: { sessionId: "session-a", agentId: "foreign" } },
    { scope: "session_agent", filters: { sessionId: "session-a" } },
    { scope: "session_agent" },
  ])("rejects mismatched or missing response ownership (%j)", async response => {
    transport.mockResolvedValueOnce(response);
    await expect(fetchSessionUsageSummary("session-a", "agent-a")).rejects.toThrow("SESSION_USAGE_IDENTITY_MISMATCH");
    expect(transport).toHaveBeenCalledTimes(1);
  });

  it("keeps the existing global summary request unchanged", async () => {
    const expected = { scope: "global", globalTokenUsage: {} };
    transport.mockResolvedValueOnce(expected);
    await expect(fetchUsageSummary()).resolves.toBe(expected);
    expect(transport).toHaveBeenCalledExactlyOnceWith("/api/usage/summary");
  });

  it("propagates a transport failure once without falling back to global usage", async () => {
    const failure = new Error("USAGE_TRANSPORT_UNAVAILABLE");
    transport.mockRejectedValueOnce(failure);
    await expect(fetchSessionUsageSummary("session-a", "agent-a")).rejects.toBe(failure);
    expect(transport).toHaveBeenCalledTimes(1);
  });
});

describe("usage catalog API", () => {
  it("owns usage summary transport", () => {
    expect(apiSource).toContain("export function fetchUsageSummary");
    expect(apiSource).toContain('"/api/usage/summary"');
  });

  it("keeps UsageRoute free of usage JSON paths", () => {
    expect(routeSource).toContain("fetchUsageSummary(");
    expect(routeSource).not.toContain("/api/usage/");
  });
});
