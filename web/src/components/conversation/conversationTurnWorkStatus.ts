import type { AssistantConversationTurn, SessionTurnItem } from "../../api/types";

/**
 * Settled-turn work header data. Pure derivation only.
 *
 * 口径（honest, derivable facts only — no invented fields):
 * - `turn_span`: from the turn's start instant to the last derivable activity
 *   instant. Start = the assistant message `timestamp` (turn creation, always
 *   present). End = the freshest of: any item `updatedAt`/`createdAt`, or a
 *   completed tool's `executionStartedAtEpochMs + durationMs`. Canonical journal
 *   items carry no timestamps today, so a turn whose only timed facts are tool
 *   facts measures up to the last tool completion — the trailing answer
 *   generation is not inventable from the data, and the header says "已工作"
 *   with that span rather than fabricating an end.
 * - `tool_durations`: fallback when no span can be formed — the plain sum of
 *   completed tool durations. The header then labels it 「工具耗时」 so the
 *   number is never presented as total turn time.
 */
export const MIN_TURN_WORK_HEADER_DURATION_MS = 5_000;

export type ConversationTurnWorkBasis = "turn_span" | "tool_durations";

export type ConversationTurnWorkSummary = {
  durationMs: number;
  basis: ConversationTurnWorkBasis;
  toolCallCount: number;
  /** Sum of completed tool durations; null when no tool reported a duration. */
  toolDurationMs: number | null;
};

function parseEpochMs(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value) && value > 0) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Date.parse(value);
    if (Number.isFinite(parsed) && parsed > 0) {
      return parsed;
    }
  }
  return null;
}

function itemMetadata(item: SessionTurnItem): Record<string, unknown> {
  return item.metadata && typeof item.metadata === "object" ? item.metadata : {};
}

function toolStartEpochMs(item: SessionTurnItem): number | null {
  return parseEpochMs(itemMetadata(item).executionStartedAtEpochMs);
}

function toolDurationMsValue(item: SessionTurnItem): number | null {
  const raw = itemMetadata(item).durationMs;
  if (typeof raw === "number" && Number.isFinite(raw) && raw >= 0) {
    return raw;
  }
  if (typeof raw === "string" && raw.trim()) {
    const parsed = Number(raw);
    if (Number.isFinite(parsed) && parsed >= 0) {
      return parsed;
    }
  }
  return null;
}

function itemStampMs(item: SessionTurnItem): number | null {
  // `updatedAt` supersedes `createdAt`: the latest revision moment is the
  // fresher activity fact when both exist.
  return parseEpochMs(item.updatedAt) ?? parseEpochMs(item.createdAt);
}

/**
 * Resolve the derivable work summary of a settled assistant turn, or null when
 * the turn is below the header's noise threshold or carries no usable time
 * facts at all. Pure: same inputs always yield the same summary.
 */
export function resolveConversationTurnWorkSummary(
  message: AssistantConversationTurn,
): ConversationTurnWorkSummary | null {
  const toolItems = message.turnItems.filter((item) => item.type === "tool_call");
  const toolCallCount = toolItems.length;
  let toolDurationSumMs = 0;
  let hasToolDuration = false;
  for (const item of toolItems) {
    const durationMs = toolDurationMsValue(item);
    if (durationMs !== null) {
      toolDurationSumMs += durationMs;
      hasToolDuration = true;
    }
  }

  const endCandidates: number[] = [];
  const startCandidates: number[] = [];
  const messageStartMs = parseEpochMs(message.timestamp);
  if (messageStartMs !== null) {
    startCandidates.push(messageStartMs);
  }
  for (const item of message.turnItems) {
    const stampMs = itemStampMs(item);
    if (stampMs !== null) {
      startCandidates.push(stampMs);
      endCandidates.push(stampMs);
    }
    if (item.type === "tool_call") {
      const startMs = toolStartEpochMs(item);
      const durationMs = toolDurationMsValue(item);
      if (startMs !== null) {
        startCandidates.push(startMs);
        if (durationMs !== null) {
          endCandidates.push(startMs + durationMs);
        }
      }
    }
  }

  const startMs = startCandidates.length > 0 ? Math.min(...startCandidates) : null;
  const endMs = endCandidates.length > 0 ? Math.max(...endCandidates) : null;
  if (
    startMs !== null
    && endMs !== null
    && endMs >= startMs
    && endMs - startMs >= MIN_TURN_WORK_HEADER_DURATION_MS
  ) {
    return {
      durationMs: endMs - startMs,
      basis: "turn_span",
      toolCallCount,
      toolDurationMs: hasToolDuration ? toolDurationSumMs : null,
    };
  }
  // No span derivable (no item timestamps at all): a real tool-duration sum is
  // still an honest, clearly-labeled lower bound.
  if (hasToolDuration && toolDurationSumMs >= MIN_TURN_WORK_HEADER_DURATION_MS) {
    return {
      durationMs: toolDurationSumMs,
      basis: "tool_durations",
      toolCallCount,
      toolDurationMs: toolDurationSumMs,
    };
  }
  return null;
}

