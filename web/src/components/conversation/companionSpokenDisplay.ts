import type { ConversationMessage } from "../../api/types";
import {
  consolidateSessionTurnItemsV2,
  isFinalAnswerTurnItem,
} from "../../routes/chatTurnProtocol";

const SPOKEN_EDGE = /^[\s,，.。!！?？、:：;；\-—~～]+/u;
const MIN_CONTAINED_REPEAT = 40;

export function normalizeCompanionSpeech(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

/**
 * One companion turn can carry several final-answer items. Keep a single
 * spoken text: a later item that only extends an earlier one replaces it,
 * and unrelated sentences stay together in that one text.
 */
export function collapseCompanionSpokenTexts(parts: readonly string[]): string {
  let current = "";
  for (const part of parts) {
    const piece = part.trim();
    if (!piece) {
      continue;
    }
    if (!current) {
      current = piece;
      continue;
    }
    const richer = preferRicherSpeech(current, piece);
    current = richer ?? `${current}\n\n${piece}`;
  }
  return current;
}

export function companionMessageSpokenText(message: ConversationMessage): string {
  if (message.role !== "assistant") {
    return "";
  }
  const parts = consolidateSessionTurnItemsV2(message.turnItems)
    .filter(isFinalAnswerTurnItem)
    .map((item) => item.text);
  return collapseCompanionSpokenTexts(parts);
}

export function companionTurnHasVisibleError(message: ConversationMessage): boolean {
  return message.role === "assistant" && message.turnItems.some((item) => item.type === "error");
}

/** Speech already shown by the nearest earlier companion reply, before this row. */
export function previousCompanionSpokenText(
  messages: readonly ConversationMessage[],
  index: number,
): string {
  for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
    const message = messages[cursor];
    if (!message) {
      continue;
    }
    if (message.role === "user") {
      return "";
    }
    if (message.role !== "assistant") {
      continue;
    }
    const spoken = companionMessageSpokenText(message);
    if (spoken) {
      return spoken;
    }
  }
  return "";
}

/**
 * Follow-up turns are real replies. When one only repeats the previous
 * companion bubble, keep the new words and drop the repeated part.
 */
export function companionUnrepeatedSpeech(previous: string, current: string): string {
  const next = current.trim();
  const prev = previous.trim();
  if (!next) {
    return "";
  }
  if (!prev) {
    return next;
  }
  const normPrev = normalizeCompanionSpeech(prev);
  const normNext = normalizeCompanionSpeech(next);
  if (!normNext || normNext === normPrev) {
    return "";
  }
  if (normNext.startsWith(normPrev)) {
    return stripNormalizedPrefix(next, normPrev).replace(SPOKEN_EDGE, "").trim();
  }
  if (normPrev.length >= MIN_CONTAINED_REPEAT && normNext.includes(normPrev)) {
    return removeNormalizedSpan(next, normPrev).replace(SPOKEN_EDGE, "").trim();
  }
  if (normNext.length >= MIN_CONTAINED_REPEAT && normPrev.includes(normNext)) {
    return "";
  }
  return next;
}

function preferRicherSpeech(current: string, piece: string): string | null {
  const earlier = normalizeCompanionSpeech(current);
  const later = normalizeCompanionSpeech(piece);
  if (!later) {
    return current;
  }
  if (!earlier) {
    return piece;
  }
  if (later === earlier || later.startsWith(earlier)) {
    return piece.length >= current.length ? piece : current;
  }
  if (earlier.startsWith(later) && later.length >= MIN_CONTAINED_REPEAT) {
    return current;
  }
  if (earlier.length >= MIN_CONTAINED_REPEAT && later.includes(earlier)) {
    return piece;
  }
  if (later.length >= MIN_CONTAINED_REPEAT && earlier.includes(later)) {
    return current;
  }
  return null;
}

function stripNormalizedPrefix(original: string, normalizedPrefix: string): string {
  let rawIndex = 0;
  let prefixIndex = 0;
  while (rawIndex < original.length && prefixIndex < normalizedPrefix.length) {
    const rawChar = original[rawIndex] ?? "";
    const prefixChar = normalizedPrefix[prefixIndex] ?? "";
    if (/\s/u.test(rawChar)) {
      if (prefixChar !== " ") {
        break;
      }
      while (rawIndex < original.length && /\s/u.test(original[rawIndex] ?? "")) {
        rawIndex += 1;
      }
      prefixIndex += 1;
      continue;
    }
    if (rawChar !== prefixChar) {
      break;
    }
    rawIndex += 1;
    prefixIndex += 1;
  }
  if (prefixIndex !== normalizedPrefix.length) {
    return original.trim();
  }
  return original.slice(rawIndex);
}

function removeNormalizedSpan(original: string, normalizedSpan: string): string {
  const normalized = normalizeCompanionSpeech(original);
  const at = normalized.indexOf(normalizedSpan);
  if (at < 0) {
    return original.trim();
  }
  const start = rawIndexAtNormalized(original, at);
  const end = rawIndexAtNormalized(original, at + normalizedSpan.length);
  return `${original.slice(0, start)}${original.slice(end)}`.replace(/\s+/g, " ").trim();
}

function rawIndexAtNormalized(original: string, target: number): number {
  let rawIndex = 0;
  let normIndex = 0;
  let inSpace = false;
  while (rawIndex < original.length && normIndex < target) {
    const char = original[rawIndex] ?? "";
    if (/\s/u.test(char)) {
      if (!inSpace) {
        normIndex += 1;
        inSpace = true;
      }
      rawIndex += 1;
      continue;
    }
    inSpace = false;
    rawIndex += 1;
    normIndex += 1;
  }
  return rawIndex;
}
