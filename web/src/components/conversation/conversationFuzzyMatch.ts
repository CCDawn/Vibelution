/**
 * Shared tiered match scoring for composer completion candidates (the @
 * reference type-ahead, slash commands, and the plus-menu reference pickers).
 *
 * Borrowed from the ZCode @-mention ranking: a prefix hit outranks a substring
 * hit, which outranks a subsequence hit; anything else is a non-match.
 * Subsequence matching stays disabled whenever the query or the haystack
 * carries CJK text (ideographs, kana, or hangul): scattered CJK characters
 * match far too broadly to be useful, so CJK queries only ever match by
 * prefix or substring. Modeled on the command palette's fuzzy fallback
 * (VCommandPalette scoreItem) but returning stable sort keys instead of
 * position-weighted scores.
 */

/** Sort keys returned by {@link scoreMatch}: lower is a better match. */
export const SCORE_PREFIX = 0;
export const SCORE_SUBSTRING = 1;
export const SCORE_SUBSEQUENCE = 2;
/** Not a match: callers drop candidates scoring this value. */
export const SCORE_NONE = Number.POSITIVE_INFINITY;

/** Common CJK code point ranges: ideographs (incl. ext A/B-F), kana, hangul. */
const cjkCodePointRanges: ReadonlyArray<readonly [number, number]> = [
  [0x1100, 0x11ff], // Hangul Jamo
  [0x3040, 0x30ff], // Hiragana + Katakana
  [0x3400, 0x4dbf], // CJK Unified Ideographs Extension A
  [0x4e00, 0x9fff], // CJK Unified Ideographs
  [0xac00, 0xd7af], // Hangul Syllables
  [0xf900, 0xfaff], // CJK Compatibility Ideographs
  [0x20000, 0x2fa1f], // CJK Extensions B-F + Compatibility Supplement
];

function isCjkCodePoint(codePoint: number): boolean {
  return cjkCodePointRanges.some(([start, end]) => codePoint >= start && codePoint <= end);
}

/** True when the text carries any CJK ideograph, kana, or hangul character. */
export function containsCjk(text: string): boolean {
  for (const character of String(text ?? "")) {
    const codePoint = character.codePointAt(0);
    if (codePoint !== undefined && isCjkCodePoint(codePoint)) {
      return true;
    }
  }
  return false;
}

function isSubsequence(needle: string, haystack: string): boolean {
  const expected = Array.from(needle);
  if (expected.length === 0) {
    return true;
  }
  let cursor = 0;
  for (const character of haystack) {
    if (character === expected[cursor]) {
      cursor += 1;
      if (cursor === expected.length) {
        return true;
      }
    }
  }
  return false;
}

/**
 * Score one candidate haystack against the query, returning the sort key.
 *
 * Both arguments are compared as-is: callers normalize case (and trim the
 * query) before calling. An empty query ties everything at the top tier so
 * callers keep their input order untouched.
 */
export function scoreMatch(query: string, text: string): number {
  const needle = String(query ?? "");
  const haystack = String(text ?? "");
  if (!needle || haystack.startsWith(needle)) {
    return SCORE_PREFIX;
  }
  if (haystack.includes(needle)) {
    return SCORE_SUBSTRING;
  }
  if (!containsCjk(needle) && !containsCjk(haystack) && isSubsequence(needle, haystack)) {
    return SCORE_SUBSEQUENCE;
  }
  return SCORE_NONE;
}

/**
 * Rank candidates by tiered match score, dropping non-matches. Equal scores
 * keep the caller's input order (stable sort), so callers preserve their own
 * secondary rules (builtin input order, alphabetical order, list order) by
 * feeding items in that order.
 */
export function rankByScore<T>(
  items: readonly T[],
  query: string,
  haystackOf: (item: T) => string,
): T[] {
  const ranked: Array<{ item: T; score: number }> = [];
  for (const item of items) {
    const score = scoreMatch(query, haystackOf(item));
    if (Number.isFinite(score)) {
      ranked.push({ item, score });
    }
  }
  ranked.sort((left, right) => left.score - right.score);
  return ranked.map((entry) => entry.item);
}
