import type { AssistantConversationTurn, SessionTurnItem } from "../../api/types";

/**
 * Settled-turn work header data. Pure derivation only.
 *
 * 口径（honest, derivable facts only — no invented fields):
 * - `turn_header`（authoritative）: the backend projects the turn-level work
 *   header (`turnState`/`turnStartedAt`/`turnEndedAt`/`turnActiveMs`) from the
 *   durable journal + work-run snapshots. `turnActiveMs` is the authoritative
 *   worked time; `turnEndedAt - turnStartedAt` is the honest span fallback
 *   when active time is not (yet) derivable. Live turns (`turnState:
 *   "running"`) have no settled span, so the header still degrades below.
 * - `turn_span`: from the turn's start instant to the last derivable activity
 *   instant. Start = the assistant message `timestamp` (turn creation, always
 *   present). End = the freshest of: any item `updatedAt`/`createdAt`, or a
 *   completed tool's `executionStartedAtEpochMs + durationMs`. Turns whose
 *   items carry no timestamps still measure up to the last tool completion —
 *   the trailing answer generation is not inventable from the data.
 * - `tool_durations`: fallback when no span can be formed — the plain sum of
 *   completed tool durations. The header then labels it 「工具耗时」 so the
 *   number is never presented as total turn time.
 */
export const MIN_TURN_WORK_HEADER_DURATION_MS = 5_000;

export type ConversationTurnWorkBasis = "turn_header" | "turn_span" | "tool_durations";

/** Turn-level work header projected by the backend (additive wire fields). */
type TurnWorkHeader = {
  turnState?: string;
  turnStartedAt?: string;
  turnEndedAt?: string;
  turnActiveMs?: number;
};

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

function turnWorkHeader(message: AssistantConversationTurn): TurnWorkHeader {
  // Additive backend fields ride next to the canonical envelope; structural
  // keeps this module decoupled from the shared type file's revision cadence.
  const candidate = message as AssistantConversationTurn & TurnWorkHeader;
  return {
    turnState: typeof candidate.turnState === "string" ? candidate.turnState : undefined,
    turnStartedAt: typeof candidate.turnStartedAt === "string" ? candidate.turnStartedAt : undefined,
    turnEndedAt: typeof candidate.turnEndedAt === "string" ? candidate.turnEndedAt : undefined,
    turnActiveMs:
      typeof candidate.turnActiveMs === "number" && Number.isFinite(candidate.turnActiveMs)
        ? candidate.turnActiveMs
        : undefined,
  };
}

function itemMetadata(item: SessionTurnItem): Record<string, unknown> {
  return item.metadata && typeof item.metadata === "object" ? item.metadata : {};
}

function toolStartEpochMs(item: SessionTurnItem): number | null {
  return parseEpochMs(itemMetadata(item).executionStartedAtEpochMs);
}

function coerceDurationMs(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value) && value >= 0) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed) && parsed >= 0) {
      return parsed;
    }
  }
  return null;
}

function toolDurationMsValue(item: SessionTurnItem): number | null {
  // First-class `durationMs` is the v3 wire fact; metadata carries the legacy
  // live-merge location. Both are capture/journal-measured numbers.
  const wireDuration = coerceDurationMs((item as SessionTurnItem & { durationMs?: unknown }).durationMs);
  if (wireDuration !== null) {
    return wireDuration;
  }
  return coerceDurationMs(itemMetadata(item).durationMs);
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

  const header = turnWorkHeader(message);
  const headerActiveMs = header.turnActiveMs ?? null;
  const headerStartMs = parseEpochMs(header.turnStartedAt);
  const headerEndMs = parseEpochMs(header.turnEndedAt);
  // Authoritative header: the backend measured this turn's worked time (or at
  // least its real start/end instants). Never below the noise floor either —
  // a sub-threshold header is still a header, but keep the threshold semantics.
  if (headerActiveMs !== null && headerActiveMs > 0 && header.turnState !== "running") {
    if (headerActiveMs >= MIN_TURN_WORK_HEADER_DURATION_MS) {
      return {
        durationMs: headerActiveMs,
        basis: "turn_header",
        toolCallCount,
        toolDurationMs: hasToolDuration ? toolDurationSumMs : null,
      };
    }
    return null;
  }
  if (
    header.turnState
    && header.turnState !== "running"
    && headerStartMs !== null
    && headerEndMs !== null
    && headerEndMs >= headerStartMs
    && headerEndMs - headerStartMs >= MIN_TURN_WORK_HEADER_DURATION_MS
  ) {
    return {
      durationMs: headerEndMs - headerStartMs,
      basis: "turn_header",
      toolCallCount,
      toolDurationMs: hasToolDuration ? toolDurationSumMs : null,
    };
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
