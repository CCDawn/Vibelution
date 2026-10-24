import { describe, expect, it } from "vitest";

import { launcherCommandResultEventPresentation, launcherCommandResultPresentation } from "./launcherCommandResultPresentation";

describe("launcherCommandResultPresentation", () => {
  it.each([
    [{ completed: true, ok: true }, "completed", "success", "已完成", "Completed"],
    [{ completed: true, ok: false }, "failed", "error", "失败", "Failed"],
    [{ completed: true, ok: false, cancelled: true }, "cancelled", "neutral", "已取消", "Cancelled"],
    [{ completed: true, ok: false, errorType: "LifecycleCommandCancelled" }, "cancelled", "neutral", "已取消", "Cancelled"],
    [{ completed: true, ok: false, errorType: "SupersededByOpenWorkbench" }, "superseded", "neutral", "已被后续请求替代", "Superseded"],
    [{ completed: true, ok: false, errorType: "SupersededByCloseWorkbench" }, "superseded", "neutral", "已被后续请求替代", "Superseded"],
    [{ completed: true, ok: false, errorType: "SupersededByForceCloseWorkbench" }, "superseded", "neutral", "已被后续请求替代", "Superseded"],
    [{ completed: true, ok: false, supersededByCommandId: "cmd-new" }, "superseded", "neutral", "已被后续请求替代", "Superseded"],
    [{ completed: false, ok: true }, "pending", "neutral", "处理中", "Pending"],
    [{ ok: false, cancelled: true }, "pending", "neutral", "处理中", "Pending"],
    [undefined, "pending", "neutral", "处理中", "Pending"],
    [{ completed: true }, "unknown", "neutral", "结果未知", "Unknown result"],
    [{ completed: true, ok: null }, "unknown", "neutral", "结果未知", "Unknown result"],
    [{ completed: true, errorType: "UnexpectedError" }, "unknown", "neutral", "结果未知", "Unknown result"],
    [{ completed: true, ok: false, errorType: "UnexpectedError" }, "failed", "error", "失败", "Failed"],
  ] as const)("keeps result %j in its own outcome family", (result, state, tone, zh, en) => {
    expect(launcherCommandResultPresentation(result, "zh")).toEqual({ state, tone, label: zh });
    expect(launcherCommandResultPresentation(result, "en")).toEqual({ state, tone, label: en });
  });
});

describe("launcherCommandResultEventPresentation", () => {
  it.each(["LifecycleCommandCancelled", "SupersededByOpenWorkbench", "SupersededByCloseWorkbench", "SupersededByForceCloseWorkbench"])(
    "uses the same terminal facts for a projected %s result event",
    (errorType) => {
      const facts = { completed: true, ok: false, errorType };
      expect(launcherCommandResultEventPresentation({ type: "command_queue.command_result_written", ...facts }, "zh"))
        .toEqual(launcherCommandResultPresentation(facts, "zh"));
      expect(launcherCommandResultEventPresentation({ type: "command_queue.command_result_written", ...facts }, "en"))
        .toEqual(launcherCommandResultPresentation(facts, "en"));
    },
  );

  it("leaves ordinary queue events with their existing event presentation", () => {
    expect(launcherCommandResultEventPresentation({
      type: "command_queue.processing_recovered", completed: true, ok: false, errorType: "LifecycleCommandCancelled",
    }, "zh")).toBeNull();
  });

  it("does not infer completed from a result event name without completion evidence", () => {
    expect(launcherCommandResultEventPresentation({ type: "command_queue.command_result_written", ok: false }, "zh"))
      .toMatchObject({ state: "pending", tone: "neutral" });
    expect(launcherCommandResultEventPresentation({ type: "command_queue.command_result_written", completed: true, ok: null }, "zh"))
      .toMatchObject({ state: "unknown", tone: "neutral" });
  });
});
