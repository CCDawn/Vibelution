/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../api/queryKeys";
import { LauncherShell } from "./LauncherShell";

type BranchInstancesPayload = {
  currentId: string;
  items: Array<{ id: string; current?: boolean }>;
};

const launcherBridge = vi.hoisted(() => {
  type Listener = (snapshot: unknown) => void;
  const listeners = new Set<Listener>();
  return {
    listeners,
    getLauncherBranchInstances: vi.fn(),
    getLauncherState: vi.fn(),
    hasLauncherStateBridge: vi.fn(),
    onLauncherStateChanged: vi.fn((listener: Listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    }),
  };
});

vi.mock("../api/launcher", () => launcherBridge);
vi.mock("react-router-dom", () => ({ Outlet: () => null }));
vi.mock("./browserTelemetry", () => ({
  collectBrowserPageSnapshot: () => ({}),
  postBrowserTelemetry: vi.fn(),
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function BranchInstancesConsumer() {
  const query = useQuery<BranchInstancesPayload>({
    queryKey: queryKeys.launcherBranchInstances(),
    queryFn: () => launcherBridge.getLauncherBranchInstances(),
  });

  return <output data-testid="branch-items">{query.data?.items.map((item) => item.id).join(",")}</output>;
}

describe("LauncherShell launcher state synchronization", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  beforeEach(() => {
    launcherBridge.listeners.clear();
    launcherBridge.getLauncherBranchInstances.mockReset();
    launcherBridge.getLauncherState.mockReset();
    launcherBridge.getLauncherState.mockReturnValue(new Promise(() => undefined));
    launcherBridge.hasLauncherStateBridge.mockReturnValue(true);
    launcherBridge.onLauncherStateChanged.mockClear();
  });

  afterEach(async () => {
    if (root) {
      await act(async () => {
        root?.unmount();
      });
    }
    container?.remove();
    root = null;
    container = null;
    launcherBridge.listeners.clear();
  });

  it("refetches the shared branch query when a launcher state event arrives", async () => {
    launcherBridge.getLauncherBranchInstances
      .mockResolvedValueOnce({ currentId: "main", items: [] })
      .mockResolvedValue({ currentId: "main", items: [{ id: "branch-1", current: false }] });

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => {
      root?.render(
        <QueryClientProvider client={queryClient}>
          <LauncherShell />
          <BranchInstancesConsumer />
        </QueryClientProvider>,
      );
    });

    await vi.waitFor(() => expect(launcherBridge.getLauncherBranchInstances).toHaveBeenCalledTimes(1));
    expect(container.querySelector("[data-testid='branch-items']")?.textContent).toBe("");
    expect(launcherBridge.onLauncherStateChanged).toHaveBeenCalledTimes(1);
    expect(launcherBridge.listeners.size).toBe(1);

    await act(async () => {
      for (const listener of launcherBridge.listeners) {
        listener({ revision: 2 });
      }
      await Promise.resolve();
      await Promise.resolve();
    });

    await vi.waitFor(() => expect(container.querySelector("[data-testid='branch-items']")?.textContent).toContain("branch-1"));
    expect(launcherBridge.getLauncherBranchInstances).toHaveBeenCalledTimes(2);
  });
});
