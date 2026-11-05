import { isAssistantQueuedTurnRequest, type AssistantHostRequest } from "./assistantHost.js";

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

/** Read views wait this long for host.start() before falling through to the
 * host's ASSISTANT_NOT_READY fast path; writes still await the full recovery. */
const START_GRACE_READ_MS = 2_000;
/** Renderer read views that keep polling while a generation is starting. */
const READ_OPERATIONS = new Set(["status", "detail", "dispatches", "teamRuns", "config", "approvals", "curation", "assistantAvatar", "budgetParameters", "usageSummary"]);
/**
 * Closed verb list a renderer may dispatch through this bridge; must cover
 * every operation of AssistantHostRequest (assistantHost.ts) and is locked to
 * that union by tests/assistantBridge.test.ts. Bridge-local verbs
 * (openLauncher/hide/setExpanded) are handled above and are not part of it.
 * Every member is dispatched after a full host.start() recovery except the
 * READ_OPERATIONS subset, which gets a bounded grace instead.
 */
export const ASSISTANT_BRIDGE_OPERATIONS = ["status", "detail", "dispatches", "teamRuns", "setModel", "setManagementPermissionPreset", "budgetParameters", "setBudgetParameters", "usageSummary", "previewTaskCleanup", "executeTaskCleanup", "config", "send", "uploadAttachment", "upload_attachment", "readAttachment", "stop", "updateQueuedTurn", "removeQueuedTurn", "sendNowQueuedTurn", "continue", "switchHead", "regenerate", "guidance", "curation", "curate", "approvals", "resolveApproval", "previewDispatchApproval", "decideDispatchApproval", "declineDispatchApproval", "operatorAsset", "assistantAvatar", "computerState", "computerWindows", "computerGrant", "computerControl", "computerConfirm"];

function delay(ms: number): Promise<void> {
  return new Promise(done => {
    const timer: ReturnType<typeof setTimeout> = setTimeout(done, ms);
    timer.unref?.();
  });
}

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
  if (request.operation === "assistantAvatar" && Object.keys(request).length !== 1) throw new Error("ASSISTANT_REQUEST_INVALID");
  if (request.operation === "budgetParameters" && Object.keys(request).length !== 1) throw new Error("ASSISTANT_BUDGET_INVALID");
  if (request.operation === "usageSummary" && Object.keys(request).length !== 1) throw new Error("ASSISTANT_USAGE_INVALID");
  if (request.operation === "setBudgetParameters" && (Object.keys(request).length !== 3
    || !Number.isSafeInteger(request.revision) || (request.revision as number) < 0
    || request.maxCallsPerTurn !== null && (!Number.isSafeInteger(request.maxCallsPerTurn)
      || (request.maxCallsPerTurn as number) < 0 || (request.maxCallsPerTurn as number) > 200)))
    throw new Error("ASSISTANT_BUDGET_INVALID");
  if (request.operation === "setManagementPermissionPreset" && (Object.keys(request).length !== 3
    || typeof request.preset !== "string" || !["request_approval", "auto_review", "full_access"].includes(request.preset)
    || !Number.isSafeInteger(request.expectedRevision) || (request.expectedRevision as number) < 0))
    throw new Error("ASSISTANT_PERMISSION_INVALID");
  if (request.operation === "setModel" && (Object.keys(request).length !== 2
    || typeof request.modelId !== "string" || !/^[^\s\x00-\x1f\x7f]{1,200}(?![\s\S])/.test(request.modelId)))
    throw new Error("ASSISTANT_REQUEST_INVALID");
  if (["updateQueuedTurn", "removeQueuedTurn", "sendNowQueuedTurn"].includes(String(request.operation))
    && !isAssistantQueuedTurnRequest(request)) throw new Error("ASSISTANT_REQUEST_INVALID");
  if (!ASSISTANT_BRIDGE_OPERATIONS.includes(String(request.operation))) {
    throw new Error("ASSISTANT_REQUEST_INVALID");
  }
  try {
    // A fresh invocation may recover a confirmed dead owner. Failed writes
    // are returned once; neither this bridge nor host.start replays them.
    // Confirmation can only settle an existing native waiter. Starting a new
    // host here would also wait behind migration admission and deadlock it.
    if (request.operation !== "computerConfirm"
      && !(request.operation === "computerState" && owner.host.snapshot?.().state === "ready")) {
      const starting = owner.host.start();
      if (READ_OPERATIONS.has(String(request.operation))) {
        // Reads still trigger the same recovery but wait on it for a bounded
        // grace: a still-starting host fails fast below with ASSISTANT_NOT_READY
        // (the renderer's cold-start waiting state) instead of parking the
        // renderer on an unbudgeted start. The abandoned start keeps running.
        await Promise.race([starting, delay(START_GRACE_READ_MS)]);
      } else await starting;
    }
    return await owner.host.request(payload as AssistantHostRequest);
  } catch (error) {
    // The host passes host.py's attachment-read 404 through under its native
    // unprefixed code; admit it here too so the renderer can distinguish a
    // missing attachment, while every other failure still folds to one code.
    const code = error instanceof Error
      && (/^ASSISTANT_[A-Z_]+$/.test(error.message) || error.message === "ATTACHMENT_NOT_FOUND")
      ? error.message : "ASSISTANT_REQUEST_FAILED";
    throw new Error(code);
  }
}
