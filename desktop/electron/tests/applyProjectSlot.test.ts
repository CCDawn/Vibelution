import { describe, expect, it } from "vitest";
import {
  instanceWorkbenchUrl,
  planProjectSlot,
  projectSlotWindowAction
} from "../src/protocol/applyProjectSlot.js";
import { parseBranchInstanceRecords } from "../src/protocol/launcherControlClient.js";

const listed = {
  items: [
    {
      id: "main",
      path: "C:/repo",
      slotKey: "c:\\repo",
      url: "http://127.0.0.1:8000",
      port: 8000,
      alive: true,
      current: true,
      checkedOut: true,
      kind: "main"
    },
    {
      id: "worktree:task",
      path: "C:/repo/.worktrees/task",
      slotKey: "c:\\repo\\.worktrees\\task",
      url: "",
      port: 8001,
      alive: false,
      current: false,
      checkedOut: true,
      kind: "worktree"
    }
  ]
};

describe("planProjectSlot", () => {
  const items = parseBranchInstanceRecords(listed);

  it("matches a path or slotKey without treating slash differences as a new slot", () => {
    expect(planProjectSlot({ items, projectRoot: "C:\\repo\\.worktrees\\task" }).instanceId).toBe("worktree:task");
    expect(planProjectSlot({ items, projectRoot: "C:/repo/.worktrees/task" }).instanceId).toBe("worktree:task");
    expect(planProjectSlot({ items, projectRoot: "c:\\repo" }).instanceId).toBe("main");
  });

  it("does not start a live main slot again when no lifecycle command is given", () => {
    expect(
      planProjectSlot({
        items,
        projectRoot: "C:/repo"
      })
    ).toMatchObject({
      instanceId: "main",
      url: "http://127.0.0.1:8000/",
      isMain: true,
      operation: "",
      alive: true
    });
  });

  it("plans start for an idle worktree instead of falling through to main", () => {
    expect(
      planProjectSlot({
        items,
        projectRoot: "C:/repo/.worktrees/task",
        lifecycleCommand: "start"
      })
    ).toMatchObject({
      instanceId: "worktree:task",
      url: "http://127.0.0.1:8001/",
      isMain: false,
      operation: "start"
    });
  });

  it("keeps stop on the matched worktree", () => {
    expect(
      planProjectSlot({
        items,
        projectRoot: "C:/repo/.worktrees/task",
        lifecycleCommand: "stop"
      }).operation
    ).toBe("stop");
  });

  it("rejects an unknown project path instead of planning main start", () => {
    expect(() =>
      planProjectSlot({
        items,
        projectRoot: "C:/missing",
        lifecycleCommand: "start"
      })
    ).toThrow("找不到对应工作区");
  });

  it("rejects an empty project path", () => {
    expect(() => planProjectSlot({ items, projectRoot: "   " })).toThrow("未指定要应用的工作区路径");
  });

  it("does not treat a worktree start plan as the main slot", () => {
    expect(
      planProjectSlot({
        items,
        projectRoot: "C:/repo/.worktrees/task",
        lifecycleCommand: "start"
      }).isMain
    ).toBe(false);
  });

  it("builds a loopback workbench URL from the reserved port", () => {
    expect(instanceWorkbenchUrl({ url: "", port: 8002 })).toBe("http://127.0.0.1:8002/");
  });

  it("leaves start-like branch windows to the readiness supervisor", () => {
    const plan = planProjectSlot({
      items,
      projectRoot: "C:/repo/.worktrees/task",
      lifecycleCommand: "restart"
    });
    expect(projectSlotWindowAction(plan)).toBe("none");
  });

  it("routes an already-running branch to its instance window", () => {
    const liveItems = parseBranchInstanceRecords({
      items: listed.items.map((item) =>
        item.id === "worktree:task" ? { ...item, alive: true } : item
      )
    });
    const plan = planProjectSlot({
      items: liveItems,
      projectRoot: "C:/repo/.worktrees/task",
      lifecycleCommand: "status"
    });
    expect(projectSlotWindowAction(plan)).toBe("instance");
  });
});
