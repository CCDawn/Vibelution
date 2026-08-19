import { boundedDesktopControlFetch } from "./boundedFetch.js";

export type LauncherControlPostPath =
  | "/api/launcher/start"
  | "/api/launcher/stop"
  | "/api/launcher/restart"
  | "/api/launcher/rebuild-and-start"
  | "/api/launcher/force-stop"
  | "/api/launcher/branch-instances/start"
  | "/api/launcher/branch-instances/stop";

export type TrayBranchInstance = {
  id: string;
  label: string;
  startable: boolean;
  stoppable: boolean;
};

export type BranchInstanceRecord = {
  id: string;
  path: string;
  slotKey: string;
  url: string;
  port: number;
  alive: boolean;
  current: boolean;
  checkedOut: boolean;
  kind: string;
};

export type LauncherStatusSummary = {
  overallState: string;
  observedState: string;
  lifecycleConsistency: string;
  phase: string;
  stateVersion: number;
  backendHealthy: boolean;
  backendPortListening: boolean;
  lifecycleResults: LauncherLifecycleResultSummary[];
};

export type LauncherLifecycleResultSummary = {
  commandId: string;
  completed: boolean;
  ok: boolean;
  message?: string;
  generation?: number;
};

function launcherOriginBase(launcherOrigin: string): string {
  return new URL(launcherOrigin).origin;
}

function readNestedString(payload: Record<string, unknown>, keys: string[]): string {
  let current: unknown = payload;
  for (const key of keys) {
    if (!isRecord(current)) {
      return "";
    }
    current = current[key];
  }
  return typeof current === "string" ? current.trim() : "";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function readNestedValue(payload: Record<string, unknown>, keys: string[]): unknown {
  let current: unknown = payload;
  for (const key of keys) {
    if (!isRecord(current)) {
      return undefined;
    }
    current = current[key];
  }
  return current;
}

function readLifecycleResults(payload: Record<string, unknown>): LauncherLifecycleResultSummary[] {
  const recent = readNestedValue(payload, ["controlPlaneEvidence", "results", "recent"]);
  if (!Array.isArray(recent)) {
    return [];
  }
  return recent.slice(0, 10).flatMap((item) => {
    if (!isRecord(item)) {
      return [];
    }
    const commandId = typeof item.commandId === "string" ? item.commandId.trim() : "";
    if (!commandId) {
      return [];
    }
    const message = typeof item.message === "string" && item.message.trim() ? item.message.trim() : "";
    return [{
      commandId,
      completed: item.completed === true,
      ok: item.ok === true,
      ...(message ? { message } : {})
    }];
  });
}

async function readFailureDetail(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as unknown;
    if (!isRecord(payload)) {
      return `HTTP ${response.status}`;
    }
    const detail = payload.detail;
    if (typeof detail === "string" && detail.trim()) {
      return detail.trim();
    }
    if (isRecord(detail) && typeof detail.message === "string" && detail.message.trim()) {
      return detail.message.trim();
    }
    if (typeof payload.message === "string" && payload.message.trim()) {
      return payload.message.trim();
    }
  } catch {
    // ignore body parse failures
  }
  return `HTTP ${response.status}`;
}

export async function postLauncherControl(input: {
  launcherOrigin: string;
  controlToken: string;
  path: LauncherControlPostPath;
  trigger?: string;
  body?: Record<string, unknown>;
  fetchImpl?: typeof fetch;
  requestTimeoutMs?: number;
}): Promise<void> {
  const headers: Record<string, string> = {
    "X-Vibelution-Control-Token": input.controlToken
  };
  if (input.trigger) {
    headers["X-Vibelution-Launcher-Trigger"] = input.trigger;
  }
  if (input.body) {
    headers["Content-Type"] = "application/json";
  }
  const response = await boundedDesktopControlFetch({
    fetchImpl: input.fetchImpl,
    resource: `${launcherOriginBase(input.launcherOrigin)}${input.path}`,
    operation: `launcher control ${input.path}`,
    requestTimeoutMs: input.requestTimeoutMs,
    init: {
      method: "POST",
      headers,
      body: input.body ? JSON.stringify(input.body) : undefined
    }
  });
  if (!response.ok) {
    throw new Error(await readFailureDetail(response));
  }
}

