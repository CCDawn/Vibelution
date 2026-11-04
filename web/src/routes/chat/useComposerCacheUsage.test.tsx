// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { TokenUsageRollup } from "../../api/types";
import { composerCacheUsageQueryKey, useComposerCacheUsage } from "./useComposerCacheUsage";

const reads = vi.hoisted(() => ({ session: vi.fn(), assistant: vi.fn(), global: vi.fn() }));
vi.mock("../../api/usage", () => ({ fetchSessionUsageSummary: reads.session, fetchUsageSummary: reads.global }));
vi.mock("../../api/launcherAssistant", () => ({ getLauncherAssistantUsageSummary: reads.assistant }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

type Input = Parameters<typeof useComposerCacheUsage>[0];
const initial: Input = { sessionId: "session-a", agentId: "agent-a", source: "session", refreshMarker: "call-1:completed" };

function snapshot(cached = 25) {
  return {
    sessionTokenUsage: { inputTokens: 100, cachedInputTokens: cached, cacheObservedInputTokens: 100,
      callCount: 1, cacheObservedCallCount: 1, cacheUnobservedCallCount: 0,
      cacheUsageObserved: true, cacheUsageComplete: true } as TokenUsageRollup,
    lastTokenUsage: { source: "provider_usage", inputTokens: 100, cachedInputTokens: cached, cacheUsageObserved: true },
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}

let root: Root | undefined;
let client: QueryClient;
let latest: ReturnType<typeof useComposerCacheUsage>;

function Probe({ input }: { input: Input }) {
  latest = useComposerCacheUsage(input);
  return null;
}

async function render(input: Input = initial) {
  if (!root) root = createRoot(document.createElement("div"));
  await act(async () => root!.render(<QueryClientProvider client={client}><Probe input={input} /></QueryClientProvider>));
}

async function until(assertion: () => void) {
  await vi.waitFor(async () => {
    await act(async () => { await new Promise(done => setTimeout(done, 0)); });
    assertion();
  }, { timeout: 2000, interval: 10 });
}

beforeEach(() => {
  vi.resetAllMocks();
  client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity, gcTime: Infinity } } });
  reads.session.mockResolvedValue(snapshot());
  reads.assistant.mockResolvedValue({ ...snapshot(80), sessionId: initial.sessionId, agentId: initial.agentId });
});

afterEach(async () => {
  if (root) await act(async () => root!.unmount());
  root = undefined;
  client.clear();
  vi.useRealTimers();
});

