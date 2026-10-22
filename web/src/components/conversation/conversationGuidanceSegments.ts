import type { AssistantConversationTurn, ConversationMessage, SessionTurnItem } from "../../api/types/chat";
import { assistantTurnIsInFlight } from "../../routes/chatTurnProtocol";
import { sessionTurnItemOrderSequence } from "../../agent-thread/turnItemOrder";
import { isSteerGuidanceMessage } from "./conversationMessagePredicates";

type Guide = Extract<ConversationMessage, { role: "user" }>;
type Boundary = { guide: Guide; sequence: number };

function positiveSequence(value: unknown): number | undefined {
  const sequence = typeof value === "number" ? value : Number(value);
  return Number.isSafeInteger(sequence) && sequence > 0 ? sequence : undefined;
}

function guidanceTurnId(message: ConversationMessage): string {
  return String(message.metadata?.turnId ?? "").trim();
}

export function guidanceDisplayState(message: ConversationMessage): "pending" | "drained" | "received" {
  const submitted = positiveSequence(message.metadata?.guidanceSequence);
  const consumed = positiveSequence(message.metadata?.guidanceConsumedSequence);
  if (message.metadata?.guidanceState === "drained" && submitted && consumed && consumed > submitted) {
    return "drained";
  }
  return message.metadata?.guidanceState === "pending" ? "pending" : "received";
}

function guideBoundary(guide: Guide): number | undefined {
  if (guidanceDisplayState(guide) === "drained") {
    return positiveSequence(guide.metadata?.guidanceConsumedSequence);
  }
  // Without a drain receipt this input has no confirmed execution boundary.
  // Keep it after current work even when a stop/failure settles the turn.
  return undefined;
}

function segmentMessage(
  source: AssistantConversationTurn,
  turnItems: SessionTurnItem[],
  key: string,
  last: boolean,
): AssistantConversationTurn {
  return {
    ...source,
    // Only the final segment is an actionable canonical message. Its node/id
    // still target the original backend answer; the other ids are view-only.
    id: last ? source.id : `${source.turnId}-guidance-segment:${key}`,
    status: last ? source.status : "completed",
    nodeId: last ? source.nodeId : undefined,
    branch: last ? source.branch : undefined,
    usageStats: last ? source.usageStats : undefined,
    turnItems,
    metadata: {
      ...source.metadata,
      ...(!last ? { kind: "guidance_work_segment" } : {}),
      guidanceSegmentKey: key,
      guidanceSegmentIsLast: last,
    },
  };
}

function splitTurn(source: AssistantConversationTurn, guides: Guide[]): ConversationMessage[] {
  const running = assistantTurnIsInFlight(source);
  const boundaries: Boundary[] = [];
  const waiting: Guide[] = [];
  for (const guide of guides) {
    const sequence = guideBoundary(guide);
    if (sequence === undefined) waiting.push(guide);
    else boundaries.push({ guide, sequence });
  }
  boundaries.sort((left, right) => left.sequence - right.sequence);
  if (!boundaries.length) return [source, ...waiting];

  const buckets: SessionTurnItem[][] = Array.from({ length: boundaries.length + 1 }, () => []);
  for (const item of source.turnItems) {
    // Revisions update content/status without changing where work began. The
    // server persists creation anchors for provisional as well as native items.
    const sequence = sessionTurnItemOrderSequence(item);
    const index = boundaries.filter((boundary) => sequence > boundary.sequence).length;
    buckets[index].push(item);
  }
  // A stop/failure can settle after the guide was drained but before another
  // item arrived. Keep the canonical actions/status on the last real segment.
  const lastVisibleIndex = running ? buckets.length - 1
    : buckets.reduce((last, items, index) => items.length ? index : last, -1);
  const result: ConversationMessage[] = [];
  buckets.forEach((items, index) => {
    if (index > 0) result.push(boundaries[index - 1].guide);
    const last = index === lastVisibleIndex;
    if (!items.length && !(last && running)) return;
    const trigger = boundaries[index - 1]?.guide;
    const key = trigger ? String(trigger.metadata?.guidanceEventId ?? trigger.id) : "initial";
    result.push(segmentMessage(source, items, key, last));
  });
  return [...result, ...waiting];
}

/**
 * Render-only work segments (Codex committed input / ZCode workSegments).
 * Fold item revisions first, then cut on durable guide boundaries. No Session,
 * Turn, Journal item, or model-history message is created or changed here.
 */
export function projectGuidanceWorkSegments(messages: ConversationMessage[]): ConversationMessage[] {
  const guidesByTurn = new Map<string, Guide[]>();
  for (const message of messages) {
    if (message.role !== "user" || !isSteerGuidanceMessage(message)
      || !positiveSequence(message.metadata?.guidanceSequence)) continue;
    const turnId = guidanceTurnId(message);
    if (!turnId) continue;
    const guides = guidesByTurn.get(turnId) ?? [];
    guides.push(message);
    guidesByTurn.set(turnId, guides);
  }
  if (!guidesByTurn.size) return messages;

  const replacements = new Map<ConversationMessage, ConversationMessage[]>();
  const removed = new Set<ConversationMessage>();
  for (const source of messages) {
    if (source.role !== "assistant") continue;
    const guides = guidesByTurn.get(source.turnId);
    if (!guides?.length) continue;
    guides.sort((left, right) => Number(left.metadata?.guidanceSequence) - Number(right.metadata?.guidanceSequence));
    const first = messages.find((message) => message === source || guides.includes(message as Guide))!;
    replacements.set(first, splitTurn(source, guides));
    removed.add(source);
    guides.forEach((guide) => removed.add(guide));
  }
  return messages.flatMap((message) => replacements.get(message) ?? (removed.has(message) ? [] : [message]));
}

/** Waiting guides share the live region so they cannot virtualize growing work. */
export function conversationLiveTailStartIndex(messages: ConversationMessage[]): number {
  let index = messages.length;
  let turnId = "";
  let hasLiveAssistant = false;
  while (index > 0) {
    const message = messages[index - 1];
    const nextTurn = message.role === "assistant" ? message.turnId : guidanceTurnId(message);
    const live = assistantTurnIsInFlight(message);
    const waiting = isSteerGuidanceMessage(message) && guidanceDisplayState(message) === "pending";
    if ((!live && !waiting) || !nextTurn || (turnId && turnId !== nextTurn)) break;
    turnId = nextTurn;
    hasLiveAssistant ||= live;
    index -= 1;
  }
  return hasLiveAssistant ? index : messages.length;
}
