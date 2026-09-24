/**
 * Streamdown-pattern incomplete-markdown repair for streaming rendering.
 *
 * Pattern attribution (Apache-2.0):
 * - Streamdown (https://github.com/vercel/streamdown) — `parseIncompleteMarkdown`
 *   concept: while streaming, close unbalanced fences/inline marks and hold
 *   incomplete block syntax so react-markdown output does not flash.
 * - zai-org/ZCode chat stream (https://github.com/zai-org/ZCode) — dual-mode
 *   usage (parse-incomplete only while streaming, static renderer once done).
 *
 * This is a local, dependency-free adaptation trimmed to the constructs the
 * preview script actually emits (fences, tables, bold/italic/strikethrough,
 * inline code). Production integration should evaluate the upstream package.
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
  { open: "*", close: "*" },
  { open: "_", close: "_" },
];

/**
 * Repairs text that may end mid-syntax so the markdown AST stays stable
 * while streaming. Pure and deterministic.
 */
export function repairIncompleteMarkdown(text: string): {
  repaired: string;
  stats: IncompleteRepairStats;
} {
  const stats: IncompleteRepairStats = { closedFence: false, completedTable: false, balancedMarks: 0 };
  let working = text;

  // 1. Close an unterminated code fence (odd number of ``` fence lines).
  const fenceMatches = working.match(/^```/gm);
  if (fenceMatches && fenceMatches.length % 2 === 1) {
    working = `${working}\n\`\`\``;
    stats.closedFence = true;
  }

  // 2. Complete a dangling table: header row without separator, or trailing
  //    partial row. Keeps the table block rendering instead of flashing to a
  //    paragraph and back.
  const lines = working.split("\n");
  const lastLine = lines[lines.length - 1]?.trim() ?? "";
  const previousLine = lines[lines.length - 2]?.trim() ?? "";
  const isRowLike = (line: string) => /^\|.*\|?$/.test(line) && line.includes("|");
  if (isRowLike(lastLine)) {
    const previousIsSeparator = /^\|[\s:|-]+\|?$/.test(previousLine);
    if (!previousIsSeparator) {
      const columnCount = lastLine.split("|").length - 2;
      if (columnCount >= 0) {
        lines.push(`| ${Array.from({ length: Math.max(1, columnCount) }, () => "---").join(" | ")} |`);
        stats.completedTable = true;
        working = lines.join("\n");
      }
    }
  }

  // 3. Balance unbalanced inline emphasis marks outside code fences.
  const segments = splitOutsideFences(working);
  for (let index = 0; index < segments.length; index += 1) {
    const segment = segments[index];
    if (index % 2 === 1) continue; // inside fence
    const repairedSegment = balanceMarks(segment, stats);
    if (repairedSegment !== segment) {
      segments[index] = repairedSegment;
    }
  }
  working = segments.join("```");

  return { repaired: working, stats };
}

function balanceMarks(segment: string, stats: IncompleteRepairStats): string {
  let result = segment;
  for (const pair of MARK_PAIRS) {
    const occurrences = countOccurrences(result, pair.open);
    if (occurrences % 2 === 1) {
      result += pair.close;
      stats.balancedMarks += 1;
    }
  }
  // Unterminated inline code (odd number of single backticks outside fences).
  const backticks = countUnpairedInlineBackticks(result);
  if (backticks % 2 === 1) {
    result += "`";
    stats.balancedMarks += 1;
  }
  return result;
}

function splitOutsideFences(text: string): string[] {
  return text.split("```");
}

function countOccurrences(haystack: string, needle: string): number {
  let count = 0;
  let offset = haystack.indexOf(needle);
  while (offset !== -1) {
    count += 1;
    offset = haystack.indexOf(needle, offset + needle.length);
  }
  return count;
}

function countUnpairedInlineBackticks(text: string): number {
  // Rough heuristic: count backticks not already counted as fence delimiters.
  let count = 0;
  let offset = text.indexOf("`");
  while (offset !== -1) {
    count += 1;
    offset = text.indexOf("`", offset + 1);
  }
  return count;
}

/** FNV-1a 32-bit hash: cheap equality proxy for large streamed strings. */
export function fnv1aHash(text: string): string {
  let hash = 0x811c9dc5;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16);
}
