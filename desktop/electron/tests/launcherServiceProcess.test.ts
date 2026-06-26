import { describe, expect, it } from "vitest";
import { initialManagedProcessState } from "../src/process/managedProcessTypes.js";
import {
  markProcessExited,
  markProcessFailed,
  markProcessRunning,
  markProcessStarting
} from "../src/process/launcherServiceProcess.js";

describe("python launcher service supervisor transitions", () => {
  it("records start and running pid for the single directly owned child", () => {
    const idle = initialManagedProcessState("python_launcher_service");
    const starting = markProcessStarting(idle, "2026-06-26T00:00:00.000Z");
    const running = markProcessRunning(starting, 1234);
    expect(running).toMatchObject({
      role: "python_launcher_service",
      status: "running",
      pid: 1234,
      startedAt: "2026-06-26T00:00:00.000Z"
    });
  });

  it("clears pid and records exit evidence", () => {
    const running = markProcessRunning(
      markProcessStarting(initialManagedProcessState("python_launcher_service"), "start"),
      2222
    );
    const exited = markProcessExited(running, 0, "", "end");
    expect(exited).toMatchObject({ status: "exited", pid: 0, exitCode: 0, exitedAt: "end" });
  });

  it("records failure reason", () => {
    const failed = markProcessFailed(initialManagedProcessState("python_launcher_service"), "spawn failed", "now");
    expect(failed).toMatchObject({ status: "failed", lastError: "spawn failed", exitedAt: "now" });
  });
});
