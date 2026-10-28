import type { AssistantHostRequest } from "./assistantHost.js";

export const LAUNCHER_ASSISTANT_URL = "vibelution-launcher://launcher/launcher-assistant";

type Contents = { mainFrame: unknown; isDestroyed(): boolean };
type Sender = { sender: unknown; senderFrame?: { url: string } | null };
export type AssistantBridgeOwner = {
  contents: Contents;
  host: { start(): Promise<unknown>; request(payload: AssistantHostRequest): Promise<unknown>;
    snapshot?(): { state: string } };
  setExpanded(expanded: boolean): unknown;
  hide(): void;
  openLauncher?(): Promise<{ opened: boolean }>;
};

export function assertAssistantSender(event: Sender, contents: Contents): void {
  if (contents.isDestroyed() || event.sender !== contents || event.senderFrame !== contents.mainFrame
      || event.senderFrame?.url !== LAUNCHER_ASSISTANT_URL) {
    throw new Error("ASSISTANT_SENDER_FORBIDDEN");
  }
}

/** One owned main frame, a closed verb list, and no renderer host credential. */
export async function invokeAssistant(event: Sender, payload: unknown, owner: AssistantBridgeOwner): Promise<unknown> {
  assertAssistantSender(event, owner.contents);
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) throw new Error("ASSISTANT_REQUEST_INVALID");
  const request = payload as Record<string, unknown>;
  if (request.operation === "openLauncher") {
    if (Object.keys(request).length !== 1) throw new Error("ASSISTANT_REQUEST_INVALID");
    if (!owner.openLauncher) throw new Error("ASSISTANT_LAUNCHER_UNAVAILABLE");
    try { return await owner.openLauncher(); }
    catch { throw new Error("ASSISTANT_LAUNCHER_UNAVAILABLE"); }
  }
  if (request.operation === "hide") {
    if (Object.keys(request).length !== 1) throw new Error("ASSISTANT_REQUEST_INVALID");
    owner.hide();
    return { hidden: true };
  }
  if (request.operation === "setExpanded") {
    if (Object.keys(request).length !== 2 || typeof request.expanded !== "boolean") throw new Error("ASSISTANT_REQUEST_INVALID");
    return owner.setExpanded(request.expanded);
  }
  if (!["status", "detail", "dispatches", "config", "send", "uploadAttachment", "readAttachment", "stop", "continue", "curation", "curate", "approvals", "resolveApproval", "declineDispatchApproval", "operatorAsset", "computerState", "computerWindows", "computerGrant", "computerControl", "computerConfirm"].includes(String(request.operation))) {
    throw new Error("ASSISTANT_REQUEST_INVALID");
  }
  try {
    // A fresh invocation may recover a confirmed dead owner. Failed writes
    // are returned once; neither this bridge nor host.start replays them.
    // Confirmation can only settle an existing native waiter. Starting a new
    // host here would also wait behind migration admission and deadlock it.
    if (request.operation !== "computerConfirm"
      && !(request.operation === "computerState" && owner.host.snapshot?.().state === "ready")) await owner.host.start();
    return await owner.host.request(payload as AssistantHostRequest);
  } catch (error) {
    const code = error instanceof Error && /^ASSISTANT_[A-Z_]+$/.test(error.message)
      ? error.message : "ASSISTANT_REQUEST_FAILED";
    throw new Error(code);
  }
}
