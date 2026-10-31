export type ComputerWindow = { selectionId: string; title: string; appName: string };
export type ComputerAuthorizationRequest = { id: string; agentId: string; sessionId: string; turnId: string };

export type ComputerState = {
  available: boolean;
  status: "idle" | "ready" | "working" | "waiting_confirmation" | "paused" | "manual" | "ended" | "error";
  message: string;
  grantId: string | null;
  window: ComputerWindow | null;
  pending: { id: string; action: string; targetLabel: string; text: string | null } | null;
  /** Operator-only hint; never grants access or contains window metadata. */
  authorizationRequest?: ComputerAuthorizationRequest | null;
};

export type ComputerControlAction = "pause" | "resume" | "takeover" | "return" | "end";
