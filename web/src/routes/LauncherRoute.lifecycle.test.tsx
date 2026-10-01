/** @vitest-environment happy-dom */
import React, { act, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { LauncherBranchInstance } from "../api/launcher";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const apiMocks = vi.hoisted(() => ({
  getLauncherBranchInstances: vi.fn(),
  getLauncherStatus: vi.fn(),
  isLauncherControlPlaneNotReady: vi.fn(() => false),
  requestBranchInstanceLifecycle: vi.fn(),
  updateLauncherStartupSettings: vi.fn(),
  requestWorkbenchLifecycle: vi.fn(),
}));

vi.mock("../api/launcher", () => ({
  getLauncherBranchInstances: apiMocks.getLauncherBranchInstances,
  getLauncherStatus: apiMocks.getLauncherStatus,
  isLauncherControlPlaneNotReady: apiMocks.isLauncherControlPlaneNotReady,
  requestBranchInstanceLifecycle: apiMocks.requestBranchInstanceLifecycle,
  updateLauncherStartupSettings: apiMocks.updateLauncherStartupSettings,
}));

vi.mock("../app/useWorkbenchLifecycleActions", () => ({
  useWorkbenchLifecycleActions: () => ({ request: apiMocks.requestWorkbenchLifecycle }),
}));

vi.mock("../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: "zh" }) }));

vi.mock("../components/vui", () => ({
  VButton: ({ children, onPress }: { children?: ReactNode; onPress?: () => void }) => (
    <button type="button" onClick={onPress}>{children}</button>
  ),
  VConfirmDialog: () => null,
  VDenseOpsPage: ({ children }: { children?: ReactNode }) => <main>{children}</main>,
  VStateSurface: ({ title }: { title?: ReactNode }) => <p>{title}</p>,
}));

vi.mock("./LauncherStartupSettingsPanel", () => ({ LauncherStartupSettingsPanel: () => null }));

vi.mock("./LauncherBranchInstancesPanel", () => ({
  LauncherBranchInstancesPanel: (props: {
    items: LauncherBranchInstance[];
    pendingOperation?: Record<string, { operation: string }>;
    rowFeedback?: { message: string } | null;
    onLifecycle: (id: string, operation: "start" | "stop" | "force-stop") => void;
  }) => {
    const item = props.items[0];
    if (!item) return <div data-testid="branch-panel-loading">Loading</div>;
    return (
      <section>
        <button type="button" onClick={() => props.onLifecycle(item.id, "start")}>请求启动</button>
        <button type="button" onClick={() => props.onLifecycle(item.id, "stop")}>请求停止</button>
        <span data-testid="pending-operation">{props.pendingOperation?.[item.id]?.operation ?? "none"}</span>
        <span data-testid="row-feedback">{props.rowFeedback?.message ?? ""}</span>
      </section>
    );
  },
}));

import { LauncherRoute } from "./LauncherRoute";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function buildingInstance(): LauncherBranchInstance {
  return {
    id: "worktree:build-race",
    kind: "worktree",
    branch: "codex/build-race",
    path: "C:/repo/.worktrees/build-race",
    displayPath: ".worktrees/build-race",
    head: "abc123",
    current: false,
    legacy: false,
    dirty: false,
    checkedOut: true,
    alive: false,
    observedState: "building",
    port: 0,
    pids: { backend: 0, window: 0, manager: 0 },
    promotable: true,
    shortName: "build-race",
    workbenchTitle: "build-race 台",
    runtime: {
      lifecycleState: "building",
      desiredState: "running",
      observedState: "building",
      phase: "building",
      backend: { alive: false, healthy: false, listening: false, port: 0, portReserved: false, portConflict: false, pid: 0 },
      frontend: { mode: "bundled_static_dist", ready: false },
      window: { open: false, pid: 0, title: "build-race 台", titleObserved: false },
    },
    startable: true,
    startBlockReason: "",
  };
}

function branchInstances() {
  return {
    schemaVersion: 1,
    integrationRoot: "C:/repo",
    branchPool: "C:/repo/.worktrees",
    currentId: "main",
    items: [buildingInstance()],
  };
}

function button(label: string): HTMLButtonElement {
  const found = [...document.querySelectorAll<HTMLButtonElement>("button")]
    .find((candidate) => candidate.textContent?.trim() === label);
  if (!found) throw new Error(`button not found: ${label}`);
  return found;
}

async function click(label: string) {
  await act(async () => {
    button(label).click();
    await Promise.resolve();
  });
}

async function resolveAndFlush<T>(request: ReturnType<typeof deferred<T>>, value: T) {
  await act(async () => {
    request.resolve(value);
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function rejectAndFlush<T>(request: ReturnType<typeof deferred<T>>, error: unknown) {
  await act(async () => {
    request.reject(error);
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function waitFor(predicate: () => boolean, label: string, timeoutMs = 3000) {
  const deadline = Date.now() + timeoutMs;
  while (!predicate()) {
    if (Date.now() > deadline) throw new Error(`waitFor timeout: ${label}`);
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
  }
}

let host: HTMLDivElement;
let root: Root;
let queryClient: QueryClient;

async function renderRoute() {
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false }, mutations: { retry: false } },
  });
  const router = createMemoryRouter(
    [{ path: "/launcher", element: <LauncherRoute /> }],
    { initialEntries: ["/launcher"] },
  );
  await act(async () => {
    root.render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
  });
  await waitFor(() => Boolean(document.querySelector('[data-testid="pending-operation"]')), "branch panel mounts");
}

async function beginOverlappingLifecycleRequests(
  start: ReturnType<typeof deferred<unknown>>,
  stop: ReturnType<typeof deferred<unknown>>,
) {
  apiMocks.requestBranchInstanceLifecycle.mockImplementation((_id: string, operation: string) => (
    operation === "start" ? start.promise : stop.promise
  ));
  await renderRoute();
  await click("请求启动");
  await waitFor(() => apiMocks.requestBranchInstanceLifecycle.mock.calls.length === 1, "start request begins");
  await click("请求停止");
  await waitFor(() => apiMocks.requestBranchInstanceLifecycle.mock.calls.length === 2, "stop supersedes start");
  expect(document.querySelector('[data-testid="pending-operation"]')?.textContent).toBe("stop");
}

beforeEach(() => {
  apiMocks.getLauncherBranchInstances.mockReset().mockResolvedValue(branchInstances());
  apiMocks.getLauncherStatus.mockReset().mockResolvedValue({});
  apiMocks.isLauncherControlPlaneNotReady.mockReset().mockReturnValue(false);
  apiMocks.requestBranchInstanceLifecycle.mockReset();
  apiMocks.updateLauncherStartupSettings.mockReset();
  apiMocks.requestWorkbenchLifecycle.mockReset();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root?.unmount());
  queryClient?.clear();
  host?.remove();
});

describe("LauncherRoute lifecycle intent ordering", () => {
  it("keeps the newer Stop intent and feedback when an older Start is rejected", async () => {
    const start = deferred<unknown>();
    const stop = deferred<unknown>();
    await beginOverlappingLifecycleRequests(start, stop);

    await resolveAndFlush(start, { accepted: false, message: "旧启动请求被拒绝" });
    await waitFor(() => apiMocks.getLauncherBranchInstances.mock.calls.length > 1, "stale start response refreshes state");

    expect(document.querySelector('[data-testid="pending-operation"]')?.textContent).toBe("stop");
    expect(document.querySelector('[data-testid="row-feedback"]')?.textContent).toBe("");
    expect(document.body.textContent).not.toContain("旧启动请求被拒绝");

    await resolveAndFlush(stop, { accepted: true, message: "停止已提交" });
  });

  it("keeps the newer Stop intent and feedback when an older Start throws", async () => {
    const start = deferred<unknown>();
    const stop = deferred<unknown>();
    await beginOverlappingLifecycleRequests(start, stop);

    await rejectAndFlush(start, new Error("旧启动请求异常"));
    await waitFor(() => apiMocks.getLauncherBranchInstances.mock.calls.length > 1, "stale start error refreshes state");

    expect(document.querySelector('[data-testid="pending-operation"]')?.textContent).toBe("stop");
    expect(document.querySelector('[data-testid="row-feedback"]')?.textContent).toBe("");
    expect(document.body.textContent).not.toContain("旧启动请求异常");

    await resolveAndFlush(stop, { accepted: true, message: "停止已提交" });
  });
});
