import { describe, expect, it } from "vitest";

import type { LauncherBranchInstance } from "../api/launcher";
import {
  cleanupRecommendation,
  gitStatusExplanation,
  runtimeStatusExplanation,
} from "./LauncherBranchStatusHelp.model";
import helpSource from "./LauncherBranchStatusHelp.tsx?raw";
import helpStyles from "./LauncherBranchStatusHelp.styles";

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
    observedState: "closed",
    port: 0,
    pids: { backend: 0, window: 0, manager: 0 },
    promotable: true,
    mergedToMain: true,
    cleanupEligible: true,
    runtime: {
      lifecycleState: "closed",
      desiredState: "closed",
      observedState: "closed",
      phase: "steady",
      backend: { alive: false, healthy: false, listening: false, port: 0, portReserved: false, portConflict: false, pid: 0 },
      frontend: { mode: "bundled_static_dist", ready: true },
      window: { open: false, pid: 0, title: "task", titleObserved: true },
    },
    startable: true,
    ...overrides,
  };
}

describe("Launcher branch status help", () => {
  it("recommends cleanup only for stopped, clean, merged instances", () => {
    expect(cleanupRecommendation(instance(), "stopped", true)).toEqual({
      level: "recommended",
      label: "可以清理",
      reason: "实例已停止、工作区干净且提交已合入 main。",
    });
    expect(cleanupRecommendation(instance({ dirty: true }), "stopped", true).level).toBe("avoid");
    expect(cleanupRecommendation(instance({ mergedToMain: false }), "stopped", true).level).toBe("avoid");
    expect(cleanupRecommendation(instance({ mergedToMain: undefined }), "stopped", true).level).toBe("review");
    expect(cleanupRecommendation(instance({ alive: true }), "running", true).level).toBe("avoid");
    expect(cleanupRecommendation(instance({ alive: true, dirty: true, mergedToMain: false }), "running", true).reason).toContain("；");
    expect(cleanupRecommendation(instance({
      runtime: {
        ...instance().runtime,
        window: { open: true, pid: 42, title: "task", titleObserved: true },
      },
    }), "stopped", true).level).toBe("avoid");
    expect(cleanupRecommendation(instance({ cleanupRisks: ["stop_then_remove"] }), "stopped", true).level).toBe("avoid");
  });

  it("keeps main and the current worktree protected", () => {
    expect(cleanupRecommendation(instance({ id: "main", kind: "main", branch: "main" }), "stopped", true).label).toBe("不可清理");
    expect(cleanupRecommendation(instance({ current: true }), "stopped", true).label).toBe("不可清理");
  });

  it("does not treat a failed leftover as a live instance that must be stopped before cleanup", () => {
    const failed = instance({
      runtime: {
        ...instance().runtime,
        lifecycleState: "error",
      },
    });
    const recommendation = cleanupRecommendation(failed, "failed", true);
    expect(recommendation.level).toBe("avoid");
    expect(recommendation.reason).toContain("关闭失败记录");
    expect(recommendation.reason).not.toContain("先停止实例");
    expect(runtimeStatusExplanation("failed", true)).toContain("不必重启");
  });

  it("explains runtime and Git labels in plain language", () => {
    expect(runtimeStatusExplanation("partial", true)).toContain("部分运行组件");
    expect(gitStatusExplanation(instance({ dirty: true }), true)).toContain("强制清理会丢弃");
    expect(gitStatusExplanation(instance({ mergedToMain: false }), true)).toContain("尚未合入 main");
    expect(gitStatusExplanation(instance({ cleanupRisks: ["delete_unmerged"] }), true)).toContain("尚未合入 main");
  });

  it("keeps the tooltip trigger on a local style map", () => {
    expect(helpSource).toContain("styles.trigger");
    expect(helpSource).not.toContain('className="inline-flex');
    expect(helpStyles.trigger).toContain("cursor-help");
    expect(helpStyles.trigger).toContain("focus-visible:shadow-[var(--vui-shadow-focus)]");
  });
});
