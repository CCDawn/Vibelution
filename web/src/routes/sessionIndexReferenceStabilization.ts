import type { ConversationSummary, SessionSummary } from "../api/types";

/**
 * Reference stabilization for the chat session/conversation index pipeline.
 *
 * The active-session stream applies a snapshot every <=350ms and every apply
 * rebuilds the session index caches and the conversation index model from
 * scratch, so downstream consumers that key on array/object identity (useMemo,
 * memo) see "all new" on every apply even when nothing user-visible changed.
 * These helpers make the data-layer output boundaries reuse the previous
 * object/array references whenever content is structurally equivalent, so
 * identity-based memoization can short-circuit.
 *
 * Equivalence is compared field by field. `JSON.stringify` is deliberately
 * avoided: it is sensitive to key insertion order, and upstream constructors
 * mix conditional spreads with explicit keys, so content-equal objects can
 * serialize differently and stabilization would silently degrade into "new
 * reference every frame". Field comparison is order-insensitive and
 * short-circuits at the first difference, keeping the cost O(fields) per
 * compared entry.
 */

/**
 * Structural equivalence for index entries: shallow fields compare directly,
 * nested objects compare key by key, arrays compare element by element.
 *
 * Keys whose value is `undefined` are treated as absent on both sides, so a
 * conditional spread (`...(x ? { k: v } : {})`) and an explicit `k: undefined`
 * stay equivalent. `null` is a real value and never equals `undefined`.
 * Declared keys plus any runtime-extra keys are compared, so an unknown extra
 * field can only cause a reference rotation (conservative), never a stale reuse.
 */
export function areIndexEntryValuesEquivalent(left: unknown, right: unknown): boolean {
  if (left === right) {
    return true;
  }
  if (typeof left !== "object" || left === null || typeof right !== "object" || right === null) {
    return false;
  }
  if (Array.isArray(left) || Array.isArray(right)) {
    if (!Array.isArray(left) || !Array.isArray(right) || left.length !== right.length) {
      return false;
    }
    return left.every((value, index) => areIndexEntryValuesEquivalent(value, right[index]));
  }
  const leftRecord = left as Record<string, unknown>;
  const rightRecord = right as Record<string, unknown>;
  const leftKeys = Object.keys(leftRecord).filter((key) => leftRecord[key] !== undefined);
  const rightKeys = Object.keys(rightRecord).filter((key) => rightRecord[key] !== undefined);
  if (leftKeys.length !== rightKeys.length) {
    return false;
  }
  return leftKeys.every((key) => areIndexEntryValuesEquivalent(leftRecord[key], rightRecord[key]));
}

/**
 * Reuse previous entries when content is equivalent.
 *
 * Entries are matched by `identityKey` (not position), so reordering reuses
 * entry references while still producing a new array. The previous array
 * reference is returned only when every entry was reused in the same position
 * (same length, same order), which lets whole-array memo dependencies
 * short-circuit. Entries with an empty identity key are left as-is.
 */
export function stabilizeIndexEntries<T>(
  previous: readonly T[] | undefined,
  next: readonly T[],
  identityKey: (entry: T) => string,
  areEquivalent: (left: T, right: T) => boolean,
): T[] {
  if (next.length === 0) {
    // An empty result is whole-table equivalent to an empty previous table:
    // reuse its reference so downstream empty-state memos short-circuit too.
    return previous && previous.length === 0 ? (previous as T[]) : (next as T[]);
  }
  if (!previous || previous.length === 0) {
    return next as T[];
  }
  const previousByKey = new Map<string, T>();
  for (const entry of previous) {
    const key = identityKey(entry);
    if (key && !previousByKey.has(key)) {
      previousByKey.set(key, entry);
    }
  }
  if (previousByKey.size === 0) {
    return next as T[];
  }
  let identical = previous.length === next.length;
  const stabilized = next.map((entry, index) => {
    const key = identityKey(entry);
    const previousEntry = key ? previousByKey.get(key) : undefined;
    if (previousEntry && areEquivalent(previousEntry, entry)) {
      if (identical && previous[index] !== previousEntry) {
        identical = false;
      }
      return previousEntry;
    }
    identical = false;
    return entry;
  });
  return identical ? (previous as T[]) : stabilized;
}

