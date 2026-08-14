import { boundedDesktopControlFetch } from "./boundedFetch.js";
import { overlayLauncherWindowTruth, type LauncherWindowTruth } from "../windows/launcherWindowTruthOverlay.js";

export const LAUNCHER_IPC_HOST_NOT_READY = "LAUNCHER_IPC_HOST_NOT_READY";
export const LAUNCHER_IPC_UNSUPPORTED_PATH = "LAUNCHER_IPC_UNSUPPORTED_PATH";
export const LAUNCHER_IPC_INVALID_PAYLOAD = "LAUNCHER_IPC_INVALID_PAYLOAD";
export const LAUNCHER_IPC_HTTP_ERROR_PREFIX = "LAUNCHER_IPC_HTTP_";
export const LAUNCHER_IPC_NETWORK_ERROR = "LAUNCHER_IPC_NETWORK_ERROR";
export const LAUNCHER_IPC_LIFECYCLE_ERROR = "LAUNCHER_IPC_LIFECYCLE_ERROR";

const LIFECYCLE_PATHS = new Set(["start", "stop", "force-stop", "restart", "rebuild-and-start"]);
const BRANCH_INSTANCE_PATHS = new Set([
  "branch-instances/start",
  "branch-instances/stop",
  "branch-instances/force-stop",
  "branch-instances/restart"
]);

export type OrchestratedLifecycleResult = {
  schemaVersion: 1;
  accepted: boolean;
  operation: string;
  commandId?: string;
  message?: string;
  code?: string;
  activeWorkRuns?: unknown[];
};

export type OrchestratedBranchInstanceResult = {
  schemaVersion: 1;
  accepted: boolean;
  operation: string;
  instanceId?: string;
  port?: number;
  controlPort?: number;
  message?: string;
  code?: string;
  activeWorkRuns?: unknown[];
};

export type LauncherIpcInvokePayload = {
  schemaVersion: 1;
  path: string;
  init?: {
    method?: "GET" | "POST" | "PUT" | "DELETE";
    headers?: Record<string, string>;
    body?: unknown;
  };
};

export type LauncherIpcInvokeResult =
  | { ok: true; payload: unknown }
  | { ok: false; error: { code: string; message: string } };

export type LauncherIpcHostContext = {
  launcherOrigin: string;
  controlToken: string;
};

function launcherIpcError(code: string, message: string): LauncherIpcInvokeResult {
  return { ok: false, error: { code, message } };
}

function isLauncherApiPath(path: string): boolean {
  const raw = String(path || "").trim();
  if (!raw) {
    return false;
  }
  if (raw.includes("\\") || raw.includes("..") || raw.includes("//") || raw.includes("://")) {
    return false;
  }
  if (raw.startsWith("/") || raw.startsWith("?") || raw.startsWith("#")) {
    return false;
  }
  const firstSegment = raw.split("/")[0];
  const allowed = new Set([
    "status",
    "freshness",
    "start",
    "stop",
    "force-stop",
    "restart",
    "rebuild-and-start",
    "branch-instances",
    "settings",
    "developer-mode",
    "maintenance",
    "supervisor",
    "lifecycle-intents",
    "workbench-close-transactions",
    "desktop-actions",
    "desktop-sessions",
  ]);
  return allowed.has(firstSegment);
}

function normalizePayload(payload: LauncherIpcInvokePayload): LauncherIpcInvokePayload | null {
  if (!payload || typeof payload !== "object" || payload.schemaVersion !== 1) {
    return null;
  }
  const path = String(payload.path ?? "").trim();
  if (!path) {
    return null;
  }
  const init = payload.init && typeof payload.init === "object" ? payload.init : undefined;
  const method = (init?.method ?? "GET").toUpperCase() as "GET" | "POST" | "PUT" | "DELETE";
  if (!["GET", "POST", "PUT", "DELETE"].includes(method)) {
    return null;
  }
  return {
    schemaVersion: 1,
    path,
    ...(init ? { init: { ...init, method } } : { init: { method } }),
  };
}

async function readFailureDetail(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as unknown;
    if (typeof payload === "object" && payload !== null) {
      const record = payload as Record<string, unknown>;
      const detail = record.detail;
      if (typeof detail === "string" && detail.trim()) {
        return detail.trim();
      }
      if (typeof detail === "object" && detail !== null && typeof (detail as Record<string, unknown>).message === "string") {
        return String((detail as Record<string, unknown>).message).trim();
      }
      if (typeof record.message === "string" && record.message.trim()) {
        return record.message.trim();
      }
    }
  } catch {
    // ignore body parse failures
  }
  return `HTTP ${response.status}`;
}

