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

export type LauncherStatusSummary = {
  overallState: string;
  observedState: string;
  lifecycleConsistency: string;
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
  return { overallState, observedState, lifecycleConsistency };
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
    const startable = checkedOut && !alive && kind !== "retired" && kind !== "local_branch";
    items.push({
      id,
      label: shortName || branch || id,
      startable,
      stoppable: alive
    });
  }
  return items;
}

export async function fetchLauncherBranchInstances(input: {
  launcherOrigin: string;
  controlToken: string;
  fetchImpl?: typeof fetch;
  requestTimeoutMs?: number;
}): Promise<TrayBranchInstance[]> {
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
  return classifyTrayBranchInstances(await response.json());
}

export function formatLauncherStatusSummary(summary: LauncherStatusSummary): string {
  return `状态：${summary.overallState || "unknown"} / ${summary.observedState || "unknown"} / ${summary.lifecycleConsistency || "unknown"}`;
}
