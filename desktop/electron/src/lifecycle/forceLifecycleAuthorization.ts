import { randomUUID } from "node:crypto";

import type { ActiveWorkProbeState, ActiveWorkStatus } from "../shutdown/shutdownCoordinator.js";

export type ForceLifecycleAuthorization = {
  requestId: string;
  instanceId: string;
  operation: "force-stop";
  operatorIntent: string;
  probeState: ActiveWorkProbeState;
  probeMessage: string;
};

export type PreconfirmedForceLifecycleAuthorization = {
  requestId: string;
  probeState: ActiveWorkProbeState;
  probeMessage?: string;
};

export class ForceLifecycleAuthorizationDeniedError extends Error {
  readonly code = "force_lifecycle_not_confirmed";
  readonly requestId: string;

  constructor(requestId: string) {
    super(`force lifecycle request ${requestId} was not confirmed`);
    this.name = "ForceLifecycleAuthorizationDeniedError";
    this.requestId = requestId;
  }
}

export function isForceLifecycleAuthorizationDenied(
  error: unknown
): error is ForceLifecycleAuthorizationDeniedError {
  return error instanceof ForceLifecycleAuthorizationDeniedError
    || (
      error instanceof Error
      && error.message.includes("force lifecycle request")
      && error.message.includes("was not confirmed")
    );
}

function errorMessage(error: unknown): string {
  return (error instanceof Error ? error.message : String(error)).trim() || "active-work probe failed";
}

export async function authorizeForceLifecycleOperation(input: {
  operation: string;
  instanceId: string;
  operatorIntent: string;
  preconfirmed?: PreconfirmedForceLifecycleAuthorization;
  probe: () => Promise<ActiveWorkStatus>;
  confirm: (authorization: ForceLifecycleAuthorization) => Promise<boolean>;
  record: (authorization: ForceLifecycleAuthorization) => Promise<void>;
  requestIdFactory?: () => string;
}): Promise<ForceLifecycleAuthorization | null> {
  if (input.operation !== "force-stop") {
    return null;
  }
  const instanceId = input.instanceId.trim();
  const operatorIntent = input.operatorIntent.trim();
  if (!instanceId || !operatorIntent) {
    throw new Error("force lifecycle authorization requires instanceId and operatorIntent");
  }

  let requestId: string;
  let status: ActiveWorkStatus;
  if (input.preconfirmed) {
    requestId = input.preconfirmed.requestId.trim();
    status = {
      state: input.preconfirmed.probeState,
      message: String(input.preconfirmed.probeMessage ?? "").trim()
    };
  } else {
    requestId = String((input.requestIdFactory ?? randomUUID)()).trim();
    try {
      status = await input.probe();
    } catch (error: unknown) {
      status = { state: "unknown", message: errorMessage(error) };
    }
  }
  if (!requestId) {
    throw new Error("force lifecycle authorization requires requestId");
  }

  const authorization: ForceLifecycleAuthorization = {
    requestId,
    instanceId,
    operation: "force-stop",
    operatorIntent,
    probeState: status.state,
    probeMessage: status.message
  };
  if (!input.preconfirmed && !(await input.confirm(authorization))) {
    throw new ForceLifecycleAuthorizationDeniedError(requestId);
  }
  await input.record(authorization);
  return authorization;
}
