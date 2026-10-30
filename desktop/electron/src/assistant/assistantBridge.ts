import type { AssistantHostRequest } from "./assistantHost.js";

export const LAUNCHER_ASSISTANT_URL = "vibelution-launcher://launcher/launcher-assistant";

type Contents = { mainFrame: unknown; isDestroyed(): boolean };
type Sender = { sender: unknown; senderFrame?: { url: string } | null };
/**
 * Main-process identity gates held by the assistantInvoke registration site;
 * admission includes exact object identity. The Launcher gate additionally
 * checks its pinned frame URL. `contents` is the pet float's pinned
 * webContents (absent for host-direct callers).
 */
export type WorkbenchSenderGate = (sender: unknown) => boolean;
export type AssistantBridgeOwner = {
  contents?: Contents;
  host: { start(): Promise<unknown>; request(payload: AssistantHostRequest): Promise<unknown>;
    snapshot?(): { state: string } };
  setExpanded(expanded: boolean): unknown;
  hide(): void;
  openLauncher?(): Promise<{ opened: boolean }>;
  isWorkbenchSender?: WorkbenchSenderGate;
  isLauncherControlSender?: WorkbenchSenderGate;
};

export function assertAssistantSender(event: Sender, contents: Contents | undefined,
  isWorkbenchSender?: WorkbenchSenderGate, isLauncherControlSender?: WorkbenchSenderGate): void {
  if (contents && !contents.isDestroyed() && event.sender === contents
      && event.senderFrame === contents.mainFrame && event.senderFrame?.url === LAUNCHER_ASSISTANT_URL) return;
  if (acceptsRegisteredWindowSender(event, isWorkbenchSender)
    || acceptsRegisteredWindowSender(event, isLauncherControlSender)) return;
  throw new Error("ASSISTANT_SENDER_FORBIDDEN");
}

/**
 * Registered main windows (workbench main, launcher control) are admitted by
 * exact webContents identity on their own main frame. The registration-site
 * gate may impose further URL checks. A missing or misbehaving gate fails closed.
 */
function acceptsRegisteredWindowSender(event: Sender, gate?: WorkbenchSenderGate): boolean {
  if (!gate) return false;
  const sender: unknown = event.sender;
  if (!sender || typeof sender !== "object") return false;
  if (!event.senderFrame || event.senderFrame !== (sender as { mainFrame?: unknown }).mainFrame) return false;
  try { return gate(sender) === true; } catch { return false; }
}

/** One owned main frame, a closed verb list, and no renderer host credential. */
export async function invokeAssistant(event: Sender, payload: unknown, owner: AssistantBridgeOwner): Promise<unknown> {
  assertAssistantSender(event, owner.contents, owner.isWorkbenchSender, owner.isLauncherControlSender);
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
  if (!["status", "detail", "dispatches", "config", "send", "uploadAttachment", "readAttachment", "stop", "continue", "curation", "curate", "approvals", "resolveApproval", "previewDispatchApproval", "decideDispatchApproval", "declineDispatchApproval", "operatorAsset", "computerState", "computerWindows", "computerGrant", "computerControl", "computerConfirm", "panelSettings", "panelSettingsUpdate", "panelModelUpdate", "panelDialogue", "panelDialogueUpdate", "panelProposals", "panelProposalAccept", "panelProposalReject", "panelAffairs", "panelAffairAdd", "panelAffairComplete", "panelAffairCancel", "panelAffairReopen", "panelAffairDue"].includes(String(request.operation))) {
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
