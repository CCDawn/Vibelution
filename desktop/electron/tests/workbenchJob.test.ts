import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import {
  __setWorkbenchJobNativeForTests,
  hasTrackedWorkbenchJob,
  spawnTrackedWorkbenchProcess,
  terminateTrackedWorkbenchJob,
  type WorkbenchJobHandle,
  type WorkbenchJobNative
} from "../src/process/workbenchJob.js";

describe("workbench job registry", () => {
  it("terminates the tracked group before a later tree walk would be needed", async () => {
    const jobs: WorkbenchJobHandle[] = [];
    let active = 2;
    const native: WorkbenchJobNative = {
      spawn: () => {
        const job = { id: jobs.length + 1 };
        jobs.push(job);
        active = 2;
        return { pid: 4100 + jobs.length, job };
      },
      terminate: () => {
        active = 0;
        return true;
      },
      activeCount: () => active,
      close: () => undefined
    };
    __setWorkbenchJobNativeForTests(native);
    spawnTrackedWorkbenchProcess("C:/repo", {
      executable: "pythonw.exe",
      arguments: ["scripts/web_workbench.py"],
      cwd: "C:/repo",
      env: {},
      stdoutPath: "C:/repo/out.log",
      stderrPath: "C:/repo/err.log"
    });
    expect(hasTrackedWorkbenchJob("c:/repo")).toBe(true);
    await expect(terminateTrackedWorkbenchJob("C:\\repo")).resolves.toBe(true);
    expect(hasTrackedWorkbenchJob("C:/repo")).toBe(false);
    __setWorkbenchJobNativeForTests(undefined);
  });
});

const nativeAddon = process.platform === "win32"
  ? describe
  : describe.skip;

nativeAddon("windows workbench job", () => {
  it("kills the spawned process and the child it starts", async () => {
    const { loadWorkbenchJobNative } = await import("../src/process/workbenchJob.js");
    const native = loadWorkbenchJobNative();
    const directory = mkdtempSync(join(tmpdir(), "vibelution-job-"));
    const childPidPath = join(directory, "child-pid.txt");
    const stdoutPath = join(directory, "stdout.log");
    const stderrPath = join(directory, "stderr.log");
    const script = [
      "const {spawn}=require('node:child_process');",
      "const fs=require('node:fs');",
      "const child=spawn(process.execPath,['-e','setInterval(()=>{},1000)'],{stdio:'ignore',windowsHide:true});",
      `fs.writeFileSync(${JSON.stringify(childPidPath)}, String(child.pid));`,
      "setInterval(()=>{},1000);"
    ].join("");
    const spawned = native.spawn({
      executable: process.execPath,
      arguments: ["-e", script],
      cwd: directory,
      env: { ...process.env, PATH: process.env.PATH ?? "" },
      stdoutPath,
      stderrPath
    });
    try {
      const deadline = Date.now() + 5_000;
      let childPid = 0;
      while (Date.now() < deadline && childPid <= 0) {
        try {
          childPid = Number(readFileSync(childPidPath, "utf8"));
        } catch {
          await new Promise((resolve) => setTimeout(resolve, 50));
        }
      }
      expect(childPid).toBeGreaterThan(0);
      expect(native.activeCount(spawned.job)).toBeGreaterThan(0);
      native.terminate(spawned.job);
      const gone = Date.now() + 8_000;
      while (Date.now() < gone && native.activeCount(spawned.job) > 0) {
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
      expect(native.activeCount(spawned.job)).toBe(0);
      expect(pidAlive(spawned.pid)).toBe(false);
      expect(pidAlive(childPid)).toBe(false);
    } finally {
      try {
        native.close(spawned.job);
      } catch {
        // Already closed after a verified termination.
      }
      for (let attempt = 0; attempt < 10; attempt += 1) {
        try {
          rmSync(directory, { recursive: true, force: true });
          break;
        } catch {
          await new Promise((resolve) => setTimeout(resolve, 100));
        }
      }
    }
  }, 20_000);
});

function pidAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}
