/**
 * Streamdown-pattern incomplete-markdown repair for the streaming live tail.
 *
 * Pattern attribution (Apache-2.0):
 * - Streamdown (https://github.com/vercel/streamdown) — `parseIncompleteMarkdown`
 *   concept: while streaming, close unbalanced fences/inline marks and hold
 *   incomplete block syntax so the markdown view does not flash mid-syntax.
 * - zai-org/ZCode chat stream (https://github.com/zai-org/ZCode) — dual-mode
 *   usage: parse-incomplete only while streaming, static renderer once done.
 *
 * This is a dependency-free local adaptation. It only repairs the live tail
 * (never the stable zone, never completed messages) and deliberately does not
 * add syntax highlighting or mermaid: the streaming light pipeline exists to
 * keep per-frame work O(live-tail), not to match the full static pipeline.
 */

export type IncompleteRepairStats = {
  closedFence: boolean;
  completedTable: boolean;
  balancedMarks: number;
};

const MARK_PAIRS: Array<{ open: string; close: string }> = [
  { open: "**", close: "**" },
  { open: "__", close: "__" },
  { open: "~~", close: "~~" },
];

/**
 * Balances the high-value delimiters (bold, underline, strikethrough, inline
 * code). Single-char `*`/`_` italics are deliberately not repaired: a parity
 * heuristic cannot distinguish emphasis from literal asterisks ("3 * 4"),
 * and a stray literal marker for one frame is cheaper than a wrong closer.
 * Closers are appended last-opened-first so nesting stays readable.
 */
function balanceMarks(segment: string, stats: IncompleteRepairStats): string {
  type PendingCloser = { close: string; openIndex: number };
  const pending: PendingCloser[] = [];
  for (const pair of MARK_PAIRS) {
    const openIndex = lastUnpairedOpenIndex(segment, pair.open);
    if (openIndex >= 0) {
      pending.push({ close: pair.close, openIndex });
    }
  }
  const backtickIndex = lastUnpairedOpenIndex(segment, "`");
  if (backtickIndex >= 0) {
    pending.push({ close: "`", openIndex: backtickIndex });
  }
  if (!pending.length) {
    return segment;
  }
  let result = segment;
  pending.sort((a, b) => b.openIndex - a.openIndex);
  for (const closer of pending) {
    result += closer.close;
    stats.balancedMarks += 1;
  }
  return result;
}

/**
 * Index of the delimiter occurrence that opens an unclosed span, assuming
 * occurrences alternate open/close: an odd occurrence count means the last
 * occurrence is the dangling opener. Returns -1 when balanced.
 */
function lastUnpairedOpenIndex(segment: string, delimiter: string): number {
  let count = 0;
  let lastIndex = -1;
  let offset = segment.indexOf(delimiter);
  while (offset !== -1) {
    count += 1;
    lastIndex = offset;
    offset = segment.indexOf(delimiter, offset + delimiter.length);
  }
  return count % 2 === 1 ? lastIndex : -1;
}

/**
 * Repairs text that may end mid-syntax so the light block parse stays stable
 * while streaming. Pure and deterministic.
 */
export function repairIncompleteMarkdown(text: string): {
  repaired: string;
  stats: IncompleteRepairStats;
} {
  const stats: IncompleteRepairStats = { closedFence: false, completedTable: false, balancedMarks: 0 };
  let working = String(text ?? "").replace(/\r\n/g, "\n");
  if (!working) {
    return { repaired: working, stats };
  }

  // 1. Close an unterminated code fence (odd number of ``` fence delimiters).
  const fenceMatches = working.match(/^```/gm);
  if (fenceMatches && fenceMatches.length % 2 === 1) {
    working = `${working}\n\`\`\``;
    stats.closedFence = true;
  }

  // 2. Complete a dangling table: a row-like last line whose predecessor is
  //    not a separator row gets a minimal separator so the block parses as a
  //    table instead of flashing back to a paragraph.
  const lines = working.split("\n");
  const lastLine = lines[lines.length - 1]?.trim() ?? "";
  const previousLine = lines[lines.length - 2]?.trim() ?? "";
  const isRowLike = (line: string) => line.startsWith("|") && line.includes("|", 1);
  const isSeparatorLike = (line: string) => /^\|[\s:|-]+\|$/.test(line);
  if (isRowLike(lastLine) && !isSeparatorLike(lastLine)) {
    if (!isSeparatorLike(previousLine) && isRowLike(previousLine)) {
      // Header without separator: insert one so the header does not flash.
      const columnCount = previousLine.split("|").length - 2;
      lines.splice(lines.length - 1, 0, `| ${Array.from({ length: Math.max(1, columnCount) }, () => "---").join(" | ")} |`);
      stats.completedTable = true;
      working = lines.join("\n");
    } else if (!isSeparatorLike(previousLine)) {
      const columnCount = lastLine.split("|").length - 2;
      if (columnCount >= 1) {
        lines.push(`| ${Array.from({ length: columnCount }, () => "---").join(" | ")} |`);
        stats.completedTable = true;
        working = lines.join("\n");
      }
    }
  }

  // 3. Balance unbalanced inline emphasis marks and inline backticks outside
  //    code fences.
  const segments = working.split("```");
  for (let index = 0; index < segments.length; index += 1) {
    if (index % 2 === 1) {
      continue; // inside a fence body — leave code bytes untouched
    }
    const repairedSegment = balanceMarks(segments[index] ?? "", stats);
    if (repairedSegment !== segments[index]) {
      segments[index] = repairedSegment;
    }
  }
  working = segments.join("```");

  return { repaired: working, stats };
}
