import type { ConversationMessage } from "../api/types";
import type { ActiveTurnLayerState } from "./chatActiveTurnLayer";
import {
  assistantFinalAnswerText,
  assistantReasoningText,
  assistantTurnIsStreaming,
} from "./chatTurnProtocol";

export type TokenSpeedSample = {
  sessionId: string;
  messageId: string;
  tokenCount: number;
  timestampMs: number;
};

export type TokenSpeedTrackerState = TokenSpeedSample & {
  tokensPerSecond: number | null;
  samples: TokenSpeedSample[];
};

const CJK_CHARACTER_PATTERN = /[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff\uac00-\ud7af]/u;
const MIN_SAMPLE_INTERVAL_MS = 250;
const SAMPLE_WINDOW_MS = 2000;
const STALE_AFTER_MS = 1500;

/** Only live generated text; snapshots establish a baseline, never a burst. */
export function tokenSpeedTextFromLayer(layer: ActiveTurnLayerState | undefined) {
  if (!layer || layer.status !== "running") return null;
  let boundary = -1;
  let latest: Extract<ActiveTurnLayerState["turnItems"][number], { type: "reasoning" | "agent_message" }> | undefined;
  for (const item of layer.turnItems) {
    if (item.type === "tool_call" && (item.status === "running" || item.status === "pending")) return null;
    if (item.type === "tool_call" || item.type === "retry") boundary = Math.max(boundary, item.sequence);
    if ((item.type === "reasoning" || item.type === "agent_message") && item.status !== "failed"
      && (!latest || item.sequence > latest.sequence)) latest = item;
  }
  return latest && latest.sequence > boundary
    ? { key: JSON.stringify([layer.turnId, latest.itemId]), text: latest.text }
    : null;
}

export function tokenSpeedValueAt(tracker: TokenSpeedTrackerState | null, nowMs: number): number | null {
  return tracker && nowMs >= tracker.timestampMs && nowMs - tracker.timestampMs <= STALE_AFTER_MS
    ? tracker.tokensPerSecond : null;
}

export function estimateGeneratedTokens(content: string): number {
  let cjkCharacters = 0;
  let otherCharacters = 0;

  for (const character of String(content ?? "").trim()) {
    if (/\s/u.test(character)) {
      continue;
    }
    if (CJK_CHARACTER_PATTERN.test(character)) {
      cjkCharacters += 1;
    } else {
      otherCharacters += 1;
    }
  }

  return cjkCharacters + Math.ceil(otherCharacters / 4);
}

export function latestStreamingAssistantMessage(
  messages: ConversationMessage[] | null | undefined,
): ConversationMessage | null {
  return [...(messages ?? [])].reverse().find((message) =>
    message.role === "assistant"
    && assistantTurnIsStreaming(message)
    && estimateGeneratedTokens(generatedTokenTextForMessage(message)) > 0
  ) ?? null;
}

export function generatedTokenTextForMessage(message: ConversationMessage | null | undefined): string {
  if (!message || message.role !== "assistant") {
    return "";
  }

  const parts = [
    assistantReasoningText(message),
    looksLikeAnswerOutput(assistantFinalAnswerText(message)) ? assistantFinalAnswerText(message) : "",
  ].filter(Boolean);

  return parts.join("\n");
}

export function tokenSpeedSampleFromMessages(
  sessionId: string | null | undefined,
  messages: ConversationMessage[] | null | undefined,
  sessionState: string | null | undefined,
  timestampMs: number,
): TokenSpeedSample | null {
  const normalizedSessionId = String(sessionId ?? "").trim();
  const normalizedState = String(sessionState ?? "").trim().toLowerCase();
  if (!normalizedSessionId) {
    return null;
  }

  const message = latestStreamingAssistantMessage(messages);
  if (!message) {
    return null;
  }
  const generatedText = generatedTokenTextForMessage(message);
  if (normalizedState !== "answering" && estimateGeneratedTokens(generatedText) <= 0) {
    return null;
  }

  const tokenCount = estimateGeneratedTokens(generatedText);
  if (tokenCount <= 0) {
    return null;
  }

  return {
    sessionId: normalizedSessionId,
    messageId: message.id,
    tokenCount,
    timestampMs,
  };
}

function looksLikeAnswerOutput(content: string): boolean {
  const normalized = String(content ?? "").trim();
  if (!normalized) {
    return false;
  }
  if (normalized.length > 160) {
    return true;
  }

  const lines = normalized.split("\n").map((line) => line.trim()).filter(Boolean);
  if (lines.length > 2) {
    return true;
  }

  return ![
    /^正在准备对话上下文/i,
    /^正在读取当前会话/i,
    /^当前会话或 Agent 并发槽暂满/i,
    /^当前 Agent 正在处理上一项任务/i,
    /^正在唤起对话 agent/i,
    /^正在恢复上一轮对话记忆/i,
    /^正在请求模型/i,
    /^正在准备继续推进下一步/i,
    /^Preparing the conversation context/i,
    /^Reading the current session/i,
    /^This session or Agent concurrency slot is busy/i,
    /^The agent is handling another task/i,
    /^Preparing the conversation agent/i,
    /^Restoring the previous conversation memory/i,
    /^Requesting the model/i,
    /^Preparing the next continuation step/i,
  ].some((pattern) => pattern.test(normalized));
}

export function updateTokenSpeedTracker(
  previous: TokenSpeedTrackerState | null,
  sample: TokenSpeedSample | null,
): TokenSpeedTrackerState | null {
  if (!sample) {
    return null;
  }
  if (
    !previous
    || previous.sessionId !== sample.sessionId
    || previous.messageId !== sample.messageId
    || sample.tokenCount < previous.tokenCount
    || sample.timestampMs < previous.timestampMs
  ) {
    return {
      ...sample,
      tokensPerSecond: null,
      samples: [sample],
    };
  }

  // React Query may publish a fresh session-detail object even when the
  // streaming assistant message did not gain any text. Its render-time sample
  // gets a later timestamp, but it conveys no new token-speed information.
  // Preserve the state reference so the caller's functional setState is a
  // no-op instead of feeding that observer notification back into React.
  if (sample.tokenCount === previous.tokenCount) {
    return previous;
  }

  if (sample.timestampMs - previous.timestampMs > STALE_AFTER_MS) {
    return { ...sample, tokensPerSecond: null, samples: [sample] };
  }
  const samples = [...previous.samples, sample]
    .filter(point => point.timestampMs >= sample.timestampMs - SAMPLE_WINDOW_MS).slice(-128);
  const first = samples[0];
  const elapsedMs = sample.timestampMs - first.timestampMs;
  return {
    ...sample,
    samples,
    tokensPerSecond: elapsedMs >= MIN_SAMPLE_INTERVAL_MS
      ? (sample.tokenCount - first.tokenCount) / (elapsedMs / 1000) : null,
  };
}
