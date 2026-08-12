import { boundedDesktopControlFetch } from "./boundedFetch.js";

export type LauncherControlPostPath =
  | "/api/launcher/start"
  | "/api/launcher/stop"
  | "/api/launcher/restart"
  | "/api/launcher/rebuild-and-start"
  | "/api/launcher/force-stop";

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
  fetchImpl?: typeof fetch;
  requestTimeoutMs?: number;
}): Promise<void> {
  const headers: Record<string, string> = {
    "X-Vibelution-Control-Token": input.controlToken
  };
  if (input.trigger) {
    headers["X-Vibelution-Launcher-Trigger"] = input.trigger;
  }
  const response = await boundedDesktopControlFetch({
    fetchImpl: input.fetchImpl,
    resource: `${launcherOriginBase(input.launcherOrigin)}${input.path}`,
    operation: `launcher control ${input.path}`,
    requestTimeoutMs: input.requestTimeoutMs,
    init: {
      method: "POST",
      headers
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

export function formatLauncherStatusSummary(summary: LauncherStatusSummary): string {
  return `状态：${summary.overallState || "unknown"} / ${summary.observedState || "unknown"} / ${summary.lifecycleConsistency || "unknown"}`;
}
