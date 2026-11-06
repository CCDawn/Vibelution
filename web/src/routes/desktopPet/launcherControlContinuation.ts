import { LAUNCHER_ASSISTANT_CONTROL_CONTINUATION_MESSAGE, type LauncherAssistantControlContinuation } from "../../api/launcherAssistant";
import type { SessionDetail } from "../../api/types";
import { resolveSessionActivity } from "../sessionActivityState";
import type { LauncherAssistantSubmission } from "./launcherAssistantModel";

export const CONTROL_CONTINUATION_MESSAGE = LAUNCHER_ASSISTANT_CONTROL_CONTINUATION_MESSAGE;

export type LauncherControlOrigin = {
  agentId: string; sessionId: string; turnId: string; userMessageId: string; branchId: string;
};
export type LauncherControlIntent = { origin: LauncherControlOrigin; requestId: string; toolIds: string[]; pendingToolIds: string[] };
export type LauncherControlContext = { detail: SessionDetail | undefined; agentId: string; blocked: boolean };

function launcherControlTools(context: LauncherControlContext) {
  const detail = context.detail;
  const assistant = detail?.messages.at(-1);
  if (assistant?.role !== "assistant") return [];
  return assistant.turnItems.filter(item => item.type === "tool_call"
    && item.sessionId === detail?.id && item.turnId === assistant.turnId)
    .filter(item => item.type === "tool_call");
}
export function launcherControlToolWatermark(context: LauncherControlContext) {
  const tools = launcherControlTools(context);
  return { toolIds: tools.map(item => item.itemId || item.id).sort(),
    pendingToolIds: tools.filter(item => ["pending", "running"].includes(item.status)).map(item => item.itemId || item.id) };
}
function originalToolSucceeded(context: LauncherControlContext, pendingToolIds: string[]): boolean {
  return launcherControlTools(context).some(item => {
    if (!pendingToolIds.includes(item.itemId || item.id) || item.status !== "completed" || item.error) return false;
    // An authorization request can finish as a denied tool receipt after the
    // click. Only its exact structured native denial remains eligible.
    if (item.toolName === "personal_assistant_computer_observe_tool" && item.output && item.output.length <= 16_000) {
      try {
        const value: unknown = JSON.parse(item.output);
        if (value && typeof value === "object" && "ok" in value && value.ok === false
          && "reason" in value && value.reason === "authorization_required" && "status" in value && value.status === "blocked") return false;
      } catch { /* An uncertain result consumes the intent; never replay it. */ }
    }
    return true;
  });
}

/** Capture a native task, never infer one from a tool's prose or browser title. */
export function launcherControlOrigin({ detail, agentId, blocked }: LauncherControlContext): LauncherControlOrigin | null {
  if (blocked || !detail || !agentId || detail.agentId !== agentId || !detail.id
    || detail.provisionalTranscript || detail.selectedLightweight || detail.editResubmitProtection || detail.messageWindow?.hasLater
    || detail.queuedTurns?.length || detail.queueHold || detail.pendingQuestion) return null;
  const assistant = detail.messages.at(-1);
  const user = [...detail.messages].reverse().find(message => message.role === "user");
  if (!assistant || assistant.role !== "assistant" || !assistant.turnId || !user?.id
    || String(user.metadata?.turnId ?? user.metadata?.turn_id ?? "").trim() !== assistant.turnId) return null;
  const activity = resolveSessionActivity(detail);
  if (activity.execution === "running" ? detail.activeTurnId !== assistant.turnId
    : activity.execution !== "settled" || activity.outcome !== "completed"
      || detail.lastTurnTerminalTurnId !== assistant.turnId) return null;
  return { agentId, sessionId: detail.id, turnId: assistant.turnId, userMessageId: user.id,
    branchId: detail.activeBranchId || "" };
}

export function sameLauncherControlOrigin(a: LauncherControlOrigin, b: LauncherControlOrigin): boolean {
  return a.agentId === b.agentId && a.sessionId === b.sessionId && a.turnId === b.turnId
    && a.userMessageId === b.userMessageId && a.branchId === b.branchId;
}

/** Natural completion may advance head/sequence within the captured turn. */
export function launcherControlSubmission(intent: LauncherControlIntent, context: LauncherControlContext):
  { state: "stale" | "waiting" } | { state: "ready"; submission: LauncherAssistantSubmission } {
  const origin = launcherControlOrigin(context);
  if (!origin || !sameLauncherControlOrigin(intent.origin, origin)) return { state: "stale" };
  // If the original turn resumed its tools itself, it owns the continuation.
  if (launcherControlToolWatermark(context).toolIds.some(id => !intent.toolIds.includes(id))
    || originalToolSucceeded(context, intent.pendingToolIds)) return { state: "stale" };
  const detail = context.detail!;
  if (resolveSessionActivity(detail).execution === "running" || detail.activeTurnId === origin.turnId) return { state: "waiting" };
  if (!detail.activeLeafId || !Number.isSafeInteger(detail.ledgerSeq) || detail.ledgerSeq! < 1) return { state: "stale" };
  const controlContinuation: LauncherAssistantControlContinuation = {
    agentId: origin.agentId, sessionId: origin.sessionId, turnId: origin.turnId,
    headId: detail.activeLeafId, ledgerSeq: detail.ledgerSeq!,
  };
  return { state: "ready", submission: { message: CONTROL_CONTINUATION_MESSAGE, requestId: intent.requestId,
    preserveDraft: true, controlContinuation } };
}
