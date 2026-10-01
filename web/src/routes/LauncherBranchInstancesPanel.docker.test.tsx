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
