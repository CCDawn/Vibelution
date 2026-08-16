import { readFileSync } from "node:fs";
import { join } from "node:path";

import type { LauncherStatusSummary } from "../protocol/launcherControlClient.js";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function readRuntimeManagerLauncherStatusSummary(workspaceRoot: string): LauncherStatusSummary {
  const statePath = join(workspaceRoot, ".runtime", "runtime-manager", "state.json");
  const raw = JSON.parse(readFileSync(statePath, "utf8")) as unknown;
  if (!isRecord(raw)) {
    throw new Error("runtime manager state snapshot is invalid");
  }
  const workbench = isRecord(raw.workbench) ? raw.workbench : {};
  const runtimeState = String(raw.runtimeState || "").trim().toLowerCase();
  const stateVersionValue = Number(raw.stateVersion ?? 0);
  return {
    overallState: runtimeState === "running" ? "ready" : runtimeState || "unknown",
    observedState: String(workbench.observedState || "").trim() || "unknown",
    lifecycleConsistency: String(workbench.lifecycleConsistency || "").trim() || "unknown",
    phase: String(workbench.phase || "").trim(),
    stateVersion: Number.isFinite(stateVersionValue) ? stateVersionValue : 0,
    backendHealthy: workbench.backendHealthy === true,
    backendPortListening: workbench.backendPortListening === true,
    lifecycleResults: []
  };
}
