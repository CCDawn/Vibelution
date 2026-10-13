import { describe, expect, it } from "vitest";

import type { ActiveWorkIndicatorItem } from "../../app/systemStatus";
import type { RuntimeTaskCard } from "../../api/runtimeTasks";
import {
  activeWorkSessionIdentity,
  deduplicateRuntimeTasksByActiveWork,
  isRuntimeTaskAwaitingStopConfirmation,
} from "./runtimeTasksPanelModel";

function activeWork(overrides: Partial<ActiveWorkIndicatorItem> = {}): ActiveWorkIndicatorItem {
  return {
    kind: "chat",
    label: "对话",
    summary: "正在处理",
    fullSummary: "正在处理请求",
    status: "running",
    runId: "run-1",
    href: "/chat?session=session-1",
    detail: "对话 · 正在处理",
    tone: "running",
    ...overrides,
  };
}

function task(overrides: Partial<RuntimeTaskCard> & { taskId: string }): RuntimeTaskCard {
  return {
    kind: "child_session",
    status: "running",
    title: overrides.taskId,
    parentSessionId: "parent-1",
    childSessionId: "",
    startedAt: "2026-10-13T00:00:00.000Z",
    ...overrides,
  };
}

describe("runtime tasks panel model", () => {
  it("uses only an active chat route session identity for nested task deduplication", () => {
    const work = activeWork();
    expect(activeWorkSessionIdentity(work)).toBe("session-1");
    expect(activeWorkSessionIdentity(activeWork({ kind: "formal_review", href: "/teams" }))).toBe("");

    const tasks = [
      task({ taskId: "nested", childSessionId: "session-1" }),
      task({ taskId: "separate", childSessionId: "session-2" }),
      task({ taskId: "no-child", childSessionId: "" }),
    ];
    expect(deduplicateRuntimeTasksByActiveWork(tasks, [work]).map((item) => item.taskId)).toEqual([
      "separate",
      "no-child",
    ]);
  });

  it("keeps an accepted stop pending until the task appears in the terminal list bucket", () => {
    expect(isRuntimeTaskAwaitingStopConfirmation("task-1", ["task-1"], new Set())).toBe(true);
    expect(isRuntimeTaskAwaitingStopConfirmation("task-1", ["task-1"], new Set(["task-1"]))).toBe(false);
    expect(isRuntimeTaskAwaitingStopConfirmation("task-2", ["task-1"], new Set())).toBe(false);
  });
});
