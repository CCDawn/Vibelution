import { boundedDesktopControlFetch } from "./boundedFetch.js";

export type DesktopActionName =
  | "open_workbench"
  | "focus_workbench"
  | "close_workbench"
  | "restart_after_apply"
  | "resume_self_evolution"
  | "recover_after_crash"
  | "request_app_exit";

export type DesktopWindowOperation = "open_or_focus_workbench" | "focus_workbench" | "close_workbench" | "none";

export type DesktopAction = {
  actionId: string;
  intentId: string;
  action: DesktopActionName | string;
  status: "claimed";
  payload: Record<string, unknown>;
  claimedBy: string;
  leaseExpiresAt: string;
  claimAttempt: number;
};

export type DesktopActionRunResult =
  | {
      claimed: false;
    }
  | {
      claimed: true;
      actionId: string;
      action: string;
      status: "acked" | "failed";
    };

export type DesktopWindowOperations = {
  openOrFocusWorkbench(payload?: Record<string, unknown>): Promise<unknown>;
  focusWorkbench(): Promise<unknown>;
  closeWorkbench(payload: Record<string, unknown>): Promise<unknown>;
};

type DesktopActionEndpointTemplates = {
  claim: string;
  ack: string;
  fail: string;
};

export function desktopWindowOperationForAction(action: string): DesktopWindowOperation {
  if (action === "open_workbench") {
    return "open_or_focus_workbench";
  }
  if (action === "focus_workbench") {
    return "focus_workbench";
  }
  if (action === "close_workbench") {
    return "close_workbench";
  }
  return "none";
}

export function launcherDesktopActionEndpoints(launcherOrigin: string): DesktopActionEndpointTemplates {
  const origin = new URL(launcherOrigin).origin;
  return {
    claim: `${origin}/api/launcher/desktop-actions/claim`,
    ack: `${origin}/api/launcher/desktop-actions/{actionId}/ack`,
    fail: `${origin}/api/launcher/desktop-actions/{actionId}/fail`
  };
}

export async function fetchLauncherControlToken(input: {
  launcherOrigin: string;
  fetchImpl?: typeof fetch;
  requestTimeoutMs?: number;
}): Promise<string> {
  const response = await boundedDesktopControlFetch({
    fetchImpl: input.fetchImpl,
    resource: `${new URL(input.launcherOrigin).origin}/api/control-token`,
    operation: "launcher control token",
    requestTimeoutMs: input.requestTimeoutMs
  });
  if (!response.ok) {
    throw new Error(`launcher control token request failed: ${response.status}`);
  }
  const payload = (await response.json()) as { controlToken?: unknown };
  const token = typeof payload.controlToken === "string" ? payload.controlToken.trim() : "";
  if (!token) {
    throw new Error("launcher control token response is missing controlToken");
  }
  return token;
}

export async function claimDesktopAction(input: {
  launcherOrigin: string;
  controlToken: string;
  desktopSessionId: string;
  leaseSeconds: number;
  fetchImpl?: typeof fetch;
  requestTimeoutMs?: number;
}): Promise<DesktopAction | null> {
  const response = await boundedDesktopControlFetch({
    fetchImpl: input.fetchImpl,
    resource: launcherDesktopActionEndpoints(input.launcherOrigin).claim,
    operation: "desktop action claim",
    requestTimeoutMs: input.requestTimeoutMs,
    init: {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "X-Vibelution-Control-Token": input.controlToken
      },
      body: JSON.stringify({ desktopSessionId: input.desktopSessionId, leaseSeconds: input.leaseSeconds })
    }
  });
  if (!response.ok) {
    throw new Error(`desktop action claim failed: ${response.status}`);
  }
  const payload = (await response.json()) as DesktopAction | Record<string, never>;
  return Object.keys(payload).length === 0 ? null : (payload as DesktopAction);
}

export async function finishDesktopAction(input: {
  launcherOrigin: string;
  controlToken: string;
  actionId: string;
  desktopSessionId: string;
  status: "ack" | "fail";
  result: Record<string, unknown>;
  fetchImpl?: typeof fetch;
  requestTimeoutMs?: number;
}): Promise<void> {
  const template =
    input.status === "ack"
      ? launcherDesktopActionEndpoints(input.launcherOrigin).ack
      : launcherDesktopActionEndpoints(input.launcherOrigin).fail;
  const response = await boundedDesktopControlFetch({
    fetchImpl: input.fetchImpl,
    resource: template.replace("{actionId}", encodeURIComponent(input.actionId)),
    operation: `desktop action ${input.status}`,
    requestTimeoutMs: input.requestTimeoutMs,
    init: {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "X-Vibelution-Control-Token": input.controlToken
      },
      body: JSON.stringify({ desktopSessionId: input.desktopSessionId, result: input.result })
    }
  });
  if (!response.ok) {
    throw new Error(`desktop action ${input.status} failed: ${response.status}`);
  }
}

export async function runDesktopActionOnce(input: {
  launcherOrigin: string;
  controlToken: string;
  desktopSessionId: string;
  leaseSeconds: number;
  operations: DesktopWindowOperations;
  fetchImpl?: typeof fetch;
  requestTimeoutMs?: number;
}): Promise<DesktopActionRunResult> {
  const action = await claimDesktopAction(input);
  if (action === null) {
    return { claimed: false };
  }

  const targetDesktopSessionId = String(action.payload.desktopSessionId || "").trim();
  if (targetDesktopSessionId && targetDesktopSessionId !== input.desktopSessionId) {
    await finishDesktopAction({
      ...input,
      actionId: action.actionId,
      status: "fail",
      result: {
        reason: "desktop_action_target_mismatch",
        targetDesktopSessionId,
        desktopSessionId: input.desktopSessionId
      }
    });
    return { claimed: true, actionId: action.actionId, action: action.action, status: "failed" };
  }

  const operation = desktopWindowOperationForAction(action.action);
  if (operation === "none") {
    await finishDesktopAction({
      ...input,
      actionId: action.actionId,
      status: "fail",
      result: {
        reason: "unsupported_desktop_action",
        action: action.action
      }
    });
    return { claimed: true, actionId: action.actionId, action: action.action, status: "failed" };
  }

  try {
    const windowState = await executeDesktopWindowOperation(operation, input.operations, action.payload);
    await finishDesktopAction({
      ...input,
      actionId: action.actionId,
      status: "ack",
      result: { operation, windowState }
    });
    return { claimed: true, actionId: action.actionId, action: action.action, status: "acked" };
  } catch (error: unknown) {
    await finishDesktopAction({
      ...input,
      actionId: action.actionId,
      status: "fail",
      result: {
        reason: "desktop_action_execution_failed",
        action: action.action,
        error: error instanceof Error ? error.message.slice(0, 300) : String(error).slice(0, 300)
      }
    });
    return { claimed: true, actionId: action.actionId, action: action.action, status: "failed" };
  }
}

function executeDesktopWindowOperation(
  operation: Exclude<DesktopWindowOperation, "none">,
  operations: DesktopWindowOperations,
  payload: Record<string, unknown>
) {
  if (operation === "open_or_focus_workbench") {
    return operations.openOrFocusWorkbench(payload);
  }
  if (operation === "focus_workbench") {
    return operations.focusWorkbench();
  }
  return operations.closeWorkbench(payload);
}
