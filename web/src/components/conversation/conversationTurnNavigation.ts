/**
 * Turn navigation directory for the conversation timeline minimap (pattern:
 * zai-org/ZCode ConversationTurnNavigator, Apache-2.0). Pure row-plan logic:
 * grouping timeline rows into turns, resolving the current turn from scroll
 * geometry, and label compaction. The component shell lives in
 * ConversationTurnNavigator.tsx; nothing here touches the DOM.
 */

export const CONVERSATION_TURN_NAV_MIN_TURNS = 6;
export const CONVERSATION_TURN_NAV_LABEL_MAX_CHARS = 48;
/** Turn-list user preview cap (tooltip/list rows, not the 48-char label). */
export const CONVERSATION_TURN_NAV_USER_PREVIEW_MAX_CHARS = 200;
/** Turn-list assistant preview cap; assistant turns run longer than user ones. */
export const CONVERSATION_TURN_NAV_ASSISTANT_PREVIEW_MAX_CHARS = 300;

/** Viewport fraction used as the "current turn" probe offset. */
const CURRENT_TURN_PROBE_VIEWPORT_FRACTION = 0.35;
/** Probe never drifts further than this from the viewport top. */
const CURRENT_TURN_PROBE_MAX_PX = 240;

export type ConversationTurnNavRowKind = "user" | "assistant" | "other";

export type ConversationTurnNavRowInput = {
  rowKey: string;
  previewText: string;
};

export type ConversationTurnNavEntry = {
  /** 0-based turn order in the timeline. */
  turnIndex: number;
  /**
   * Plan row index the turn starts at: the user row, or the leading
   * assistant row for turns that begin without one (inbox/group transcripts).
   */
  anchorRowIndex: number;
  userRowKey: string | null;
  assistantRowKey: string | null;
  label: string;
  /**
   * Collapsed, length-capped message previews for the turn's user and
   * assistant rows; empty when unavailable or when no preview lookup was
   * passed to buildConversationTurnNavDirectory.
   */
  userPreviewText: string;
  assistantPreviewText: string;
};

/**
 * Row keys come from agentMessageTimelineRows: `user-message:<id>` /
 * `<role>-submission:<clientSubmissionId>` for user rows,
 * `assistant-turn:<turnId>` / `assistant-active:<renderKey>` for assistant
 * rows; anything else is timeline chrome (lifecycle notices, system rows).
 */
export function conversationTurnNavRowKind(rowKey: string): ConversationTurnNavRowKind {
  const key = String(rowKey ?? "");
  // Covers user-message/user-submission and assistant-turn/assistant-active
  // plus role-prefixed variants (e.g. assistant-submission) in one sweep.
  if (key.startsWith("assistant-")) {
    return "assistant";
  }
  if (key.startsWith("user-")) {
    return "user";
  }
  return "other";
}

/** Single-line, length-capped tooltip label with a caller-localized fallback. */
export function conversationTurnNavLabel(previewText: string, fallback: string): string {
  const singleLine = String(previewText ?? "").replace(/\s+/g, " ").trim();
  if (!singleLine) {
    return fallback;
  }
  return singleLine.slice(0, CONVERSATION_TURN_NAV_LABEL_MAX_CHARS);
}

/** Collapsed, single-line preview clipped to the turn-list cap. */
function clampTurnNavPreviewText(text: unknown, maxChars: number): string {
  return String(text ?? "").replace(/\s+/g, " ").trim().slice(0, maxChars);
}

/**
 * Groups the timeline row plan into turns: a turn starts at every user row
 * and owns the first assistant row that follows it before the next user row.
 * Assistant rows with no open user row (inbox/group transcripts at the top)
 * form assistant-anchored turns; consecutive assistant rows each get their
 * own turn. Non-turn rows are skipped.
 *
 * `previewTextByRowKey` optionally maps row keys (`user-<id>` /
 * `assistant-<id>` shapes) to message preview text; entries then carry
 * `userPreviewText` / `assistantPreviewText` for the turn list. Omitting it
 * keeps those fields empty for backward compatibility.
 */
