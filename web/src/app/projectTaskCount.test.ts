import { describe, expect, it } from "vitest";

import type { RuntimeTaskCard } from "../api/runtimeTasks";
import type { ActiveWorkIndicator, ActiveWorkIndicatorItem } from "./systemStatus";
import { projectTaskCount } from "./projectTaskCount";

function activeItem(overrides: Partial<ActiveWorkIndicatorItem> = {}): ActiveWorkIndicatorItem {
  return {
    kind: "chat",
    label: "Chat",
    summary: "Working",
    fullSummary: "Working on a request",
    status: "running",
    runId: "run-1",
    href: "/chat?session=session-1",
    detail: "Chat · Working",
    tone: "running",
    ...overrides,
  };
}

function activeWork(items: ActiveWorkIndicatorItem[]): ActiveWorkIndicator {
  const primary = items[0] ?? activeItem();
  return {
    ...primary,
    count: items.length,
    overflowCount: Math.max(0, items.length - 1),
    items,
    staleFailures: [],
  };
}

function task(overrides: Partial<RuntimeTaskCard> & { taskId: string }): RuntimeTaskCard {
  return {
    kind: "child_session",
    status: "running",
    title: overrides.taskId,
    parentSessionId: "parent-session-1",
    childSessionId: null,
    startedAt: "2026-10-13T00:00:00.000Z",
    ...overrides,
  };
}

describe("projectTaskCount", () => {
  it("deduplicates runtime child sessions only against active chat routes and keeps stopping tasks counted", () => {
    const active = activeWork([
      activeItem({ href: "/chat?session=chat-session" }),
      activeItem({ kind: "formal_review", href: "/teams?session=review-session" }),
    ]);

    expect(projectTaskCount(active, [
      task({ taskId: "same-chat", childSessionId: "chat-session" }),
      task({ taskId: "same-text-different-kind", childSessionId: "review-session" }),
      task({ taskId: "stopping-task", status: "stopping", childSessionId: "other-session" }),
    ])).toBe(4);
  });

  it("counts a repeated taskId once and does not infer identity when childSessionId is missing", () => {
    const active = activeWork([activeItem({ href: "/chat?session=shared-session" })]);

    expect(projectTaskCount(active, [
      task({ taskId: "duplicate-task", childSessionId: null, parentSessionId: "shared-session" }),
      task({ taskId: "duplicate-task", childSessionId: "shared-session" }),
      task({ taskId: "unidentified-child", childSessionId: "", parentSessionId: "shared-session" }),
    ])).toBe(3);
  });

  it("requires an exact /chat path before using a chat session query as deduplication evidence", () => {
    const active = activeWork([activeItem({ href: "/aux?session=shared-session" })]);

    expect(projectTaskCount(active, [
      task({ taskId: "task-1", childSessionId: "shared-session" }),
    ])).toBe(2);
  });
});
