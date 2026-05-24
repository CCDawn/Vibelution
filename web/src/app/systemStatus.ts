import type { BackendHealth, RuntimeSummary, WorkRunSnapshot } from "../api/types";

export type SystemStatusTone = "idle" | "running" | "failed" | "caution";

export type FrontendSystemState = "connected" | "background" | "offline";
export type BackendSystemState = "checking" | "healthy" | "offline" | "unhealthy";
export type RuntimeControllerState = "managed" | "closing" | "unmanaged" | "failed";
export type ActiveWorkKind = "supervised" | "self" | "chat";

export type ActiveWorkIndicator = {
  kind: ActiveWorkKind;
  label: string;
  summary: string;
  status: string;
  runId: string;
  detail: string;
  count: number;
  overflowCount: number;
  tone: SystemStatusTone;
};

type RuntimeSnapshot = Pick<RuntimeSummary, "runtimeManager" | "workbench">;
type ActiveWorkRunSnapshot = Partial<WorkRunSnapshot> & Record<string, unknown>;
type RuntimeWorkSnapshot = {
  workRuns?: {
    active?: {
      chat_turn?: ActiveWorkRunSnapshot | null;
      self_evolution_run?: ActiveWorkRunSnapshot | null;
      supervised_evolution_run?: ActiveWorkRunSnapshot | null;
    } | null;
  } | null;
  taskSummary?: string | null;
  sessionTitle?: string | null;
  currentPhase?: string | null;
};

export function deriveFrontendSystemState({
  online,
  visible,
}: {
  online: boolean;
  visible: boolean;
}): FrontendSystemState {
  if (!online) {
    return "offline";
  }
  if (!visible) {
    return "background";
  }
  return "connected";
}

export function deriveBackendSystemState({
  isPending,
  hasData,
  isError,
  health,
}: {
  isPending: boolean;
  hasData: boolean;
  isError: boolean;
  health?: BackendHealth | null;
}): BackendSystemState {
  if (isPending && !hasData) {
    return "checking";
  }
  if (isError) {
    return "offline";
  }
  if (health?.status === "ok") {
    return "healthy";
  }
  return "unhealthy";
}

export function deriveRuntimeControllerState(runtime: RuntimeSnapshot | null | undefined): RuntimeControllerState {
  const managerRunning = Boolean(runtime?.runtimeManager?.running);
  const desiredState = String(runtime?.workbench?.desiredState ?? "closed").trim().toLowerCase();
  const observedState = String(runtime?.workbench?.observedState ?? "closed").trim().toLowerCase();
  const phase = String(runtime?.workbench?.phase ?? "").trim().toLowerCase();
  const failureMessage = String(runtime?.workbench?.failureMessage ?? "").trim();
  const browserManaged = Boolean(runtime?.workbench?.browserManaged);
  const lifecycleConsistency = String(runtime?.workbench?.lifecycleConsistency ?? "").trim().toLowerCase();
  const frontendOrphaned = Boolean(runtime?.workbench?.frontendOrphaned) || lifecycleConsistency === "orphaned_browser";

  if (frontendOrphaned || phase === "failed" || failureMessage) {
    return "failed";
  }
  if (desiredState === "closed" && observedState !== "closed") {
    return "closing";
  }
  if (managerRunning && browserManaged) {
    return "managed";
  }
  return "unmanaged";
}

export function deriveActiveWorkIndicator(
  runtime: RuntimeWorkSnapshot | null | undefined,
  lang: "zh" | "en" = "zh",
): ActiveWorkIndicator | null {
  const active = runtime?.workRuns?.active;
  if (!active) {
    return null;
  }

  const candidates = [
    buildActiveWorkCandidate("supervised", active.supervised_evolution_run, runtime, lang),
    buildActiveWorkCandidate("self", active.self_evolution_run, runtime, lang),
    buildActiveWorkCandidate("chat", active.chat_turn, runtime, lang),
  ].filter((item): item is Omit<ActiveWorkIndicator, "count" | "overflowCount"> => Boolean(item));

  if (!candidates.length) {
    return null;
  }

  return {
    ...candidates[0],
    count: candidates.length,
    overflowCount: Math.max(0, candidates.length - 1),
  };
}

export function frontendSystemTone(state: FrontendSystemState): SystemStatusTone {
  switch (state) {
    case "offline":
      return "failed";
    case "background":
      return "idle";
    default:
      return "running";
  }
}

export function backendSystemTone(state: BackendSystemState): SystemStatusTone {
  switch (state) {
    case "healthy":
      return "running";
    case "checking":
      return "idle";
    default:
      return "failed";
  }
}

