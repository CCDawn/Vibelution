import { describe, expect, it } from "vitest";
import {
  buildShellRelaunchArgs,
  shouldEnsureResidentBackend
} from "../src/process/residentBackendStartup.js";

function startupInput(overrides: Partial<Parameters<typeof shouldEnsureResidentBackend>[0]> = {}) {
  return {
    smoke: false,
    assistantOnly: false,
    pendingOpenWorkbench: false,
    lifecycleCommand: "",
    controlPlaneReady: true,
    ...overrides
  };
}

describe("shouldEnsureResidentBackend", () => {
  it("starts a backend for a resident project shell that asked for no window", () => {
    // 2026-11-09: this is the exact relaunch shape that left the assistant
    // waiting on a dead port 8000 after a forced close.
    expect(shouldEnsureResidentBackend(startupInput())).toBe(true);
  });

  it("leaves the explicit open path alone", () => {
    expect(shouldEnsureResidentBackend(startupInput({ pendingOpenWorkbench: true }))).toBe(false);
  });

  it("leaves every explicit lifecycle command to its own handler", () => {
    for (const lifecycleCommand of ["start", "restart", "open", "stop", "status"]) {
      expect(shouldEnsureResidentBackend(startupInput({ lifecycleCommand }))).toBe(false);
    }
  });

  it("never starts a backend for shell-less surfaces", () => {
    expect(shouldEnsureResidentBackend(startupInput({ assistantOnly: true }))).toBe(false);
    expect(shouldEnsureResidentBackend(startupInput({ smoke: true }))).toBe(false);
    expect(shouldEnsureResidentBackend(startupInput({ controlPlaneReady: false }))).toBe(false);
  });
});

describe("buildShellRelaunchArgs", () => {
  it("restores the workbench intent a bare relaunch dropped", () => {
    expect(buildShellRelaunchArgs({
      argv: ["--workspace", "D:\\dev-projects\\Vibelution"],
      restoreWorkbench: true
    })).toEqual(["--workspace", "D:\\dev-projects\\Vibelution", "--open-workbench"]);
  });

  it("keeps every other switch untouched", () => {
    expect(buildShellRelaunchArgs({
      argv: ["--workspace", "D:\\w", "--local-debugging"],
      restoreWorkbench: true
    })).toEqual(["--workspace", "D:\\w", "--local-debugging", "--open-workbench"]);
  });

  it("does not duplicate an existing flag", () => {
    expect(buildShellRelaunchArgs({
      argv: ["--workspace", "D:\\w", "--open-workbench"],
      restoreWorkbench: true
    })).toEqual(["--workspace", "D:\\w", "--open-workbench"]);
  });

  it("drops a stale flag when the workbench should stay closed", () => {
    expect(buildShellRelaunchArgs({
      argv: ["--workspace", "D:\\w", "--open-workbench"],
      restoreWorkbench: false
    })).toEqual(["--workspace", "D:\\w"]);
  });
});
