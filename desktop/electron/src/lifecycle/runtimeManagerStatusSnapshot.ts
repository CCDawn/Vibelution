import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import type { LauncherLifecycleResultSummary, LauncherStatusSummary } from "../protocol/launcherControlClient.js";
import { resolveRuntimeManagerDir } from "./projectStoragePaths.js";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readLifecycleResult(path: string): LauncherLifecycleResultSummary | null {
  try {
    const payload = JSON.parse(readFileSync(path, "utf8")) as unknown;
    if (!isRecord(payload)) {
      return null;
    }
    const commandId = typeof payload.commandId === "string" ? payload.commandId.trim() : "";
    if (!commandId) {
      return null;
    }
    const message = typeof payload.message === "string" && payload.message.trim() ? payload.message.trim() : "";
    return {
      commandId,
      completed: payload.completed === true,
      ok: payload.ok === true,
      ...(message ? { message } : {})
    };
  } catch {
    return null;
  }
}

function readRecentLifecycleResults(runtimeManagerDir: string): LauncherLifecycleResultSummary[] {
  const resultsDir = join(runtimeManagerDir, "results");
  if (!existsSync(resultsDir)) {
    return [];
  }
  let names: string[] = [];
  try {
    names = readdirSync(resultsDir).filter((name) => name.endsWith(".json"));
  } catch {
    return [];
  }
  // Result files are cmd_<ISO>_<suffix>.json; newest names sort last.
  const ranked = names.sort((left, right) => (left < right ? 1 : left > right ? -1 : 0)).slice(0, 32);
  return ranked.flatMap((name) => {
    const result = readLifecycleResult(join(resultsDir, name));
    return result ? [result] : [];
  });
}

export function readRuntimeManagerLauncherStatusSummary(workspaceRoot: string): LauncherStatusSummary {
  const runtimeManagerDir = resolveRuntimeManagerDir(workspaceRoot);
  const statePath = join(runtimeManagerDir, "state.json");
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
    lifecycleResults: readRecentLifecycleResults(runtimeManagerDir)
  };
}
