export type ComputerWindow = { selectionId: string; title: string; appName: string };
/** Legacy operator-only hint from the closed contract; the open service no
 * longer emits it and the shell keeps accepting it for old replays. */
export type ComputerAuthorizationRequest = { id: string; agentId: string; sessionId: string; turnId: string };

export type ComputerState = {
  available: boolean;
  status: "idle" | "ready" | "working" | "waiting_confirmation" | "paused" | "manual" | "ended" | "error";
  message: string;
  grantId: string | null;
  window: ComputerWindow | null;
  /** The action set is open (`launch`, `click_at`, `hotkey`, ...); unknown
   * actions are judged by the service, never by shell-side whitelists. */
  pending: { id: string; action: string; targetLabel: string; text: string | null } | null;
  /** Operator-only hint; never grants access or contains window metadata. */
  authorizationRequest?: ComputerAuthorizationRequest | null;
};

export type ComputerControlAction = "pause" | "resume" | "takeover" | "return" | "end";
