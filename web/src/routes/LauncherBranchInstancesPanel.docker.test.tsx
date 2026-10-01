/** @vitest-environment happy-dom */
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { LauncherBranchInstance } from "../api/launcher";
import { VuiProvider } from "../components/vui/VuiProvider";
import { LauncherBranchInstancesPanel } from "./LauncherBranchInstancesPanel";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const copy = {
  branchInstances: "分支实例",
  branchInstancesHint: "管理工作区分支",
  branchColumn: "分支",
  instanceState: "状态",
  instanceKind: "类型",
  instancePath: "路径",
  currentInstance: "当前实例",
  legacyCheckout: "旧工作区",
  retiredCheckout: "已退役",
  notCheckedOut: "未检出",
};

function instance(overrides: {
  id?: string;
  branch?: string;
  current?: boolean;
  state?: LauncherBranchInstance["runtime"]["lifecycleState"];
  alive?: boolean;
  windowOpen?: boolean;
} = {}): LauncherBranchInstance {
  const id = overrides.id ?? "worktree:task";
  const branch = overrides.branch ?? "codex/task";
  const state = overrides.state ?? "running";
  const alive = overrides.alive ?? state === "running";
  const windowOpen = overrides.windowOpen ?? false;
  return {
    id,
    kind: "worktree",
    branch,
    path: `C:/repo/.worktrees/${id}`,
    displayPath: `.worktrees/${id}`,
    head: "abc123",
    current: overrides.current ?? false,
    legacy: false,
    dirty: false,
    checkedOut: true,
    alive,
    observedState: state,
    port: alive ? 8000 : 0,
    pids: { backend: alive ? 1234 : 0, window: 0, manager: 0 },
    promotable: true,
    shortName: branch,
    workbenchTitle: `${branch} 台`,
    runtime: {
      lifecycleState: state,
      desiredState: state === "closed" ? "closed" : "running",
      observedState: state,
      phase: state === "building" ? "building" : "steady",
      backend: {
        alive,
        healthy: alive,
        listening: alive,
        port: alive ? 8000 : 0,
        portReserved: false,
        portConflict: false,
        pid: alive ? 1234 : 0,
      },
      frontend: { mode: "bundled_static_dist", ready: state !== "building" },
      window: { open: windowOpen, pid: 0, title: `${branch} 台`, titleObserved: false },
    },
    startable: true,
    startBlockReason: "",
  };
}

let host: HTMLDivElement;
let root: Root;
let queryClient: QueryClient;
let onSelect: ReturnType<typeof vi.fn>;
let onLifecycle: ReturnType<typeof vi.fn>;
let onStopMany: ReturnType<typeof vi.fn>;

async function renderPanel(items: LauncherBranchInstance[], buildingStartPending = false, listError?: string) {
  onSelect = vi.fn();
  onLifecycle = vi.fn(() => ({ accepted: true as const }));
  onStopMany = vi.fn();
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={queryClient}>
        <VuiProvider>
          <LauncherBranchInstancesPanel
            copy={copy}
            items={items}
            selectedId={items[0]?.id ?? ""}
            onSelect={onSelect}
            launcherOnline
            listError={listError}
            lifecyclePending={buildingStartPending}
            pendingOperation={buildingStartPending ? { instanceId: items[0].id, operation: "start" } : undefined}
            onLifecycle={onLifecycle}
            onStopMany={onStopMany}
          />
        </VuiProvider>
      </QueryClientProvider>,
    );
  });
}

function button(label: string, scope: ParentNode = document): HTMLButtonElement {
  const found = [...scope.querySelectorAll<HTMLButtonElement>("button")]
    .find((candidate) => candidate.textContent?.trim() === label);
  if (!found) throw new Error(`button not found: ${label}`);
  return found;
}

async function click(element: HTMLElement) {
  await act(async () => {
    element.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, button: 0, ctrlKey: false }));
    element.dispatchEvent(new MouseEvent("pointerup", { bubbles: true, button: 0, ctrlKey: false }));
    element.click();
    await Promise.resolve();
  });
}

async function waitForDialog(condition: () => boolean, attempts = 80) {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    if (condition()) {
      return;
    }
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 25));
    });
  }
  throw new Error('dialog condition not met; dialogs: ' + [...document.querySelectorAll('[role="dialog"], [role="alertdialog"]')].map((d) => (d.textContent || '').slice(0, 120)).join(' || '));
}

async function openRowCleanupDialog(branch: string) {
  const menuTrigger = [...host.querySelectorAll("button")].find(
    (candidate) => (candidate.getAttribute("aria-label") || "").includes("更多操作"),
  );
  if (!menuTrigger) throw new Error(`row menu button not found for ${branch}`);
  await click(menuTrigger);
  const cleanupItem = [...document.querySelectorAll('[role="menuitem"]')].find(
    (item) => item.textContent?.trim() === "清理",
  );
  if (!cleanupItem) throw new Error("cleanup menu item not found");
  await click(cleanupItem);
}

function findDialogConfirmButton(scope: ParentNode | null | undefined): HTMLButtonElement | undefined {
  if (!scope) return undefined;
  return [...scope.querySelectorAll<HTMLButtonElement>("button")].find(
    (candidate) => (candidate.textContent || "").trim().startsWith("清理"),
  );
}

beforeEach(() => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root?.unmount());
  queryClient?.clear();
  host?.remove();
});

