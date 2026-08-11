import type { ManagedWindowState } from "./windowProviderTypes.js";
import { boundedDesktopControlFetch } from "../protocol/boundedFetch.js";

export type DesktopSessionRegistration = {
  desktopSessionId: string;
  revision: number;
};

export class DesktopSessionConflictError extends Error {
  readonly code: string;
  readonly actualRevision: number;

  constructor(message: string, code: string, actualRevision = 0) {
    super(message);
    this.name = "DesktopSessionConflictError";
    this.code = code;
    this.actualRevision = actualRevision;
  }
}

export async function registerDesktopSession(input: {
  launcherOrigin: string;
  controlToken: string;
  desktopSessionId: string;
  workspaceRoot: string;
  capabilities: string[];
  fetchImpl?: typeof fetch;
  requestTimeoutMs?: number;
}): Promise<DesktopSessionRegistration> {
  const response = await boundedDesktopControlFetch({
    fetchImpl: input.fetchImpl,
    resource: `${new URL(input.launcherOrigin).origin}/api/launcher/desktop-sessions`,
    operation: "desktop session registration",
    requestTimeoutMs: input.requestTimeoutMs,
    init: {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "X-Vibelution-Control-Token": input.controlToken
      },
      body: JSON.stringify({
        desktopSessionId: input.desktopSessionId,
        provider: "electron",
        workspaceRoot: input.workspaceRoot,
        capabilities: input.capabilities
      })
    }
  });
  if (!response.ok) {
    throw new Error(`desktop session registration failed: ${response.status}`);
  }
  return (await response.json()) as DesktopSessionRegistration;
}

export async function heartbeatDesktopSession(input: {
  launcherOrigin: string;
  controlToken: string;
  desktopSessionId: string;
  revision: number;
  fetchImpl?: typeof fetch;
  requestTimeoutMs?: number;
}): Promise<DesktopSessionRegistration> {
  const response = await boundedDesktopControlFetch({
    fetchImpl: input.fetchImpl,
    resource: `${new URL(input.launcherOrigin).origin}/api/launcher/desktop-sessions/${encodeURIComponent(input.desktopSessionId)}/heartbeat`,
    operation: "desktop session heartbeat",
    requestTimeoutMs: input.requestTimeoutMs,
    init: {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "X-Vibelution-Control-Token": input.controlToken
      },
      body: JSON.stringify({ revision: input.revision })
    }
  });
  await throwDesktopSessionRequestError(response, "heartbeat");
  return (await response.json()) as DesktopSessionRegistration;
}

export async function closeDesktopSession(input: {
  launcherOrigin: string;
  controlToken: string;
  desktopSessionId: string;
  revision: number;
  fetchImpl?: typeof fetch;
  requestTimeoutMs?: number;
}): Promise<DesktopSessionRegistration> {
  const response = await boundedDesktopControlFetch({
    fetchImpl: input.fetchImpl,
    resource: `${new URL(input.launcherOrigin).origin}/api/launcher/desktop-sessions/${encodeURIComponent(input.desktopSessionId)}`,
    operation: "desktop session close",
    requestTimeoutMs: input.requestTimeoutMs,
    init: {
      method: "DELETE",
      headers: {
        "content-type": "application/json",
        "X-Vibelution-Control-Token": input.controlToken
      },
      body: JSON.stringify({ revision: input.revision })
    }
  });
  await throwDesktopSessionRequestError(response, "close");
  return (await response.json()) as DesktopSessionRegistration;
}

export async function reportDesktopWindowState(input: {
  launcherOrigin: string;
  controlToken: string;
  desktopSessionId: string;
  role: "launcher" | "workbench";
  revision: number;
  state: ManagedWindowState;
  fetchImpl?: typeof fetch;
  requestTimeoutMs?: number;
}): Promise<DesktopSessionRegistration> {
  const response = await boundedDesktopControlFetch({
    fetchImpl: input.fetchImpl,
    resource: `${new URL(input.launcherOrigin).origin}/api/launcher/desktop-sessions/${encodeURIComponent(input.desktopSessionId)}/windows/${input.role}`,
    operation: "desktop session window update",
    requestTimeoutMs: input.requestTimeoutMs,
    init: {
      method: "PUT",
      headers: {
        "content-type": "application/json",
        "X-Vibelution-Control-Token": input.controlToken
      },
      body: JSON.stringify({
        revision: input.revision,
        provider: input.state.provider,
        open: input.state.open,
        focused: input.state.focused,
        windowId: input.state.windowId,
        rendererProcessId: input.state.rendererProcessId,
        url: input.state.url
      })
    }
  });
  await throwDesktopSessionRequestError(response, "window update");
  return (await response.json()) as DesktopSessionRegistration;
}

async function throwDesktopSessionRequestError(response: Response, operation: string): Promise<void> {
  if (response.ok) {
    return;
  }
  let payload: Record<string, unknown> = {};
  try {
    const candidate = await response.json();
    const detail = candidate && typeof candidate === "object" ? (candidate as { detail?: unknown }).detail : null;
    payload = detail && typeof detail === "object" ? (detail as Record<string, unknown>) : {};
  } catch {
    payload = {};
  }
  const code = String(payload.code ?? "desktop_session_request_failed");
  const actualRevision = Number(payload.actualDesktopSessionRevision ?? 0);
  if (response.status === 409) {
    throw new DesktopSessionConflictError(
      String(payload.message ?? `desktop session ${operation} conflict`),
      code,
      Number.isFinite(actualRevision) ? actualRevision : 0
    );
  }
  throw new Error(`desktop session ${operation} failed: ${response.status}`);
}
