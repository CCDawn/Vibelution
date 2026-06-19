import { describe, expect, it } from "vitest";

import { kernelTaskCenterHref, kernelTaskListUrl, kernelTaskTimelineUrl, selectKernelTaskId } from "./kernel";

describe("kernel API urls", () => {
  it("builds canonical kernel task list urls", () => {
    expect(kernelTaskListUrl("", 80)).toBe("/api/kernel/tasks?limit=80");
    expect(kernelTaskListUrl("succeeded", 120)).toBe("/api/kernel/tasks?status=succeeded&limit=120");
  });

  it("builds encoded kernel task timeline urls", () => {
    expect(kernelTaskTimelineUrl("task/with space")).toBe("/api/kernel/tasks/task%2Fwith%20space/timeline");
  });

  it("builds kernel task center deep links", () => {
    expect(kernelTaskCenterHref("")).toBe("/kernel");
    expect(kernelTaskCenterHref("task/with space")).toBe("/kernel?taskId=task%2Fwith+space");
  });

  it("keeps requested task ids even when the task is outside the current list", () => {
    expect(selectKernelTaskId([{ taskId: "task-new" }, { taskId: "task-old" }], "task-hidden")).toBe("task-hidden");
    expect(selectKernelTaskId([{ taskId: "task-new" }, { taskId: "task-old" }], "")).toBe("task-new");
    expect(selectKernelTaskId([], "")).toBe("");
  });
});