/**
 * "X 分 Y 秒" style two-unit duration copy (reference: desktop `workDuration`):
 * the two largest non-zero units only, so long turns stay scannable.
 */
export function formatConversationTurnWorkDuration(
  durationMs: number,
  lang: "zh" | "en" | string,
): string {
  const zh = lang !== "en";
  const totalSeconds = Math.max(1, Math.round(durationMs / 1000));
  const units: Array<{ value: number; zh: string; en: string }> = [
    { value: Math.floor(totalSeconds / 86_400), zh: "天", en: "d" },
    { value: Math.floor((totalSeconds % 86_400) / 3_600), zh: "时", en: "h" },
    { value: Math.floor((totalSeconds % 3_600) / 60), zh: "分", en: "m" },
    { value: totalSeconds % 60, zh: "秒", en: "s" },
  ];
  const parts: string[] = [];
  for (const unit of units) {
    if (unit.value > 0) {
      parts.push(zh ? `${unit.value} ${unit.zh}` : `${unit.value}${unit.en}`);
    }
    if (parts.length === 2) {
      break;
    }
  }
  if (parts.length === 0) {
    return zh ? "1 秒" : "1s";
  }
  return parts.join(zh ? " " : " ");
}

/** Turn-tail trigger label, e.g. 「已工作 3 分 42 秒」. */
export function formatConversationTurnWorkedFor(
  summary: ConversationTurnWorkSummary,
  lang: "zh" | "en" | string,
): string {
  const duration = formatConversationTurnWorkDuration(summary.durationMs, lang);
  // tool_durations basis measures the tools only; the label must say so.
  if (summary.basis === "tool_durations") {
    return lang === "en"
      ? `Tool time ${duration}`
      : `工具耗时 ${duration}`;
  }
  return lang === "en"
    ? `Worked for ${duration}`
    : `已工作 ${duration}`;
}

/** Expanded body line: what the duration is made of, with only known facts. */
export function formatConversationTurnWorkBreakdown(
  summary: ConversationTurnWorkSummary,
  lang: "zh" | "en" | string,
): string {
  const zh = lang !== "en";
  const toolParts: string[] = [];
  if (summary.toolCallCount > 0) {
    toolParts.push(zh
      ? `工具调用 ${summary.toolCallCount} 次`
      : `${summary.toolCallCount} tool call${summary.toolCallCount === 1 ? "" : "s"}`);
  }
  if (summary.toolDurationMs !== null) {
    toolParts.push(zh
      ? `工具耗时 ${formatConversationTurnWorkDuration(summary.toolDurationMs, lang)}`
      : `tool time ${formatConversationTurnWorkDuration(summary.toolDurationMs, lang)}`);
  }
  if (toolParts.length === 0) {
    return zh ? "本轮没有可展示的分段耗时" : "No per-segment timing available for this turn";
  }
  return toolParts.join(zh ? " · " : " · ");
}
