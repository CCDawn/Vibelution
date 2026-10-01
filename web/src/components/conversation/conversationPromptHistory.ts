/**
 * Composer prompt history: recall recently sent prompts with ArrowUp/ArrowDown
 * on an empty draft (ZCode parity, see its promptHistory.ts).
 *
 * Pure navigation/append logic lives here; ConversationView owns the browse
 * refs and keydown wiring, useChatComposerSubmit owns the append-on-accept.
 */

export const MAX_PROMPT_HISTORY = 30;

/**
 * Single global key by design: neither ConversationView nor
 * useChatComposerSubmit currently carries a stable per-workspace identity at
 * the append/navigation sites (sessionWorkspacePath is optional and not
 * available in the submit hook), so history is recalled across workspaces.
 * If per-workspace scoping is wanted later, key on a hashed workspace path.
 */
export const PROMPT_HISTORY_STORAGE_KEY = "vibelution.chat.prompt-history.v1";

type PromptHistoryDirection = "up" | "down";

export interface PromptHistoryNavigationResult {
  /** null means "left the browse mode; restore the stashed draft". */
  nextIndex: number | null;
  nextValue: string;
  shouldHandle: boolean;
}

export function appendPromptHistoryEntry(
  entries: readonly string[],
  entry: string,
  limit = MAX_PROMPT_HISTORY,
): string[] {
  const trimmed = entry.trim();
  if (!trimmed) {
    return [...entries];
  }

  // Only compare against the last entry so consecutive identical sends do not
  // make ArrowUp land on the same prompt twice; non-adjacent duplicates
  // (A, B, A) are kept on purpose.
  if (entries.at(-1)?.trim() === trimmed) {
    return [...entries];
  }

  const normalizedLimit = Math.max(1, Math.trunc(limit));
  return [...entries, trimmed].slice(-normalizedLimit);
}

export function navigatePromptHistory(
  entries: readonly string[],
  currentIndex: number | null,
  direction: PromptHistoryDirection,
): PromptHistoryNavigationResult {
  if (entries.length === 0) {
    return {
      nextIndex: currentIndex,
      nextValue: "",
      shouldHandle: false,
    };
  }

  if (direction === "up") {
    // Clamp both ends so a stale out-of-range index (history shrank while
    // browsing) can never land outside the list.
    const previous = currentIndex === null ? entries.length - 1 : currentIndex - 1;
    const nextIndex = Math.min(Math.max(previous, 0), entries.length - 1);
    return {
      nextIndex,
      nextValue: entries[nextIndex] ?? "",
      shouldHandle: true,
    };
  }

  if (currentIndex === null) {
    const nextIndex = entries.length - 1;
    return {
      nextIndex,
      nextValue: entries[nextIndex] ?? "",
      shouldHandle: true,
    };
  }

  if (currentIndex >= entries.length - 1) {
    // Past the newest entry: hand the composer back to the stashed draft.
    return {
      nextIndex: null,
      nextValue: "",
      shouldHandle: true,
    };
  }

  const nextIndex = currentIndex + 1;
  return {
    nextIndex,
    nextValue: entries[nextIndex] ?? "",
    shouldHandle: true,
  };
}

/** Reads the stored history, tolerating missing storage and corrupt payloads. */
export function readPromptHistory(
  storage: Pick<Storage, "getItem"> | null | undefined = typeof window === "undefined" ? null : window.localStorage,
): string[] {
  if (!storage) {
    return [];
  }
  let raw: string | null = null;
  try {
    raw = storage.getItem(PROMPT_HISTORY_STORAGE_KEY);
  } catch {
    return [];
  }
  if (!raw) {
    return [];
  }
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.filter((item): item is string => typeof item === "string");
  } catch {
    return [];
  }
}

/** Appends one accepted prompt to the stored history; returns the new list. */
export function appendStoredPromptHistoryEntry(
  entry: string,
  storage: Pick<Storage, "getItem" | "setItem"> | null | undefined = typeof window === "undefined" ? null : window.localStorage,
): string[] {
  const current = readPromptHistory(storage);
  if (!storage) {
    return current;
  }
  const next = appendPromptHistoryEntry(current, entry);
  try {
    storage.setItem(PROMPT_HISTORY_STORAGE_KEY, JSON.stringify(next));
  } catch {
    // Quota/private-mode failures must never break the submit path.
  }
  return next;
}
