import { describe, expect, it } from "vitest";

import { kernelTaskListUrl, kernelTaskTimelineUrl } from "./kernel";

describe("kernel API urls", () => {
  it("builds canonical kernel task list urls", () => {
    expect(kernelTaskListUrl("", 80)).toBe("/api/kernel/tasks?limit=80");
    expect(kernelTaskListUrl("succeeded", 120)).toBe("/api/kernel/tasks?status=succeeded&limit=120");
  });

  it("builds encoded kernel task timeline urls", () => {
    expect(kernelTaskTimelineUrl("task/with space")).toBe("/api/kernel/tasks/task%2Fwith%20space/timeline");
  });
});
