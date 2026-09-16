import type { SessionReferenceAttachment } from "../../api/types";

/**
 * Caret-aware "@ reference" type-ahead parsing for the chat composer.
 *
 * The composer's reference pickers never insert reference markup into the
 * draft text: selecting a candidate registers a structured
 * {@link SessionReferenceAttachment} chip (deduped, capped at 6 per turn) and
 * the backend resolves it from the submit payload (`conversation_references.py`
 * has no text-embedded @ syntax). The type-ahead is therefore a fast path to
 * the same structured attachment: while the draft contains a live "@ token",
 * candidates filter on the token's query, and selecting one registers the same
 * reference payload while removing the token fragment from the draft.
 */

/** Largest filter fragment accepted after "@", keeping long pasted text inert. */
export const MAX_REFERENCE_TYPEAHEAD_QUERY_LENGTH = 64;

export const MAX_REFERENCE_TYPEAHEAD_SUGGESTIONS = 6;

export type ReferenceTypeaheadToken = {
  /** Index of the triggering "@" character in the draft text. */
  triggerIndex: number;
  /** Filter fragment between "@" (exclusive) and the caret. */
  query: string;
  /** Replace-range start (the "@" itself). */
  start: number;
  /** Replace-range end (the caret). */
  end: number;
};

/** One rendered row of the @ reference suggestion listbox. */
export type ReferenceTypeaheadOption = {
  id: string;
  title: string;
  meta?: string;
  reference: SessionReferenceAttachment;
};

/** ASCII word characters only: CJK neighbors must still trigger (你@文件). */
function isAsciiWordCharacter(character: string): boolean {
  return /[A-Za-z0-9_]/.test(character);
}

/**
 * Resolve the live "@ token" around the caret, or null when the caret is not
 * inside one.
 *
 * Rules:
 * - The "@" is the closest one at or before the caret; text between it and the
 *   caret must be whitespace-free (typing a space ends the token).
 * - The token only arms when the "@" starts a word: at text start, after
 *   whitespace/punctuation/CJK punctuation, or after a CJK character. An "@"
 *   directly after an ASCII letter/digit (email-like `foo@bar`) stays inert.
 * - A query longer than {@link MAX_REFERENCE_TYPEAHEAD_QUERY_LENGTH} never
 *   arms, so pasted content cannot pop the listbox.
 */
export function detectReferenceToken(text: string, caretIndex: number): ReferenceTypeaheadToken | null {
  const value = String(text ?? "");
  const caret = Math.min(Math.max(0, Math.trunc(Number(caretIndex) || 0)), value.length);
  for (let index = caret - 1; index >= 0; index -= 1) {
    const character = value[index];
    if (character === "@") {
      if (index > 0 && isAsciiWordCharacter(value[index - 1])) {
        // Email-like usage: the "@" is glued to a preceding word.
        return null;
      }
      const query = value.slice(index + 1, caret);
      if (/\s/.test(query) || query.length > MAX_REFERENCE_TYPEAHEAD_QUERY_LENGTH) {
        return null;
      }
      return { triggerIndex: index, query, start: index, end: caret };
    }
    if (/\s/.test(character)) {
      // Whitespace between the caret and any "@" ends the token.
      return null;
    }
  }
  return null;
}

/**
 * Filter and cap reference options for the current token query, matching the
 * reference dialog's "title + meta contains" semantics. An empty query shows
 * the first options as-is.
 */
export function filterReferenceTypeaheadOptions(
  options: readonly ReferenceTypeaheadOption[],
  query: string,
  limit: number = MAX_REFERENCE_TYPEAHEAD_SUGGESTIONS,
): ReferenceTypeaheadOption[] {
  const normalized = String(query ?? "").trim().toLocaleLowerCase();
  const matches = !normalized
    ? [...options]
    : options.filter((option) => `${option.title} ${option.meta ?? ""}`.toLocaleLowerCase().includes(normalized));
  return matches.slice(0, Math.max(0, limit));
}

/**
 * Remove a selected token from the draft and report where the caret should
 * land. When the removal would glue two non-whitespace chunks together, a
 * single space is kept between them and the caret lands after it.
 */
export function removeReferenceToken(
  text: string,
  token: ReferenceTypeaheadToken,
): { text: string; caretIndex: number } {
  const value = String(text ?? "");
  const start = Math.min(Math.max(0, Math.trunc(token.start) || 0), value.length);
  const end = Math.min(Math.max(start, Math.trunc(token.end) || 0), value.length);
  const before = value.slice(0, start);
  const after = value.slice(end);
  const charBefore = before.slice(-1);
  const charAfter = after.slice(0, 1);
  if (charBefore && charAfter && !/\s/.test(charBefore) && !/\s/.test(charAfter)) {
    return { text: `${before} ${after}`, caretIndex: start + 1 };
  }
  return { text: before + after, caretIndex: start };
}