/**
 * Session summary equivalence: every field declared on `SessionSummary`
 * (web/src/api/types/chat.ts) plus runtime extras, compared as:
 * - identity/shallow strings, numbers, booleans: id, title, agentId, agentCode,
 *   agentDisplayName, agentAvatarImagePath, agentAvatarImageUrl,
 *   agentPrimaryMode, agentRoleKey, agentPromptTemplateId, dialogueModelId,
 *   reasoningEffort, agentInboxPendingCount, agentPrimaryDirectSessionId,
 *   agentDirectSessionMismatch, workspacePath, agentWorkspacePath,
 *   agentMissingId, agentMissing, agentStatusCode, agentStatusMessage, status,
 *   taskSummary, lastActive, updatedAt, createdAt, currentPhase,
 *   hiddenFromIndex, readOnly, lastTurnStatus, lastTurnTerminalTurnId,
 *   terminalReason, sessionKind, sessionRole, parentSessionId, rootSessionId,
 *   activeChildSessionId, childStatus, taskTitle, teamId, teamName,
 *   conversationIndexVisibility, conversationIndexKind;
 * - arrays element-wise: childSessionIds, conversationIndexErrors;
 * - nested objects key by key: experimentBinding, archiveState
 *   (status/source/agentId/archivedAt + extras), resultCard
 *   (status/title/summary/updatedAt + extras), agentPromptSnapshot
 *   (incl. corePrompts[] and promptAssembly/segments[]), lastPromptAssembly,
 *   sourceRef, projectionEdit, agentSourceRef.
 *
 * Activity timestamps (lastActive/updatedAt) are compared even though most
 * rail rows do not render them directly: a content change there still rotates
 * the row reference. Conservative correctness beats aggressive reuse — a field
 * that gains a downstream consumer must not be missing from this comparison.
 */
export function areSessionSummariesEquivalent(left: SessionSummary, right: SessionSummary): boolean {
  return areIndexEntryValuesEquivalent(left, right);
}

/**
 * Conversation summary equivalence: every field declared on
 * `ConversationSummary` (web/src/api/types/chat.ts) plus runtime extras:
 * - shallow: teamId, teamName, conversationId, type, title, agentId, agentCode,
 *   agentDisplayName, agentAvatarImagePath, agentAvatarImageUrl,
 *   directSessionId, roomId, status, summary, updatedAt, workspacePath,
 *   participantCount, mode, agentPrimaryMode, agentRoleKey,
 *   agentPromptTemplateId, dialogueModelId, agentInboxPendingCount,
 *   conversationIndexVisibility, conversationIndexKind, agentMissing,
 *   agentStatusCode, agentStatusMessage;
 * - arrays element-wise: conversationIndexErrors;
 * - nested objects key by key: sourceRef, projectionEdit, agentSourceRef.
 */
export function areConversationSummariesEquivalent(left: ConversationSummary, right: ConversationSummary): boolean {
  return areIndexEntryValuesEquivalent(left, right);
}

export function sessionSummaryIdentityKey(session: Pick<SessionSummary, "id">): string {
  return String(session.id || "").trim();
}

export function conversationSummaryIdentityKey(conversation: ConversationSummary): string {
  return String(
    conversation.conversationId || conversation.directSessionId || conversation.roomId || conversation.agentId || "",
  ).trim();
}

export function stabilizeSessionSummaries(previous: readonly SessionSummary[] | undefined, next: readonly SessionSummary[]): SessionSummary[] {
  return stabilizeIndexEntries(previous, next, sessionSummaryIdentityKey, areSessionSummariesEquivalent);
}

export function stabilizeConversationSummaries(
  previous: readonly ConversationSummary[] | undefined,
  next: readonly ConversationSummary[],
): ConversationSummary[] {
  return stabilizeIndexEntries(previous, next, conversationSummaryIdentityKey, areConversationSummariesEquivalent);
}