describe("Launcher branch workspace interactions", () => {
  it("keeps cached workspaces and their actions visible when a background refresh fails", async () => {
    await renderPanel([instance({ branch: "codex/cached", state: "closed", alive: false })], false, "工作区刷新失败");
    expect(host.textContent).toContain("工作区刷新失败");
    expect(host.querySelector('[role="table"]')).not.toBeNull();
    expect(host.textContent).toContain("codex/cached");
    expect(button("打开窗口").disabled).toBe(false);
  });

  it("surfaces the window hint only when a running backend has no window", async () => {
    await renderPanel([
      instance({ id: "worktree:opened", branch: "codex/open", windowOpen: true }),
      instance({ id: "worktree:headless", branch: "codex/headless" }),
      instance({ id: "worktree:closed", branch: "codex/closed", state: "closed", alive: false }),
    ]);

    const rows = [...host.querySelectorAll('[role="row"]')];
    const rowOf = (branch: string) => rows.find((row) => row.textContent?.includes(branch));
    expect(rowOf("codex/headless")?.textContent).toContain("窗口未打开");
    expect(rowOf("codex/open")?.textContent).not.toContain("窗口未打开");
    expect(rowOf("codex/closed")?.textContent).not.toContain("窗口未打开");
  });

  it("surfaces a retry affordance when the cleanup metadata read fails instead of spinning forever", async () => {
    const jsonResponse = (payload: unknown) =>
      new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
    let dataFetchCount = 0;
    const fetchMock = vi.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>(
      async (input) => {
        const url = String(input);
        if (url.includes("/api/control-token")) {
          return jsonResponse({ header: "X-Control-Token", controlToken: "test-control-token" });
        }
        dataFetchCount += 1;
        if (dataFetchCount === 1) {
          throw new TypeError("fetch failed");
        }
        return jsonResponse({ items: [] });
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    try {
      await renderPanel([instance({ id: "worktree:residue", branch: "codex/residue", state: "closed", alive: false })]);

      const cleanupDialog = () =>
        [...document.querySelectorAll('[role="dialog"], [role="alertdialog"]')].find((node) =>
          (node.textContent || "").includes("确认清理分支实例"),
        );
      await openRowCleanupDialog("codex/residue");
      await waitForDialog(() => cleanupDialog()?.textContent?.includes("读取分支实例失败") === true);

      // Merge status is the only warning before deleting an unmerged branch:
      // a failed read keeps confirm locked but must explain and offer retry.
      expect(cleanupDialog()?.textContent).toContain("重试读取");
      const confirmInError = findDialogConfirmButton(cleanupDialog());
      expect(confirmInError?.disabled).toBe(true);

      await click(button("重试读取", cleanupDialog()!));
      await waitForDialog(() => cleanupDialog()?.textContent?.includes("codex/residue") === true);
      const confirmAfterRetry = findDialogConfirmButton(cleanupDialog());
      expect(confirmAfterRetry?.disabled).toBe(false);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("confirms ordinary Stop before dispatching the stop request", async () => {
    const running = instance({ id: "worktree:running", branch: "codex/running" });
    await renderPanel([running]);

    await click(button("停止"));
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain("确认停止这些工作台");
    await click(button("停止", document.querySelector('[role="dialog"]')!));

    expect(onStopMany).toHaveBeenCalledWith([running.id]);
    expect(onLifecycle).not.toHaveBeenCalled();
  });

  it("confirms Force stop before dispatching the recovery operation", async () => {
    const stoppedWorktree = instance({ id: "worktree:stale", branch: "codex/stale", state: "stopping", alive: false });
    await renderPanel([stoppedWorktree]);

    await click(button("强制停止"));
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain("普通停止无法收口时使用");
    await click(button("强制停止", document.querySelector('[role="dialog"]')!));

    expect(onLifecycle).toHaveBeenCalledWith(stoppedWorktree.id, "force-stop");
    expect(onStopMany).not.toHaveBeenCalled();
  });

  it("keeps the open action disabled during a frontend build while Stop remains available", async () => {
    const building = instance({ id: "worktree:building", branch: "codex/building", state: "building", alive: false });
    await renderPanel([building], true);

    const openAction = button("构建中");
    expect(openAction.disabled).toBe(true);
    await click(openAction);
    expect(onLifecycle).not.toHaveBeenCalled();

    const stopAction = button("停止");
    expect(stopAction.disabled).toBe(false);
    await click(stopAction);
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain("确认停止这些工作台");
    expect(button("停止", document.querySelector('[role="dialog"]')!).disabled).toBe(false);
    await click(button("停止", document.querySelector('[role="dialog"]')!));

    expect(onStopMany).toHaveBeenCalledWith([building.id]);
  });

  it("opens the branch detail view and updates the selected branch when a row is clicked", async () => {
    const branch = instance({ id: "worktree:details", branch: "codex/details", alive: false, state: "closed" });
    await renderPanel([branch]);
    const table = host.querySelector<HTMLElement>('[role="table"][aria-label="工作区分支列表"]');
    const row = table?.querySelectorAll<HTMLElement>('[role="row"]')[1];
    expect(row).toBeTruthy();

    await click(row!);

    expect(onSelect).toHaveBeenCalledWith(branch.id);
    expect(host.textContent).toContain("返回分支列表");
    expect(host.textContent).toContain("概览");
    expect(host.textContent).toContain("codex/details");
  });
});
