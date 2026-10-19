import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { executeMainLineWorkbench } from "../src/process/workbenchBackend.js";
import { closeOwnedWorkbenchFast } from "../src/process/fastWorkbenchClose.js";

vi.mock("../src/process/fastWorkbenchClose.js", () => ({ closeOwnedWorkbenchFast: vi.fn() }));
const directories: string[] = [];
afterEach(() => { for (const path of directories.splice(0)) rmSync(path, { recursive: true, force: true }); vi.clearAllMocks(); });

describe("explicit fast close lifecycle", () => {
  function fixture() {
    const workspaceRoot = mkdtempSync(join(tmpdir(), "vibelution-fast-close-lifecycle-"));
    directories.push(workspaceRoot);
    const previous = { spawnPid: 123, backendPid: 456, workbenchPort: 8000, desiredState: "open" };
    const writeState = vi.fn();
    const listActiveWork = vi.fn(() => { throw new Error("must not scan active work"); });
    const captureProcessIdentity = vi.fn(async () => { throw new Error("must not spawn Python"); });
    return { input: { workspaceRoot, pythonPath: "unused", operation: "force-stop" as const,
      command: { commandId: "cmd_fast", type: "force_close" as const, operation: "force-stop" as const, noBrowser: true },
      fastCloseTiming: { deadlineAt: Date.now() + 1800, forceAt: Date.now() + 1200 },
      readState: () => previous, writeState, listActiveWork, captureProcessIdentity,
      readDaemonPid: () => 0, pidAlive: (pid: number) => pid > 0 }, writeState, previous, listActiveWork, captureProcessIdentity };
  }
  it("records closed only after owned Job and listener retirement succeeds", async () => {
    const f = fixture();
    vi.mocked(closeOwnedWorkbenchFast).mockResolvedValue(true);
    expect((await executeMainLineWorkbench(f.input)).accepted).toBe(true);
    expect(closeOwnedWorkbenchFast).toHaveBeenCalledWith(expect.objectContaining({ spawnPid: 123, ...f.input.fastCloseTiming }));
    expect(f.writeState).toHaveBeenCalledWith(expect.objectContaining({ desiredState: "closed", observedState: "closed", spawnPid: 0, backendPid: 0 }));
    expect(f.listActiveWork).not.toHaveBeenCalled();
    expect(f.captureProcessIdentity).not.toHaveBeenCalled();
  });
  it("retains every handle on failed retirement instead of reporting closed", async () => {
    const f = fixture();
    vi.mocked(closeOwnedWorkbenchFast).mockResolvedValue(false);
    expect((await executeMainLineWorkbench(f.input)).accepted).toBe(false);
    expect(f.writeState).not.toHaveBeenCalled();
    expect(f.previous.spawnPid).toBe(123);
  });
  it("does not erase the registration of a separately live daemon", async () => {
    const f = fixture();
    const result = await executeMainLineWorkbench({ ...f.input, readDaemonPid: () => 789 });
    expect(result.accepted).toBe(false);
    expect(closeOwnedWorkbenchFast).not.toHaveBeenCalled();
    expect(f.writeState).not.toHaveBeenCalled();
  });
});
