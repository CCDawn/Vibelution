import { describe, expect, it } from "vitest";

import type { LauncherBranchInstance } from "../api/launcher";
import panelSource from "./LauncherBranchInstancesPanel.tsx?raw";
import {
  BRANCH_INSTANCE_PAGE_SIZE,
  cleanupRiskLabels,
  formatBackendCell,
  instanceHealth,
  instanceHealthLabel,
  instanceWindowOpen,
  isCleanupEligible,
  paginateItems,
} from "./LauncherBranchInstancesPanel.model";

function instance(overrides: Partial<LauncherBranchInstance> = {}): LauncherBranchInstance {
  return {
    id: "worktree:task",
    kind: "worktree",
    branch: "codex/task",
    path: "C:/repo/.worktrees/task",
    displayPath: ".worktrees/task",
    head: "abc123",
    current: false,
    legacy: false,
    dirty: false,
    checkedOut: true,
    alive: false,
    observedState: "idle",
    port: 0,
    pids: { backend: 0, window: 0, manager: 0 },
    promotable: true,
    shortName: "task",
    ...overrides,
  };
}

describe("LauncherBranchInstancesPanel contracts", () => {
  it("keeps the product table on VUI primitives and a confirm dialog", () => {
    expect(panelSource).toContain("from \"../components/vui\"");
    expect(panelSource).toContain("<VButton");
    expect(panelSource).toContain("<VCheckbox");
    expect(panelSource).toContain("<VConfirmDialog");
    expect(panelSource).not.toContain("TeamSourcePagination");
    expect(panelSource).not.toMatch(/from\s+["']@heroui\/react["']/);
    expect(panelSource).not.toMatch(/renderers\/shadcn/);
    expect(panelSource).not.toMatch(/<button\b/);
    expect(BRANCH_INSTANCE_PAGE_SIZE).toBe(8);
  });

  it("pages every instance at 8 per page and keeps main on page 1", () => {
    const items = [
      instance({ id: "main", kind: "main", branch: "main", current: true, shortName: "主" }),
      ...Array.from({ length: 10 }, (_, index) => instance({
        id: `branch:${index + 1}`,
        kind: "local_branch",
        branch: `codex/item-${index + 1}`,
        shortName: `item-${index + 1}`,
      })),
    ];

    const first = paginateItems(items, 1);
    const second = paginateItems(items, 2);

    expect(first.pageCount).toBe(2);
    expect(first.items).toHaveLength(8);
    expect(first.items[0]?.id).toBe("main");
    expect(second.items).toHaveLength(3);
    expect(paginateItems(items, 99).page).toBe(2);
  });

  it("never treats main or the current checkout as cleanable", () => {
    expect(isCleanupEligible(instance({ id: "main", kind: "main", branch: "main", current: true }))).toBe(false);
    expect(isCleanupEligible(instance({ id: "worktree:self", current: true, cleanupEligible: false }))).toBe(false);
    expect(isCleanupEligible(instance({ cleanupEligible: true }))).toBe(true);
    expect(isCleanupEligible(instance({ kind: "local_branch", cleanupEligible: undefined }))).toBe(true);
  });

  it("lists cleanup risks for dirty running unmerged instances", () => {
    const labels = cleanupRiskLabels(
      instance({
        dirty: true,
        alive: true,
        mergedToMain: false,
        cleanupRisks: ["discard_dirty", "stop_then_remove", "delete_unmerged"],
      }),
      true,
    );

    expect(labels).toEqual([
      "将丢弃未提交改动",
      "将先停止再拆除运行中的实例",
      "将删除尚未合入 main 的本地提交",
    ]);
  });

  it("uses one Chinese health label and backend cell per instance", () => {
    const running = instance({
      id: "main",
      kind: "main",
      current: true,
      alive: true,
      port: 8002,
      pids: { backend: 14220, window: 0, manager: 0 },
      shortName: "主",
    });
    const dirty = instance({ dirty: true, port: 8001, shortName: "timing" });
    expect(instanceHealthLabel(instanceHealth(running), true)).toBe("运行中");
    expect(instanceHealthLabel(instanceHealth(dirty), true)).toBe("有未提交");
    expect(formatBackendCell(running)).toBe("14220 · 8002");
    expect(instanceWindowOpen(running, { currentId: "main", windowOpen: true })).toBe(true);
    expect(panelSource).toContain("onLifecycle");
    expect(panelSource).not.toContain("HEAD");
  });
});
