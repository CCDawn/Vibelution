import { describe, expect, it } from "vitest";

import type { LauncherBranchInstance } from "../api/launcher";
import { resolveLiveInstance, resolveProcessMonitorTarget } from "./LauncherProcessMonitor.binding";

function instance(overrides: Partial<LauncherBranchInstance> = {}): LauncherBranchInstance {
  return {
    id: "worktree:task",
    kind: "worktree",
    branch: "codex/task",
    path: ".worktrees/task",
    displayPath: ".worktrees/task",
    head: "abc",
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

describe("process monitor auto-bind", () => {
  const main = instance({
    id: "main",
    kind: "main",
    branch: "main",
    current: true,
    alive: true,
    observedState: "open",
    port: 8002,
    shortName: "主",
  });
  const abandoned = instance({
    id: "branch:abandoned",
    kind: "local_branch",
    branch: "codex/abandoned",
    checkedOut: false,
    shortName: "abandoned",
  });
  const idleTree = instance({
    id: "worktree:idle",
    branch: "codex/idle",
    shortName: "idle",
  });

  it("binds to the current live instance by default", () => {
    const bound = resolveProcessMonitorTarget([main, abandoned], {
      selectedId: "branch:abandoned",
      currentId: "main",
    });
    expect(bound?.id).toBe("main");
    expect(resolveLiveInstance([main, abandoned], "main")?.id).toBe("main");
  });

  it("keeps the latest started live instance ahead of main", () => {
    const started = instance({ id: "worktree:started", alive: true, port: 8003, shortName: "started" });
    const bound = resolveProcessMonitorTarget([main, started], {
      selectedId: "main",
      currentId: "main",
      lastStartedId: "worktree:started",
    });
    expect(bound?.id).toBe("worktree:started");
  });

  it("only inspects an explicit checked-out row that is not the live project", () => {
    const bound = resolveProcessMonitorTarget([main, idleTree], {
      selectedId: "worktree:idle",
      currentId: "main",
      explicitSelect: true,
    });
    expect(bound?.id).toBe("worktree:idle");
  });
});