describe("composer cache usage query ownership", () => {
  it("isolates session, agent, and native-versus-project caches", async () => {
    reads.session.mockImplementation(async (sid: string, aid: string) =>
      snapshot(sid === "session-b" ? 40 : aid === "agent-b" ? 60 : 25));
    await render();
    await until(() => expect(latest?.sessionPercent).toBe(25));
    await render({ ...initial, sessionId: "session-b" });
    await until(() => expect(latest?.sessionPercent).toBe(40));
    await render({ ...initial, agentId: "agent-b" });
    await until(() => expect(latest?.sessionPercent).toBe(60));
    await render({ ...initial, source: "assistant" });
    await until(() => expect(latest?.sessionPercent).toBe(80));
    await render();
    await until(() => expect(latest?.sessionPercent).toBe(25));
    expect(reads.session.mock.calls).toEqual([
      ["session-a", "agent-a"], ["session-b", "agent-a"], ["session-a", "agent-b"],
      ["session-a", "agent-a"],
    ]);
    expect(reads.assistant).toHaveBeenCalledExactlyOnceWith();
    expect(reads.global).not.toHaveBeenCalled();
    expect(client.getQueryCache().getAll()).toHaveLength(4);
  });

  it("refreshes a returning owner's changed usage despite the application cache freshness default", async () => {
    reads.session.mockResolvedValueOnce(snapshot(25)).mockResolvedValueOnce(snapshot(40)).mockResolvedValueOnce(snapshot(90));
    await render();
    await until(() => expect(latest?.sessionPercent).toBe(25));
    await render({ ...initial, sessionId: "session-b" });
    await until(() => expect(latest?.sessionPercent).toBe(40));
    await render({ ...initial, refreshMarker: "call-2:completed" });
    await until(() => expect(latest?.sessionPercent).toBe(90));
    expect(reads.session).toHaveBeenCalledTimes(3);
  });

  it("recovers a failed native read through the existing page refresh key with an unchanged marker", async () => {
    reads.assistant.mockRejectedValueOnce(new Error("temporary unavailable"))
      .mockResolvedValueOnce({ ...snapshot(80), sessionId: initial.sessionId, agentId: initial.agentId });
    await render({ ...initial, source: "assistant" });
    await until(() => expect(latest?.state).toBe("error"));
    await act(async () => { await client.invalidateQueries({
      queryKey: composerCacheUsageQueryKey("assistant", initial.agentId, initial.sessionId), exact: true,
    }); });
    await until(() => expect(latest?.sessionPercent).toBe(80));
    expect(reads.assistant).toHaveBeenCalledTimes(2);
    expect(reads.session).not.toHaveBeenCalled();
    expect(reads.global).not.toHaveBeenCalled();
  });

  it.each([{ enabled: false }, { sessionId: "" }, { agentId: "" }])(
    "does not read when disabled by the surface or missing identity (%j)", async overrides => {
      await render({ ...initial, ...overrides });
      expect(latest).toBeNull();
      expect(reads.session).not.toHaveBeenCalled();
      expect(reads.assistant).not.toHaveBeenCalled();
      expect(reads.global).not.toHaveBeenCalled();
    },
  );

  it.each([{ sessionId: "foreign-session" }, { agentId: "foreign-agent" }])(
    "rejects native identity mismatches without reading the main backend (%j)", async mismatch => {
      reads.assistant.mockResolvedValue({ ...snapshot(90), sessionId: initial.sessionId, agentId: initial.agentId, ...mismatch });
      await render({ ...initial, source: "assistant" });
      await until(() => expect(latest).toMatchObject({ state: "error", sessionPercent: null, lastCallPercent: null }));
      expect(reads.assistant).toHaveBeenCalledTimes(1);
      expect(reads.session).not.toHaveBeenCalled();
      expect(reads.global).not.toHaveBeenCalled();
    },
  );

  it("never publishes a slow old owner's result onto the current owner", async () => {
    const old = deferred<ReturnType<typeof snapshot>>();
    const current = deferred<ReturnType<typeof snapshot>>();
    reads.session.mockImplementation((sid: string) => sid === "session-a" ? old.promise : current.promise);
    await render();
    await render({ ...initial, sessionId: "session-b" });
    expect(latest).toMatchObject({ state: "loading", sessionPercent: null });
    await act(async () => current.resolve(snapshot(80)));
    await until(() => expect(latest?.sessionPercent).toBe(80));
    await act(async () => old.resolve(snapshot(10)));
    await until(() => expect(latest).toMatchObject({ state: "ready", sessionPercent: 80 }));
    expect(reads.session).toHaveBeenCalledTimes(2);
  });

  it("refetches on a changed detail marker even while the first read is pending", async () => {
    const old = deferred<ReturnType<typeof snapshot>>();
    const current = deferred<ReturnType<typeof snapshot>>();
    reads.session.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise);
    await render();
    expect(reads.session).toHaveBeenCalledTimes(1);
    await render({ ...initial, refreshMarker: "call-2:completed" });
    await until(() => expect(reads.session).toHaveBeenCalledTimes(2));
    await act(async () => current.resolve(snapshot(80)));
    await until(() => expect(latest?.sessionPercent).toBe(80));
    await act(async () => old.resolve(snapshot(10)));
    await until(() => expect(latest).toMatchObject({ state: "ready", sessionPercent: 80 }));
    expect(client.getQueryCache().getAll()).toHaveLength(1);
  });

  it.each(["session", "assistant"] as const)("restarts a pending %s read when returning to its owner", async source => {
    const old = deferred<ReturnType<typeof snapshot> & { sessionId: string; agentId: string }>();
    const read = source === "session" ? reads.session : reads.assistant;
    read.mockReturnValueOnce(old.promise)
      .mockResolvedValueOnce({ ...snapshot(40), sessionId: "session-b", agentId: initial.agentId })
      .mockResolvedValueOnce({ ...snapshot(80), sessionId: initial.sessionId, agentId: initial.agentId });
    await render({ ...initial, source });
    await render({ ...initial, source, sessionId: "session-b" });
    await until(() => expect(latest?.sessionPercent).toBe(40));
    await render({ ...initial, source, refreshMarker: "call-2:completed" });
    await until(() => expect(latest?.sessionPercent).toBe(80));
    await act(async () => old.resolve({ ...snapshot(25), sessionId: initial.sessionId, agentId: initial.agentId }));
    await until(() => expect(latest?.sessionPercent).toBe(80));
    expect(read).toHaveBeenCalledTimes(3);
  });

  it("refreshes the same key from existing detail updates without polling or writes", async () => {
    vi.useFakeTimers();
    await render();
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(latest?.sessionPercent).toBe(25);
    await act(async () => { await vi.advanceTimersByTimeAsync(120000); });
    expect(reads.session).toHaveBeenCalledTimes(1);
    await render({ ...initial, running: true });
    expect(latest?.updating).toBe(true);
    expect(reads.session).toHaveBeenCalledTimes(1);
    reads.session.mockResolvedValueOnce(snapshot(75));
    await render({ ...initial, refreshMarker: "call-2:completed" });
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(latest?.sessionPercent).toBe(75);
    expect(reads.session).toHaveBeenCalledTimes(2);
    expect(client.getQueryCache().getAll()).toHaveLength(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(120000); });
    expect(reads.session).toHaveBeenCalledTimes(2);
    expect(reads.assistant).not.toHaveBeenCalled();
    expect(reads.global).not.toHaveBeenCalled();
    expect(client.getMutationCache().getAll()).toHaveLength(0);
  });

  it.each(["session", "assistant"] as const)("keeps confirmed %s numbers on failure without fallback", async source => {
    const read = source === "session" ? reads.session : reads.assistant;
    const expected = source === "session" ? 25 : 80;
    await render({ ...initial, source });
    await until(() => expect(latest?.sessionPercent).toBe(expected));
    read.mockRejectedValueOnce(new Error("USAGE_TRANSPORT_UNAVAILABLE"));
    await render({ ...initial, source, refreshMarker: "call-2:completed" });
    await until(() => expect(latest).toMatchObject({ state: "error", sessionPercent: expected, lastCallPercent: expected }));
    expect(read).toHaveBeenCalledTimes(2);
    expect(source === "session" ? reads.assistant : reads.session).not.toHaveBeenCalled();
    expect(reads.global).not.toHaveBeenCalled();
  });
});
