import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import type { LauncherLifecycleResultSummary, LauncherStatusSummary } from "../protocol/launcherControlClient.js";
import { knownPidIsAlive } from "./mainLine/observation.js";
import { resolveLauncherRuntimeDir, resolveRuntimeManagerDir } from "./projectStoragePaths.js";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isSafeRuntimeManagerCommandId(commandId: string): boolean {
  return commandId.length > 0 && /^[A-Za-z0-9_-]+$/.test(commandId);
}

const CLOSING_PHASES = new Set(["closing", "stopping", "force_stopping"]);

function readLifecycleResult(path: string): LauncherLifecycleResultSummary | null {
  try {
    const payload = JSON.parse(readFileSync(path, "utf8")) as unknown;
    if (!isRecord(payload)) {
      return null;
    }
    const commandId = typeof payload.commandId === "string" ? payload.commandId.trim() : "";
    if (!commandId || !isSafeRuntimeManagerCommandId(commandId)) {
      return null;
    }
    const message = typeof payload.message === "string" && payload.message.trim() ? payload.message.trim() : "";
    const generationValue = Number(payload.generation);
    return {
      commandId,
      completed: payload.completed === true,
      ok: payload.ok === true,
      ...(message ? { message } : {}),
      ...(Number.isFinite(generationValue) && generationValue > 0 ? { generation: Math.trunc(generationValue) } : {})
    };
  } catch {
    return null;
  }
}

function readExactLifecycleResult(runtimeManagerDir: string, commandId: string): LauncherLifecycleResultSummary | null {
  if (!isSafeRuntimeManagerCommandId(commandId)) {
    return null;
  }
  return readLifecycleResult(join(runtimeManagerDir, "results", `${commandId}.json`));
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

function readJsonRecord(path: string): Record<string, unknown> | null {
  try {
    const payload = JSON.parse(readFileSync(path, "utf8")) as unknown;
    return isRecord(payload) ? payload : null;
  } catch {
    return null;
  }
}

function readElectronMainLineIntentCommandId(runtimeManagerDir: string): string {
  const payload = readJsonRecord(join(runtimeManagerDir, "main_line_intent.json"));
  if (!payload || payload.schemaVersion !== 1) {
    return "";
  }
  const operation = String(payload.operation || "").trim().toLowerCase();
  const commandId = String(payload.commandId || "").trim();
  if (payload.desiredState !== "open") {
    return "";
  }
  if (operation !== "start" && operation !== "restart" && operation !== "rebuild-and-start") {
    return "";
  }
  return isSafeRuntimeManagerCommandId(commandId) ? commandId : "";
}

type ElectronMainLineObservation = {
  present: boolean;
  backendAlive: boolean;
  desiredState: string;
  observedState: string;
  lifecycleConsistency: string;
  phase: string;
};

function isClosingPhase(value: string): boolean {
  return CLOSING_PHASES.has(value.trim().toLowerCase());
}

function readElectronMainLineObservation(workspaceRoot: string): ElectronMainLineObservation {
  const payload = readJsonRecord(join(resolveLauncherRuntimeDir(workspaceRoot), "state.json"));
  if (!payload || String(payload.lastSource || "").trim() !== "electron_main") {
    return {
      present: false,
      backendAlive: false,
      desiredState: "",
      observedState: "",
      lifecycleConsistency: "",
      phase: ""
    };
  }
  return {
    present: true,
    backendAlive: knownPidIsAlive(Number(payload.backendPid || 0)),
    desiredState: String(payload.desiredState || "").trim(),
    observedState: String(payload.observedState || "").trim(),
    lifecycleConsistency: String(payload.lifecycleConsistency || "").trim(),
    phase: String(payload.phase || "").trim()
  };
}

export function readRuntimeManagerLauncherStatusSummary(
  workspaceRoot: string,
  expectedCommandId?: string
): LauncherStatusSummary {
  const runtimeManagerDir = resolveRuntimeManagerDir(workspaceRoot);
  const statePath = join(runtimeManagerDir, "state.json");
  const raw = JSON.parse(readFileSync(statePath, "utf8")) as unknown;
  if (!isRecord(raw)) {
    throw new Error("runtime manager state snapshot is invalid");
  }
  const workbench = isRecord(raw.workbench) ? raw.workbench : {};
  const runtimeState = String(raw.runtimeState || "").trim().toLowerCase();
  const stateVersionValue = Number(raw.stateVersion ?? 0);
  const recent = readRecentLifecycleResults(runtimeManagerDir);
  const expected = String(expectedCommandId || "").trim();
  const exact = expected ? readExactLifecycleResult(runtimeManagerDir, expected) : null;
  const electron = readElectronMainLineObservation(workspaceRoot);
  const synthesized = (
    !exact
    && expected
    && electron.present
    && electron.backendAlive
    && readElectronMainLineIntentCommandId(runtimeManagerDir) === expected
  )
    ? { commandId: expected, completed: true, ok: true }
    : null;
  const matched = exact ?? synthesized;
  const lifecycleResults = matched
    ? [matched, ...recent.filter((item) => item.commandId !== matched.commandId)]
    : recent;
  const summary: LauncherStatusSummary = {
    overallState: runtimeState === "running" ? "ready" : runtimeState || "unknown",
    observedState: String(workbench.observedState || "").trim() || "unknown",
    lifecycleConsistency: String(workbench.lifecycleConsistency || "").trim() || "unknown",
    phase: String(workbench.phase || "").trim(),
    stateVersion: Number.isFinite(stateVersionValue) ? stateVersionValue : 0,
    backendHealthy: workbench.backendHealthy === true,
    backendPortListening: workbench.backendPortListening === true,
    lifecycleResults
  };
  if (!electron.present) {
    return summary;
  }
  // A registered Electron PID can still be alive after the backend has
  // stopped listening. Runtime Manager remains the health authority while a
  // close intent is settling.
  const electronClosingIntent = (
    electron.desiredState.toLowerCase() === "closed"
    && electron.observedState.length > 0
    && electron.observedState.toLowerCase() !== "closed"
  );
  const closing = isClosingPhase(summary.phase)
    || isClosingPhase(electron.phase)
    || electronClosingIntent;
  const electronPhase = electron.phase.toLowerCase();
  const projectedPhase = electronClosingIntent
    && electronPhase !== "failed"
    && !isClosingPhase(electronPhase)
    ? "closing"
    : electron.phase || summary.phase;
  const backendHealthy = electron.backendAlive && (!closing || summary.backendHealthy);
  const backendPortListening = electron.backendAlive && (!closing || summary.backendPortListening);
  return {
    ...summary,
    overallState: electron.backendAlive ? "ready" : summary.overallState,
    observedState: electron.observedState || summary.observedState,
    lifecycleConsistency: electron.backendAlive
      ? (electron.lifecycleConsistency || "browser_missing")
      : (electron.lifecycleConsistency || summary.lifecycleConsistency),
    phase: projectedPhase,
    backendHealthy,
    backendPortListening
  };
}
