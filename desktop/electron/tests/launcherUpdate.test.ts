import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";
import { executeLauncherUpdate, projectLauncherUpdateFreshness } from "../src/process/launcherUpdate.js";
import type { ActiveWorkStatus } from "../src/shutdown/shutdownCoordinator.js";

function updateInputs(state: ActiveWorkStatus = { state: "idle", message: "" }) {
  return {
    activeWork: vi.fn().mockResolvedValue(state),
    prepare: vi.fn().mockResolvedValue({}),
    stopWorkspaces: vi.fn().mockResolvedValue(undefined),
    scheduleReplacement: vi.fn().mockResolvedValue(undefined),
  };
}

describe("guarded local Launcher update", () => {
  it.each(["active", "unknown"] as const)("does not build, stop or schedule when tasks are %s", async (state) => {
    const input = updateInputs({ state, count: state === "active" ? 1 : 0, message: "" });
    expect(await executeLauncherUpdate(input)).toMatchObject({ accepted: false, operation: "restart-latest-shell" });
    expect(input.prepare).not.toHaveBeenCalled();
    expect(input.stopWorkspaces).not.toHaveBeenCalled();
    expect(input.scheduleReplacement).not.toHaveBeenCalled();
  });

  it("fails closed if the task probe rejects", async () => {
    const input = updateInputs();
    input.activeWork.mockRejectedValue(new Error("offline"));
    expect(await executeLauncherUpdate(input)).toMatchObject({ accepted: false, code: "active_work_status_unavailable" });
    expect(input.stopWorkspaces).not.toHaveBeenCalled();
  });

  it("lets an operator update save running tasks before replacing the shell", async () => {
    const input = { ...updateInputs({ state: "active", count: 1, message: "" }), interruptActiveWork: true };
    expect(await executeLauncherUpdate(input)).toMatchObject({ accepted: true });
    expect(input.prepare).toHaveBeenCalledOnce();
    expect(input.stopWorkspaces).toHaveBeenCalledOnce();
    expect(input.scheduleReplacement).toHaveBeenCalledOnce();
    expect(input.stopWorkspaces.mock.invocationCallOrder[0]).toBeLessThan(input.scheduleReplacement.mock.invocationCallOrder[0]);
  });

  it("retains the shell when an operator task-save acknowledgement fails", async () => {
    const input = { ...updateInputs({ state: "active", count: 1, message: "" }), interruptActiveWork: true };
    input.stopWorkspaces.mockRejectedValue(new Error("user_restart_pause_failed"));
    await expect(executeLauncherUpdate(input)).rejects.toThrow("user_restart_pause_failed");
    expect(input.scheduleReplacement).not.toHaveBeenCalled();
  });

  it("still rejects an unknown owner state for an operator update", async () => {
    const input = { ...updateInputs({ state: "unknown", message: "" }), interruptActiveWork: true };
    expect(await executeLauncherUpdate(input)).toMatchObject({ accepted: false, code: "active_work_status_unavailable" });
    expect(input.stopWorkspaces).not.toHaveBeenCalled();
  });

  it("keeps windows alive on preparation failure", async () => {
    const input = updateInputs();
    input.prepare.mockRejectedValue(new Error("tsc failed"));
    await expect(executeLauncherUpdate(input)).rejects.toThrow("tsc failed");
    expect(input.stopWorkspaces).not.toHaveBeenCalled();
    expect(input.scheduleReplacement).not.toHaveBeenCalled();
  });

  it("rechecks tasks that start during a build", async () => {
    const input = updateInputs();
    input.activeWork.mockResolvedValueOnce({ state: "idle", message: "" }).mockResolvedValueOnce({ state: "active", count: 1, message: "" });
    expect(await executeLauncherUpdate(input)).toMatchObject({ accepted: false, code: "active_work_blocked" });
    expect(input.prepare).toHaveBeenCalledOnce();
    expect(input.stopWorkspaces).not.toHaveBeenCalled();
  });

  it("only schedules after a successful normal stop", async () => {
    const input = updateInputs();
    input.stopWorkspaces.mockRejectedValue(new Error("stop refused"));
    await expect(executeLauncherUpdate(input)).rejects.toThrow("stop refused");
    expect(input.scheduleReplacement).not.toHaveBeenCalled();
    input.stopWorkspaces.mockResolvedValue(undefined);
    expect(await executeLauncherUpdate(input)).toMatchObject({ accepted: true });
    expect(input.scheduleReplacement).toHaveBeenCalledOnce();
  });

  it("wires the real IPC route through preparation and non-force shutdown", () => {
    const main = readFileSync(new URL("../src/main.ts", import.meta.url), "utf8");
    const update = main.slice(main.indexOf("async function restartLauncherToLatestBuild"), main.indexOf("async function exitAndRelaunchLauncherShell"));
    expect(update).toContain("executeLauncherUpdate");
    expect(update).toContain("ensureLatestLauncher");
    expect(update).toContain("stopMainRuntimeForApprovedShutdown");
    expect(update).toContain("stopIsolatedInstancesForApprovedShutdown");
    expect(update).not.toContain("bestEffortStopIsolatedInstancesForShutdown");
    expect(update).not.toContain('"force-stop"');
  });
});

describe("Launcher freshness is based on the real packaged shell", () => {
  const input = { raw: { current: true, runningShort: "wrong-head-label" }, packaged: true, activeWork: { state: "idle", message: "" } as ActiveWorkStatus, updating: false };
  it("never turns a failed inspection into an up-to-date verdict", () => {
    expect(projectLauncherUpdateFreshness(input)).toMatchObject({ current: null, updateAvailable: false, runningShort: "", activeWorkState: "idle" });
  });
  it("detects stale frontend bytes even when the Python process claims current", () => {
    expect(projectLauncherUpdateFreshness({ ...input, shell: { schemaVersion: 1, stale: true, reason: "frontend_content_mismatch", currentElectronTree: "c".repeat(40), packagedSourceCommit: "a".repeat(40), currentCommit: "b".repeat(40) } })).toMatchObject({ current: false, updateAvailable: true, runningShort: "a".repeat(12), headShort: "b".repeat(12) });
  });
  it("does not advertise an update when the current frontend could not be inspected", () => {
    expect(projectLauncherUpdateFreshness({ ...input, shell: { schemaVersion: 1, stale: true, reason: "frontend_inspection_failed", currentElectronTree: "a".repeat(40) } })).toMatchObject({ current: null, updateAvailable: false, shellStale: false });
  });
  it("only reports current after a verified source identity and surfaces refresh failures", () => {
    expect(projectLauncherUpdateFreshness({ ...input, shell: { schemaVersion: 1, stale: false, reason: "current", currentElectronTree: "a".repeat(40), refreshBlocked: true, refreshBlockedDetail: "package failed" } })).toMatchObject({ current: true, refreshError: "package failed" });
  });
});
