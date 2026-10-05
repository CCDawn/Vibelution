// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../app/pollingPolicy", () => ({
  resolvePollingInterval: () => false,
  usePageVisibility: () => true,
}));

vi.mock("../api/agentPerception", () => ({
  cancelAgentPerceptionRun: vi.fn(),
  fetchAgentPerceptionConfiguration: vi.fn(),
  fetchAgentPerceptionRuntime: vi.fn(),
  saveAgentPerceptionConfiguration: vi.fn(),
}));

import {
  fetchAgentPerceptionConfiguration,
  fetchAgentPerceptionRuntime,
  saveAgentPerceptionConfiguration,
} from "../api/agentPerception";
import { AgentPerceptionPane } from "./AgentPerceptionPane";
import { defaultAgentPerceptionPolicy } from "./agentPerception/agentPerceptionDraft";
import { agentPerceptionQueryKeys } from "./agentPerception/queryKeys";
import type { AgentPerceptionConfiguration, AgentPerceptionRuntime } from "./agentPerception/types";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function configuration(agentId: string): AgentPerceptionConfiguration {
  return {
    schemaVersion: 1,
    agentId,
    agentUpdatedAt: `${agentId}-revision-1`,
    configurationRevision: 1,
    configured: true,
    policy: defaultAgentPerceptionPolicy(),
    sourceDecisions: [],
    policyFingerprint: `${agentId}-policy-1`,
    availableScopes: { teams: [], knowledgeBases: [] },
  };
}

function runtime(agentId: string): AgentPerceptionRuntime {
  return {
    schemaVersion: 1,
    agentId,
    enabled: false,
    status: "disabled",
    nextRunAt: null,
    readableSources: [],
    activeRun: null,
    lastRun: null,
    lastActivity: null,
    dailyBudget: { date: "2026-10-05", used: 0, limit: 4, remaining: 4 },
    caps: { maxCallsPerRun: 8, maxInputTokensPerRun: 16_000, maxResultChars: 12_000, maxConcurrent: 1 },
    cancelAvailable: false,
    notifications: { unreadCount: 0, totalCount: 0, suppressedCount: 0, items: [] },
    knowledgeScan: { basesScanned: 0, cursorCount: 0, pendingCount: 0 },
    updatedAt: "2026-10-05T00:00:00Z",
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

let root: Root | null = null;
let host: HTMLDivElement | null = null;
let queryClient: QueryClient;

function mount(agentId: string) {
  if (!host) {
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
  }
  act(() => {
    root?.render(
      <QueryClientProvider client={queryClient}>
        <AgentPerceptionPane agentId={agentId} lang="en" onOpenSession={() => undefined} />
      </QueryClientProvider>,
    );
  });
}

async function flush() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function waitForSwitch(expectedChecked: boolean) {
  await vi.waitFor(async () => {
    await flush();
    expect(enabledSwitch().checked).toBe(expectedChecked);
  }, { timeout: 1_000, interval: 20 });
}

function enabledSwitch() {
  const control = host?.querySelector<HTMLInputElement>('[role="switch"]');
  if (!control) {
    throw new Error(`Perception switch is not rendered; text=${host?.textContent ?? ""}; configurationCalls=${vi.mocked(fetchAgentPerceptionConfiguration).mock.calls.length}`);
  }
  return control;
}

function clickSave() {
  const button = host?.querySelector<HTMLButtonElement>('[data-testid="agent-perception-save"]');
  if (!button || button.disabled) throw new Error("Perception save button is unavailable");
  act(() => button.click());
}

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  host?.remove();
  host = null;
  queryClient.clear();
});

beforeEach(() => {
  vi.clearAllMocks();
  queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Number.POSITIVE_INFINITY },
      mutations: { retry: false },
    },
  });
  vi.mocked(fetchAgentPerceptionConfiguration).mockImplementation(async (agentId) => configuration(agentId));
  vi.mocked(fetchAgentPerceptionRuntime).mockImplementation(async (agentId) => runtime(agentId));
});

describe("AgentPerceptionPane mutation isolation", () => {
  it("keeps an Agent A save scoped to A when the pane switches to B before it resolves", async () => {
    const saveA = deferred<AgentPerceptionConfiguration>();
    const cachedB = configuration("agent-b");
    cachedB.policyFingerprint = "agent-b-cache-sentinel";
    cachedB.agentUpdatedAt = "agent-b-cache-sentinel";
    queryClient.setQueryData(agentPerceptionQueryKeys.configuration("agent-b"), cachedB);
    queryClient.setQueryData(agentPerceptionQueryKeys.runtime("agent-b"), runtime("agent-b"));
    vi.mocked(saveAgentPerceptionConfiguration).mockReturnValue(saveA.promise);

    mount("agent-a");
    await waitForSwitch(false);
    act(() => enabledSwitch().click());
    await flush();
    expect(enabledSwitch().checked).toBe(true);
    clickSave();
    await flush();

    expect(saveAgentPerceptionConfiguration).toHaveBeenCalledWith("agent-a", expect.objectContaining({ enabled: true }), "agent-a-revision-1");
    expect(host?.querySelector('[data-testid="agent-perception-save"]')?.getAttribute("aria-busy")).toBe("true");

    mount("agent-b");
    await waitForSwitch(false);
    act(() => enabledSwitch().click());
    await flush();
    const saveB = host?.querySelector<HTMLButtonElement>('[data-testid="agent-perception-save"]');
    expect(saveB?.disabled).toBe(false);
    expect(saveB?.getAttribute("aria-busy")).not.toBe("true");

    const savedA = configuration("agent-a");
    savedA.agentUpdatedAt = "agent-a-revision-2";
    savedA.policyFingerprint = "agent-a-policy-2";
    savedA.policy.enabled = true;
    await act(async () => {
      saveA.resolve(savedA);
      await saveA.promise;
    });
    await flush();

    expect(queryClient.getQueryData(agentPerceptionQueryKeys.configuration("agent-a"))).toEqual(savedA);
    expect(queryClient.getQueryData(agentPerceptionQueryKeys.configuration("agent-b"))).toEqual(cachedB);
    expect(enabledSwitch().checked).toBe(true);
    expect(host?.textContent).not.toContain("agent-a-revision-2");
  });

  it("does not show Agent A save failures as Agent B errors", async () => {
    const saveA = deferred<AgentPerceptionConfiguration>();
    vi.mocked(saveAgentPerceptionConfiguration).mockReturnValue(saveA.promise);

    mount("agent-a");
    await waitForSwitch(false);
    act(() => enabledSwitch().click());
    await flush();
    clickSave();
    await flush();

    mount("agent-b");
    await flush();
    await act(async () => {
      saveA.reject(new Error("Agent A save failed"));
      await saveA.promise.catch(() => undefined);
    });
    await flush();

    expect(host?.textContent).not.toContain("Agent A save failed");
    const saveB = host?.querySelector<HTMLButtonElement>('[data-testid="agent-perception-save"]');
    expect(saveB?.getAttribute("aria-busy")).not.toBe("true");
  });
});