export async function fetchLauncherStatusSummary(input: {
  launcherOrigin: string;
  controlToken: string;
  fetchImpl?: typeof fetch;
  requestTimeoutMs?: number;
}): Promise<LauncherStatusSummary> {
  const response = await boundedDesktopControlFetch({
    fetchImpl: input.fetchImpl,
    resource: `${launcherOriginBase(input.launcherOrigin)}/api/launcher/status`,
    operation: "launcher status",
    requestTimeoutMs: input.requestTimeoutMs,
    init: {
      method: "GET",
      headers: {
        "X-Vibelution-Control-Token": input.controlToken
      }
    }
  });
  if (!response.ok) {
    throw new Error(await readFailureDetail(response));
  }
  const payload = (await response.json()) as Record<string, unknown>;
  const overallState =
    readNestedString(payload, ["overallState"]) ||
    readNestedString(payload, ["lifecycleProof", "overallState"]) ||
    "unknown";
  const observedState =
    readNestedString(payload, ["observedState"]) ||
    readNestedString(payload, ["workbench", "observedState"]) ||
    "unknown";
  const lifecycleConsistency =
    readNestedString(payload, ["lifecycleConsistency"]) ||
    readNestedString(payload, ["workbench", "lifecycleConsistency"]) ||
    "unknown";
  const phase = readNestedString(payload, ["phase"]) || readNestedString(payload, ["workbench", "phase"]);
  const stateVersionValue = Number(readNestedValue(payload, ["stateVersion"]) ?? 0);
  return {
    overallState,
    observedState,
    lifecycleConsistency,
    phase,
    stateVersion: Number.isFinite(stateVersionValue) ? stateVersionValue : 0,
    backendHealthy:
      readNestedValue(payload, ["projectBundle", "backend", "healthy"]) === true
      || readNestedValue(payload, ["workbench", "backendHealthy"]) === true,
    backendPortListening:
      readNestedValue(payload, ["projectBundle", "backend", "portListening"]) === true
      || readNestedValue(payload, ["workbench", "backendPortListening"]) === true,
    lifecycleResults: readLifecycleResults(payload)
  };
}

export function classifyTrayBranchInstances(payload: unknown): TrayBranchInstance[] {
  if (!isRecord(payload) || !Array.isArray(payload.items)) {
    return [];
  }
  const items: TrayBranchInstance[] = [];
  for (const raw of payload.items) {
    if (!isRecord(raw)) {
      continue;
    }
    const id = typeof raw.id === "string" ? raw.id.trim() : "";
    if (!id) {
      continue;
    }
    const shortName = typeof raw.shortName === "string" ? raw.shortName.trim() : "";
    const branch = typeof raw.branch === "string" ? raw.branch.trim() : "";
    const kind = typeof raw.kind === "string" ? raw.kind.trim() : "";
    const checkedOut = raw.checkedOut === true;
    const alive = raw.alive === true;
    const operable = checkedOut && kind !== "retired" && kind !== "local_branch";
    const runtime = isRecord(raw.runtime) ? raw.runtime : null;
    const lifecycleState = typeof runtime?.lifecycleState === "string" ? runtime.lifecycleState.trim() : "";
    const backend = isRecord(runtime?.backend) ? runtime.backend : null;
    const windowInfo = isRecord(runtime?.window) ? runtime.window : null;
    const live = alive
      || backend?.alive === true
      || backend?.listening === true
      || windowInfo?.open === true;
    const attention = lifecycleState === "error" || (lifecycleState === "partial" && !live);
    const transitional = lifecycleState === "starting" || lifecycleState === "stopping" || lifecycleState === "restarting";
    const stoppable = operable && !transitional && (live || attention);
    const startable = operable && !live && !attention && lifecycleState !== "starting";
    items.push({
      id,
      label: shortName || branch || id,
      startable,
      stoppable
    });
  }
  return items;
}

export type LauncherFreshness = {
  current: boolean | null;
  label: string;
  runningShort?: string;
  headShort?: string;
};

