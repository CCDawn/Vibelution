import type { ConversationMessage } from "../api/types";

export type TokenSpeedSample = {
  sessionId: string;
  messageId: string;
  tokenCount: number;
  timestampMs: number;
};

export type TokenSpeedTrackerState = TokenSpeedSample & {
  tokensPerSecond: number | null;
};

const CJK_CHARACTER_PATTERN = /[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff\uac00-\ud7af]/u;
const MIN_SAMPLE_INTERVAL_MS = 250;

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
    && Boolean(message.streaming)
    && estimateGeneratedTokens(generatedTokenTextForMessage(message)) > 0
  ) ?? null;
}

export function generatedTokenTextForMessage(message: ConversationMessage | null | undefined): string {
  if (!message || message.role !== "assistant") {
    return "";
  }

  const parts = [
    String(message.thought ?? "").trim(),
    looksLikeAnswerOutput(message.content) ? String(message.content ?? "").trim() : "",
    ...(message.toolCalls ?? []).map((toolCall) => stableToolArgumentsText(toolCall.arguments)),
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

function stableToolArgumentsText(value: Record<string, unknown> | undefined): string {
  if (!value || Object.keys(value).length === 0) {
    return "";
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
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
    /^当前 Agent 正在处理上一项任务/i,
    /^正在唤起对话 agent/i,
    /^正在恢复上一轮对话记忆/i,
    /^正在请求模型/i,
    /^正在准备继续推进下一步/i,
    /^Preparing the conversation context/i,
    /^Reading the current session/i,
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
  ) {
    return {
      ...sample,
      tokensPerSecond: null,
    };
  }

  const elapsedMs = sample.timestampMs - previous.timestampMs;
  const tokenDelta = sample.tokenCount - previous.tokenCount;
  if (elapsedMs < MIN_SAMPLE_INTERVAL_MS || tokenDelta <= 0) {
    return {
      ...sample,
      tokensPerSecond: previous.tokensPerSecond,
    };
  }

  return {
    ...sample,
    tokensPerSecond: tokenDelta / (elapsedMs / 1000),
  };
}