export function createLauncherIpcHost(input: {
  resolveContext: () => Promise<LauncherIpcHostContext | null>;
  resolveWindowTruth?: () => LauncherWindowTruth;
  orchestrateLifecycle?: (operation: string, payload: LauncherIpcInvokePayload) => Promise<OrchestratedLifecycleResult>;
  orchestrateBranchInstance?: (operation: string, payload: LauncherIpcInvokePayload) => Promise<OrchestratedBranchInstanceResult>;
  fetchImpl?: typeof fetch;
  requestTimeoutMs?: number;
}) {
  const fetchImpl = input.fetchImpl ?? fetch;
  const resolveWindowTruth = input.resolveWindowTruth ?? (() => ({ workbench: null, instances: [] }));

  return {
    async invoke(payload: LauncherIpcInvokePayload): Promise<LauncherIpcInvokeResult> {
      const normalized = normalizePayload(payload);
      if (normalized === null) {
        return launcherIpcError(LAUNCHER_IPC_INVALID_PAYLOAD, "Launcher IPC payload must use schemaVersion 1.");
      }
      if (!isLauncherApiPath(normalized.path)) {
        return launcherIpcError(
          LAUNCHER_IPC_UNSUPPORTED_PATH,
          `Launcher IPC path is outside the /api/launcher control surface: ${normalized.path.slice(0, 80)}`,
        );
      }
      const context = await input.resolveContext();
      if (context === null) {
        return launcherIpcError(
          LAUNCHER_IPC_HOST_NOT_READY,
          "Launcher IPC control plane host is not ready.",
        );
      }
      if (LIFECYCLE_PATHS.has(normalized.path) && input.orchestrateLifecycle) {
        try {
          const result = await input.orchestrateLifecycle(normalized.path, normalized);
          return { ok: true, payload: result };
        } catch (error: unknown) {
          return launcherIpcError(
            LAUNCHER_IPC_LIFECYCLE_ERROR,
            error instanceof Error ? error.message : String(error)
          );
        }
      }
      if (BRANCH_INSTANCE_PATHS.has(normalized.path) && input.orchestrateBranchInstance) {
        try {
          const operation = normalized.path.split("/")[1];
          const result = await input.orchestrateBranchInstance(operation, normalized);
          return { ok: true, payload: result };
        } catch (error: unknown) {
          return launcherIpcError(
            LAUNCHER_IPC_LIFECYCLE_ERROR,
            error instanceof Error ? error.message : String(error)
          );
        }
      }
      const init = normalized.init ?? { method: "GET" };
      const method = init.method ?? "GET";
      const headers: Record<string, string> = {
        "X-Vibelution-Control-Token": context.controlToken,
        ...(init.headers ?? {}),
      };
      if (init.body !== undefined) {
        headers["Content-Type"] = headers["Content-Type"] ?? "application/json";
      }
      let response: Response;
      try {
        response = await boundedDesktopControlFetch({
          fetchImpl,
          resource: `${new URL(context.launcherOrigin).origin}/api/launcher/${normalized.path}`,
          operation: `launcher ipc ${normalized.path}`,
          requestTimeoutMs: input.requestTimeoutMs,
          init: {
            method,
            headers,
            body: init.body === undefined ? undefined : JSON.stringify(init.body),
          },
        });
      } catch (error: unknown) {
        return launcherIpcError(
          LAUNCHER_IPC_NETWORK_ERROR,
          error instanceof Error ? error.message : String(error),
        );
      }
      if (!response.ok) {
        return launcherIpcError(
          `${LAUNCHER_IPC_HTTP_ERROR_PREFIX}${response.status}`,
          await readFailureDetail(response),
        );
      }
      try {
        const payload = (await response.json()) as unknown;
        return {
          ok: true,
          payload: overlayLauncherWindowTruth(normalized.path, payload, resolveWindowTruth())
        };
      } catch (error: unknown) {
        return launcherIpcError(
          LAUNCHER_IPC_NETWORK_ERROR,
          error instanceof Error ? error.message : String(error),
        );
      }
    },
  };
}