export function runtimeControllerTone(state: RuntimeControllerState): SystemStatusTone {
  switch (state) {
    case "managed":
    case "closing":
      return "running";
    case "unmanaged":
      return "idle";
    default:
      return "failed";
  }
}

function buildActiveWorkCandidate(
  kind: ActiveWorkKind,
  run: ActiveWorkRunSnapshot | null | undefined,
  runtime: RuntimeWorkSnapshot,
  lang: "zh" | "en",
): Omit<ActiveWorkIndicator, "count" | "overflowCount"> | null {
  if (!run || typeof run !== "object") {
    return null;
  }

  const status = normalizeWorkRunStatus(run);
  if (isTerminalWorkRunStatus(status)) {
    return null;
  }

  const label = activeWorkKindLabel(kind, lang);
  const summary = activeWorkSummary(kind, run, runtime, lang);
  const runId = textValue(run.runId);
  const detailParts = [
    label,
    summary,
    status ? status.replaceAll("_", " ") : "",
    runId ? `id=${runId}` : "",
  ].filter(Boolean);

  return {
    kind,
    label,
    summary,
    status: status || "running",
    runId,
    detail: detailParts.join(" · "),
    tone: activeWorkTone(status),
  };
}

function normalizeWorkRunStatus(run: ActiveWorkRunSnapshot): string {
  return firstTextValue(run, ["status", "currentPhase", "phase", "runtimeStatus"]).toLowerCase();
}

function isTerminalWorkRunStatus(status: string): boolean {
  return new Set([
    "done",
    "completed",
    "success",
    "failed",
    "cancelled",
    "canceled",
    "stopped",
    "closed",
    "terminated",
    "error",
  ]).has(status);
}

function activeWorkTone(status: string): SystemStatusTone {
  if (["queued", "paused", "pause_requested", "pausing", "stopping"].includes(status)) {
    return "caution";
  }
  return "running";
}

function activeWorkKindLabel(kind: ActiveWorkKind, lang: "zh" | "en"): string {
  if (lang === "en") {
    return {
      supervised: "Supervised evolution",
      self: "Self evolution",
      chat: "Chat",
    }[kind];
  }
  return {
    supervised: "监督进化",
    self: "自进化",
    chat: "对话",
  }[kind];
}

function activeWorkSummary(
  kind: ActiveWorkKind,
  run: ActiveWorkRunSnapshot,
  runtime: RuntimeWorkSnapshot,
  lang: "zh" | "en",
): string {
  if (kind === "supervised") {
    return firstTextValue(run, [
      "currentTask",
      "latestMessage",
      "summary",
      "reason",
      "currentCaseScenario",
      "bundleName",
      "datasetName",
    ]) || (lang === "en" ? "Supervised run is active" : "监督任务正在运行");
  }

  if (kind === "self") {
    return firstTextValue(run, [
      "currentGoal",
      "goal",
      "latestMessage",
      "summary",
      "currentTask",
    ]) || (lang === "en" ? "Self-evolution pass is active" : "自进化任务正在运行");
  }

  return firstTextValue(run, ["userMessage", "summary", "currentTask"])
    || textValue(runtime.taskSummary)
    || textValue(runtime.sessionTitle)
    || (lang === "en" ? "Chat turn is active" : "对话正在运行");
}

function firstTextValue(source: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = textValue(source[key]);
    if (value) {
      return value;
    }
  }
  return "";
}

function textValue(value: unknown): string {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

export function lifecycleStateTone(state: string | null | undefined): SystemStatusTone {
  switch (String(state || "").trim().toLowerCase()) {
    case "ready":
    case "verified":
    case "running":
      return "running";
    case "closed":
    case "missing":
    case "unknown":
      return "idle";
    case "failed":
      return "failed";
    default:
      return "caution";
  }
}

export function lifecycleStateLabel(state: string, lang: "zh" | "en"): string {
  const normalized = String(state || "").trim().toLowerCase();
  const zh: Record<string, string> = {
    ready: "已开启",
    starting: "开启中",
    closing: "关闭中",
    closed: "已关闭",
    partial: "部分成立",
    failed: "异常",
    verified: "已验证",
    missing: "未观测到",
    unknown: "未知",
    running: "运行中",
  };
  const en: Record<string, string> = {
    ready: "Open",
    starting: "Starting",
    closing: "Closing",
    closed: "Closed",
    partial: "Partial",
    failed: "Failed",
    verified: "Verified",
    missing: "Missing",
    unknown: "Unknown",
    running: "Running",
  };
  return (lang === "en" ? en : zh)[normalized] || state;
}