export async function fetchLauncherFreshness(input: {
  launcherOrigin: string;
  controlToken: string;
  fetchImpl?: typeof fetch;
  requestTimeoutMs?: number;
}): Promise<LauncherFreshness> {
  const response = await boundedDesktopControlFetch({
    fetchImpl: input.fetchImpl,
    resource: `${launcherOriginBase(input.launcherOrigin)}/api/launcher/freshness`,
    operation: "launcher freshness",
    requestTimeoutMs: input.requestTimeoutMs,
    init: {
      method: "GET",
      headers: {
        "X-Vibelution-Control-Token": input.controlToken
      }
    }
  });
  if (!response.ok) {
    throw new Error(await readFailureDetail(response));
  }
  const payload = (await response.json()) as Record<string, unknown>;
  const current = payload.current;
  return {
    current: current === true ? true : current === false ? false : null,
    label: typeof payload.label === "string" && payload.label.trim() ? payload.label.trim() : "Launcher 版本未知",
    runningShort: typeof payload.runningShort === "string" ? payload.runningShort : "",
    headShort: typeof payload.headShort === "string" ? payload.headShort : ""
  };
}

export async function fetchLauncherBranchInstances(input: {
  launcherOrigin: string;
  controlToken: string;
  fetchImpl?: typeof fetch;
  requestTimeoutMs?: number;
}): Promise<TrayBranchInstance[]> {
  return classifyTrayBranchInstances(await readLauncherBranchInstancesPayload(input));
}

export function parseBranchInstanceRecords(payload: unknown): BranchInstanceRecord[] {
  if (!isRecord(payload) || !Array.isArray(payload.items)) {
    return [];
  }
  const items: BranchInstanceRecord[] = [];
  for (const raw of payload.items) {
    if (!isRecord(raw)) {
      continue;
    }
    const id = typeof raw.id === "string" ? raw.id.trim() : "";
    if (!id) {
      continue;
    }
    const portValue = Number(raw.port || 0);
    items.push({
      id,
      path: typeof raw.path === "string" ? raw.path.trim() : "",
      slotKey: typeof raw.slotKey === "string" ? raw.slotKey.trim() : "",
      url: typeof raw.url === "string" ? raw.url.trim() : "",
      port: Number.isFinite(portValue) ? portValue : 0,
      alive: raw.alive === true,
      current: raw.current === true,
      checkedOut: raw.checkedOut === true,
      kind: typeof raw.kind === "string" ? raw.kind.trim() : ""
    });
  }
  return items;
}

export function matchBranchInstanceByProjectRoot(
  items: BranchInstanceRecord[],
  projectRoot: string
): BranchInstanceRecord | null {
  const wanted = normalizeMatchPath(projectRoot);
  if (!wanted) {
    return null;
  }
  for (const item of items) {
    if (normalizeMatchPath(item.slotKey) === wanted || normalizeMatchPath(item.path) === wanted) {
      return item;
    }
  }
  return null;
}

export async function fetchLauncherBranchInstanceRecords(input: {
  launcherOrigin: string;
  controlToken: string;
  fetchImpl?: typeof fetch;
  requestTimeoutMs?: number;
}): Promise<BranchInstanceRecord[]> {
  return parseBranchInstanceRecords(await readLauncherBranchInstancesPayload(input));
}

async function readLauncherBranchInstancesPayload(input: {
  launcherOrigin: string;
  controlToken: string;
  fetchImpl?: typeof fetch;
  requestTimeoutMs?: number;
}): Promise<unknown> {
  const response = await boundedDesktopControlFetch({
    fetchImpl: input.fetchImpl,
    resource: `${launcherOriginBase(input.launcherOrigin)}/api/launcher/branch-instances`,
    operation: "launcher branch instances",
    requestTimeoutMs: input.requestTimeoutMs,
    init: {
      method: "GET",
      headers: {
        "X-Vibelution-Control-Token": input.controlToken
      }
    }
  });
  if (!response.ok) {
    throw new Error(await readFailureDetail(response));
  }
  return response.json();
}

function normalizeMatchPath(value: string): string {
  return String(value || "")
    .trim()
    .replace(/\//g, "\\")
    .replace(/[\\/]+$/, "")
    .toLowerCase();
}

export function formatLauncherStatusSummary(summary: LauncherStatusSummary): string {
  return `状态：${summary.overallState || "unknown"} / ${summary.observedState || "unknown"} / ${summary.lifecycleConsistency || "unknown"}`;
}
