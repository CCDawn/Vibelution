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
  backend?: Partial<LauncherBranchInstance["runtime"]["backend"]>;
  spawnIdentityStatus?: "match" | "dead" | "mismatch" | "unknown";
} = {}): LauncherBranchInstance {
  const id = overrides.id ?? "worktree:task";
  const branch = overrides.branch ?? "codex/task";
  const state = overrides.state ?? "running";
  const alive = overrides.alive ?? state === "running";
  const backendAlive = overrides.backend?.alive ?? alive;
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
        alive: backendAlive,
        healthy: overrides.backend?.healthy ?? backendAlive,
        listening: overrides.backend?.listening ?? backendAlive,
        port: backendAlive ? 8000 : 0,
        portReserved: false,
        portConflict: false,
        pid: backendAlive ? 1234 : 0,
        ...overrides.backend,
      },
      frontend: { mode: "bundled_static_dist", ready: state !== "building" },
      window: { open: windowOpen, pid: 0, title: `${branch} 台`, titleObserved: false },
      ...(overrides.spawnIdentityStatus ? { spawnIdentityStatus: overrides.spawnIdentityStatus } : {}),
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
    expect(button("启动工作台").disabled).toBe(false);
  });

  it("labels the workbench action from backend health and window presence", async () => {
    const healthyBackend = { alive: true, healthy: true, listening: true };
    const items = [
      instance({ id: "worktree:switch", branch: "codex/switch", windowOpen: true, backend: healthyBackend }),
      instance({
        id: "worktree:recover",
        branch: "codex/recover",
        windowOpen: true,
        // The flat alive flag can include this open window.
        alive: true,
        backend: { alive: false, healthy: false, listening: false },
      }),
      instance({ id: "worktree:open", branch: "codex/open", backend: healthyBackend }),
      instance({ id: "worktree:start", branch: "codex/start", state: "closed", alive: false }),
      instance({ id: "worktree:retry", branch: "codex/retry", state: "error", alive: false }),
    ];
    await renderPanel(items);

    const rowFor = (id: string) => [...host.querySelectorAll<HTMLElement>('[role="row"]')]
      .find((row) => row.textContent?.includes(id));
    const action = (id: string, label: string) => {
      const row = rowFor(id);
      if (!row) throw new Error(`row not found: ${id}`);
      return button(label, row);
    };

    expect(action("codex/switch", "切换到工作台").title).toContain("已经打开的工作台");
    expect(action("codex/switch", "切换到工作台").title).toContain("不会更新代码");
    expect(action("codex/recover", "恢复工作台")).toBeTruthy();
    expect(action("codex/recover", "恢复工作台").title).toContain("保存当前任务记录");
    expect(action("codex/recover", "恢复工作台").title).toContain("重启工作台");
    expect(action("codex/open", "打开工作台")).toBeTruthy();
    expect(action("codex/start", "启动工作台")).toBeTruthy();
    expect(action("codex/retry", "重试启动")).toBeTruthy();

    const labels: Record<string, string> = {
      "worktree:switch": "切换到工作台",
      "worktree:recover": "恢复工作台",
      "worktree:open": "打开工作台",
      "worktree:start": "启动工作台",
      "worktree:retry": "重试启动",
    };
    for (const id of items.map((item) => item.id)) {
      const openAction = action(id.replace("worktree:", "codex/"), labels[id]);
      await click(openAction);
      if (id === "worktree:recover") {
        await click(openAction);
      }
    }
    expect(onLifecycle.mock.calls).toEqual(items.map((item) => [
      item.id,
      item.id === "worktree:recover" ? "restart" : "start",
    ]));
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

    const forceStopAction = button("强制停止");
    expect(forceStopAction.getAttribute("data-variant")).toBe("danger");
    await click(button("停止"));
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain("确认停止这些工作台");
    await click(button("停止", document.querySelector('[role="dialog"]')!));

    expect(onStopMany).toHaveBeenCalledWith([running.id]);
    expect(onLifecycle).not.toHaveBeenCalled();
  });

  it("does not offer Force stop on a stopped row with no live runtime", async () => {
    const stoppedWorktree = instance({ id: "worktree:stale", branch: "codex/stale", state: "closed", alive: false });
    await renderPanel([stoppedWorktree]);

    expect([...host.querySelectorAll("button")].some((candidate) => candidate.textContent?.trim() === "强制停止")).toBe(false);
    const menuTrigger = [...host.querySelectorAll("button")].find(
      (candidate) => (candidate.getAttribute("aria-label") || "").includes("更多操作"),
    );
    if (!menuTrigger) throw new Error("row menu button not found");
    await click(menuTrigger);
    expect([...document.querySelectorAll('[role="menuitem"]')].some((item) => item.textContent?.trim() === "强制停止")).toBe(false);
    expect(onLifecycle).not.toHaveBeenCalled();
  });

  it("confirms Force stop from the menu while the row is already stopping", async () => {
    const stoppingWorktree = instance({ id: "worktree:stopping", branch: "codex/stopping", state: "stopping", alive: false });
    await renderPanel([stoppingWorktree]);

    const stoppingAction = button("停止中");
    expect(stoppingAction.disabled).toBe(true);
    expect([...host.querySelectorAll("button")].some((candidate) => candidate.textContent?.trim() === "强制停止")).toBe(false);
    expect([...host.querySelectorAll("button")].some((candidate) => candidate.textContent?.trim() === "停止")).toBe(false);

    const menuTrigger = [...host.querySelectorAll("button")].find(
      (candidate) => (candidate.getAttribute("aria-label") || "").includes("更多操作"),
    );
    if (!menuTrigger) throw new Error("row menu button not found");
    await click(menuTrigger);
    const menuItem = [...document.querySelectorAll('[role="menuitem"]')].find(
      (item) => item.textContent?.trim() === "强制停止",
    );
    if (!menuItem) throw new Error("force-stop menu item not found");
    await click(menuItem);
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain("普通停止无法收口时使用");
    await click(button("强制停止", document.querySelector('[role="dialog"]')!));

    expect(onLifecycle).toHaveBeenCalledWith(stoppingWorktree.id, "force-stop");
    expect(onStopMany).not.toHaveBeenCalled();
  });

  it("moves a backend-verified dead row's force-stop into the overflow menu", async () => {
    const deadWorktree = instance({
      id: "worktree:dead",
      branch: "codex/dead",
      state: "error",
      alive: false,
      spawnIdentityStatus: "dead",
    });
    await renderPanel([deadWorktree]);

    // Verified dead and not shown as stopped: no inline force-stop button.
    expect([...host.querySelectorAll("button")].some((candidate) => candidate.textContent?.trim() === "强制停止")).toBe(false);

    const menuTrigger = [...host.querySelectorAll("button")].find(
      (candidate) => (candidate.getAttribute("aria-label") || "").includes("更多操作"),
    );
    if (!menuTrigger) throw new Error("row menu button not found");
    await click(menuTrigger);
    const menuItem = [...document.querySelectorAll('[role="menuitem"]')].find(
      (item) => item.textContent?.trim() === "强制停止",
    );
    if (!menuItem) throw new Error("force-stop menu item not found");
    await click(menuItem);

    expect(document.querySelector('[role="dialog"]')?.textContent).toContain("普通停止无法收口时使用");
    await click(button("强制停止", document.querySelector('[role="dialog"]')!));

    expect(onLifecycle).toHaveBeenCalledWith(deadWorktree.id, "force-stop");
    expect(onStopMany).not.toHaveBeenCalled();
  });

  it("shows Stop on the only button during a frontend build", async () => {
    const building = instance({ id: "worktree:building", branch: "codex/building", state: "building", alive: false });
    await renderPanel([building], true);

    expect(host.textContent).toContain("构建中");
    expect([...host.querySelectorAll("button")].some((candidate) => candidate.textContent?.trim() === "构建中")).toBe(false);
    expect([...host.querySelectorAll("button")].some((candidate) => candidate.textContent?.trim() === "启动工作台")).toBe(false);
    expect([...host.querySelectorAll("button")].some((candidate) => candidate.textContent?.trim() === "正在启动")).toBe(false);

    const stopAction = button("停止");
    expect(stopAction.disabled).toBe(false);
    expect(stopAction.title).toContain("前端代码有更新，正在构建新版本，约需几分钟。");
    expect(stopAction.title).toContain("停止这次尚未完成的启动。");
    await click(stopAction);
    expect(onLifecycle).not.toHaveBeenCalled();
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain("确认停止这些工作台");
    expect(button("停止", document.querySelector('[role="dialog"]')!).disabled).toBe(false);
    await click(button("停止", document.querySelector('[role="dialog"]')!));

    expect(onStopMany).toHaveBeenCalledWith([building.id]);
  });

  it("shows Stop on the only button while a start is in flight", async () => {
    const starting = instance({ id: "worktree:starting", branch: "codex/starting", state: "starting", alive: false });
    await renderPanel([starting], true);

    expect(host.textContent).toContain("正在启动");
    expect([...host.querySelectorAll("button")].some((candidate) => candidate.textContent?.trim() === "正在启动")).toBe(false);
    expect([...host.querySelectorAll("button")].some((candidate) => candidate.textContent?.trim() === "启动工作台")).toBe(false);

    const stopAction = button("停止");
    expect(stopAction.disabled).toBe(false);
    expect(stopAction.title).toContain("停止这次尚未完成的启动。");
    await click(stopAction);
    expect(onLifecycle).not.toHaveBeenCalled();
    expect(document.querySelector('[role="dialog"]')?.textContent).toContain("确认停止这些工作台");
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
    expect(host.textContent).toContain("运行情况");
    expect(host.textContent).toContain("工作区信息");
    await click(button("查看完整路径"));
    expect(host.textContent).toContain(branch.path);
    expect(onLifecycle).not.toHaveBeenCalled();
    await click(button("返回分支列表"));
    expect(host.querySelector('[role="table"][aria-label="工作区分支列表"]')).toBeTruthy();
  });
});
