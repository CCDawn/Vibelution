import type { ConversationMessage } from "../../api/types";
import {
  consolidateSessionTurnItemsV2,
  isSessionTurnItemV2,
  projectConversationMessageFromTurnItemsV2,
} from "../../routes/chatTurnProtocol";
import {
  isHotRestartResumeMessage,
  isRecoverySupersededPartial,
  isRuntimeNoticeMessage,
} from "./conversationMessagePredicates";
import { chronologicalConversationMessages, messageSequenceOrder } from "./conversationMessageOrder";

/**
 * The single display selection channel.
 *
 * "Which rows reach the screen" used to be decided in five independent places
 * (three predicates in the display projection, four de-dup passes on transcript
 * cells, protocol visibility, companion suppression). Each place invented its
 * own identity rule, which is exactly how one turn ended up painted twice.
 * This module collapses the selection half into a fixed four-stage pipeline
 * where every stage owns exactly one criterion:
 *
 *   canonical -> order -> fold -> suppress
 *
 * A stage may only remove rows or stabilise row identity. It never re-orders
 * meaning, rewrites text, or re-derives an identity that the protocol already
 * defines.
 */
export type ConversationDisplayStage =
  | "canonical"
  | "order"
  | "fold"
  | "suppress";

export type ConversationDisplayDiscardReason =
  | "runtime_notice"
  | "recovery_superseded"
  | "hot_restart_resume";

export type ConversationDisplayDecision = {
  stage: "suppress";
  messageId: string;
  role: ConversationMessage["role"];
  reason: ConversationDisplayDiscardReason;
};

export type ConversationDisplayStageTrace = {
  stage: ConversationDisplayStage;
  inputCount: number;
  outputCount: number;
};

export type ConversationDisplayPipelineResult = {
  messages: ConversationMessage[];
  decisions: ConversationDisplayDecision[];
  stages: ConversationDisplayStageTrace[];
};

/**
 * Ordered suppress rules. A row is dropped by the first rule that matches, so
 * the recorded reason is the specific reason it left the timeline.
 */
const SUPPRESS_RULES: ReadonlyArray<{
  reason: ConversationDisplayDiscardReason;
  matches: (message: ConversationMessage) => boolean;
}> = [
  { reason: "runtime_notice", matches: isRuntimeNoticeMessage },
  { reason: "recovery_superseded", matches: isRecoverySupersededPartial },
  { reason: "hot_restart_resume", matches: isHotRestartResumeMessage },
];

type AssistantConversationMessage = Extract<ConversationMessage, { role: "assistant" }>;

function isAssistantMessage(
  message: ConversationMessage,
): message is AssistantConversationMessage {
  return message.role === "assistant";
}

function displayTurnId(message: ConversationMessage) {
  const metadataTurnId = message.metadata?.turnId;
  if (typeof metadataTurnId === "string" && metadataTurnId.trim()) {
    return metadataTurnId.trim();
  }
  return message.role === "assistant" ? String(message.turnId ?? "").trim() : "";
}

function sequenceOrder(message: ConversationMessage) {
  const order = messageSequenceOrder(message);
  return Number.isFinite(order) ? order : Number.POSITIVE_INFINITY;
}

/**
 * One turn can persist as several assistant rows (durable segments, a resumed
 * segment, a re-journaled tail). Those rows carry disjoint V2 items from the
 * same turn, so painting them one by one repeats the whole turn. Fold them on
 * the item identity the protocol already defines — never on text, and never by
 * discarding a row.
 */
function foldSameTurnAssistantMessages(messages: ConversationMessage[]): ConversationMessage[] {
  const byTurn = new Map<string, AssistantConversationMessage[]>();
  for (const message of messages) {
    if (!isAssistantMessage(message)) {
      continue;
    }
    const turnId = displayTurnId(message);
    if (!turnId) {
      continue;
    }
    const bucket = byTurn.get(turnId);
    if (bucket) {
      bucket.push(message);
    } else {
      byTurn.set(turnId, [message]);
    }
  }

  const foldedByTurn = new Map<string, ConversationMessage>();
  for (const [turnId, bucket] of byTurn) {
    if (bucket.length < 2) {
      continue;
    }
    // Legacy rows without canonical V2 items carry no identity to fold on.
    // Leave them untouched instead of degrading them into one lossy row.
    const foldable = bucket.every((message) => (
      Array.isArray(message.turnItems)
      && message.turnItems.length > 0
      && message.turnItems.every(isSessionTurnItemV2)
    ));
    if (!foldable) {
      continue;
    }
    const ordered = [...bucket].sort((left, right) => {
      const leftOrder = sequenceOrder(left);
      const rightOrder = sequenceOrder(right);
      if (leftOrder === rightOrder) {
        return 0;
      }
      return leftOrder < rightOrder ? -1 : 1;
    });
    foldedByTurn.set(turnId, {
      ...ordered[0],
      turnItems: consolidateSessionTurnItemsV2(...ordered.map((message) => message.turnItems)),
    });
  }

  if (foldedByTurn.size === 0) {
    return messages;
  }

  const emitted = new Set<string>();
  const result: ConversationMessage[] = [];
  for (const message of messages) {
    if (message.role !== "assistant") {
      result.push(message);
      continue;
    }
    const turnId = displayTurnId(message);
    const folded = turnId ? foldedByTurn.get(turnId) : undefined;
    if (!folded) {
      result.push(message);
      continue;
    }
    if (emitted.has(turnId)) {
      continue;
    }
    emitted.add(turnId);
    result.push(folded);
  }
  return result;
}

/**
 * Run the whole display selection channel and report what each stage did.
 *
 * The returned `stages` and `decisions` exist so a repeated-projection report
 * can be answered with "which stage dropped or folded this row" instead of
 * another round of guessing across five filters.
 */
export function projectConversationDisplayPipeline(
  messages: ConversationMessage[],
): ConversationDisplayPipelineResult {
  const stages: ConversationDisplayStageTrace[] = [];
  const decisions: ConversationDisplayDecision[] = [];

  const canonical = messages.map(projectConversationMessageFromTurnItemsV2);
  stages.push({
    stage: "canonical",
    inputCount: messages.length,
    outputCount: canonical.length,
  });

  const ordered = chronologicalConversationMessages(canonical);
  stages.push({
    stage: "order",
    inputCount: canonical.length,
    outputCount: ordered.length,
  });

  const folded = foldSameTurnAssistantMessages(ordered);
  stages.push({
    stage: "fold",
    inputCount: ordered.length,
    outputCount: folded.length,
  });

  const visible: ConversationMessage[] = [];
  for (const message of folded) {
    const rule = SUPPRESS_RULES.find((candidate) => candidate.matches(message));
    if (rule) {
      decisions.push({
        stage: "suppress",
        messageId: message.id,
        role: message.role,
        reason: rule.reason,
      });
      continue;
    }
    visible.push(message);
  }
  stages.push({
    stage: "suppress",
    inputCount: folded.length,
    outputCount: visible.length,
  });

  return { messages: visible, decisions, stages };
}
