import type { ConversationMessage } from "../../api/types";

export type ConversationStreamingFramePaintMetrics = {
  sessionId: string;
  paintedAtMs: number;
  streamingMessageCount: number;
  renderedTextLength: number;
  scrollSignal: string;
  turnId?: string;
  ledgerSeq?: number;
  assistantDeltaAppliedAtMs?: number;
};

/** Preserve the identity of the frame actually rendered, including its local anchor. */
export function conversationStreamingFrameIdentity(message: ConversationMessage | undefined) {
  const turnId = message && "turnId" in message ? message.turnId ?? "" : "";
  const ledgerSeq = message?.metadata?.ledgerSeq;
  const rawTiming = message?.metadata?.assistantDeltaTiming;
  const timing = rawTiming && typeof rawTiming === "object" ? rawTiming as Record<string, unknown> : undefined;
  return {
    turnId,
    ledgerSeq: typeof ledgerSeq === "number" ? ledgerSeq : undefined,
    assistantDeltaAppliedAtMs: timing?.turnId === turnId && timing?.ledgerSeq === ledgerSeq
      && typeof timing?.appliedAtMs === "number" ? timing.appliedAtMs : undefined,
  };
}