export function buildConversationTurnNavDirectory(
  rows: ConversationTurnNavRowInput[],
  options: {
    fallbackLabel?: (turnNumber: number) => string;
    previewTextByRowKey?: ReadonlyMap<string, string>;
  } = {},
): ConversationTurnNavEntry[] {
  const fallbackLabel = options.fallbackLabel ?? ((turnNumber: number) => String(turnNumber));
  const previewTextByRowKey = options.previewTextByRowKey;
  const previewFor = (rowKey: string, maxChars: number) => (previewTextByRowKey
    ? clampTurnNavPreviewText(previewTextByRowKey.get(rowKey), maxChars)
    : "");
  const entries: ConversationTurnNavEntry[] = [];
  let current: ConversationTurnNavEntry | null = null;
  rows.forEach((row, index) => {
    const kind = conversationTurnNavRowKind(row.rowKey);
    if (kind === "user") {
      current = {
        turnIndex: entries.length,
        anchorRowIndex: index,
        userRowKey: row.rowKey,
        assistantRowKey: null,
        label: conversationTurnNavLabel(row.previewText, fallbackLabel(entries.length + 1)),
        userPreviewText: previewFor(row.rowKey, CONVERSATION_TURN_NAV_USER_PREVIEW_MAX_CHARS),
        assistantPreviewText: "",
      };
      entries.push(current);
      return;
    }
    if (kind === "assistant") {
      // First assistant row right after a user row completes that turn;
      // anything else opens an assistant-anchored turn.
      if (current && current.userRowKey !== null && current.assistantRowKey === null) {
        current.assistantRowKey = row.rowKey;
        current.assistantPreviewText = previewFor(
          row.rowKey,
          CONVERSATION_TURN_NAV_ASSISTANT_PREVIEW_MAX_CHARS,
        );
        return;
      }
      current = {
        turnIndex: entries.length,
        anchorRowIndex: index,
        userRowKey: null,
        assistantRowKey: row.rowKey,
        label: conversationTurnNavLabel(row.previewText, fallbackLabel(entries.length + 1)),
        userPreviewText: "",
        assistantPreviewText: previewFor(
          row.rowKey,
          CONVERSATION_TURN_NAV_ASSISTANT_PREVIEW_MAX_CHARS,
        ),
      };
      entries.push(current);
    }
  });
  return entries;
}

export type ConversationTurnNavCurrentInput = {
  entries: ConversationTurnNavEntry[];
  /**
   * Row count of the virtualized history segment; rows at or beyond this
   * index render in the static live tail.
   */
  historyRowCount: number;
  /** Total measured height of the virtualized history segment. */
  historyTotalSize: number;
  /** Current scroll offset within the timeline (0 when unknown). */
  scrollOffset: number;
  /** Visible viewport height of the timeline (0 when unknown). */
  viewportHeight: number;
  /**
   * Resolves the plan row index painted at a scroll offset within the
   * virtualized history segment, or null when it cannot be resolved.
   */
  rowIndexAtOffset: (offset: number) => number | null;
};

/**
 * Current turn = the turn whose rows sit under a probe point about a third
 * into the viewport. Probes beyond the virtualized history segment land in
 * the live tail, which is always the last entry.
 */
export function resolveConversationTurnNavCurrentIndex(input: ConversationTurnNavCurrentInput): number {
  const { entries } = input;
  if (entries.length === 0) {
    return -1;
  }
  const probe = input.scrollOffset + Math.min(
    Math.max(input.viewportHeight * CURRENT_TURN_PROBE_VIEWPORT_FRACTION, 0),
    CURRENT_TURN_PROBE_MAX_PX,
  );
  if (input.historyTotalSize <= 0 || probe >= input.historyTotalSize) {
    return entries.length - 1;
  }
  const rowIndex = input.rowIndexAtOffset(probe);
  if (rowIndex === null || rowIndex < 0) {
    return 0;
  }
  if (rowIndex >= input.historyRowCount) {
    return entries.length - 1;
  }
  let current = 0;
  for (const entry of entries) {
    if (entry.anchorRowIndex > rowIndex) {
      break;
    }
    current = entry.turnIndex;
  }
  return current;
}
