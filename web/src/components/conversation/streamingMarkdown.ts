export type MarkdownBlock =
  | { type: "heading"; level: 1 | 2 | 3 | 4; content: string }
  | { type: "paragraph"; content: string }
  | { type: "image"; alt: string; url: string }
  | { type: "table"; headers: string[]; rows: string[][] }
  | { type: "unorderedList"; items: string[] }
  | { type: "orderedList"; items: string[] }
  | { type: "blockquote"; content: string }
  | { type: "code"; content: string; language: string; open: boolean }
  | { type: "divider" };

export const STREAMING_MARKDOWN_LIVE_TAIL_CHARS = 960;

export type StreamingMarkdownProjection = {
  stableText: string;
  liveText: string;
  stableBlocks: MarkdownBlock[];
  liveBlocks: MarkdownBlock[];
  blocks: MarkdownBlock[];
};

const STABLE_MARKDOWN_BLOCK_CACHE_LIMIT = 120;
const stableMarkdownBlockCache = new Map<string, MarkdownBlock[]>();
let lastStableMarkdownSplitCache:
  | {
    content: string;
    targetIndex: number;
    splitIndex: number;
    stableText: string;
    liveText: string;
  }
  | null = null;

export function projectStreamingMarkdownBlocks(content: string): StreamingMarkdownProjection {
  const normalizedContent = normalizeStreamingMarkdownContent(content);
  const { stableText, liveText } = splitStableMarkdownText(normalizedContent);
  const stableBlocks = stableText ? cachedStableMarkdownBlocks(stableText) : [];
  const liveBlocks = liveText ? parseStreamingMarkdownBlocks(liveText) : [];
  return {
    stableText,
    liveText,
    stableBlocks,
    liveBlocks,
    blocks: [...stableBlocks, ...liveBlocks],
  };
}

export function parseStreamingMarkdownBlocks(content: string): MarkdownBlock[] {
  const lines = normalizeStreamingMarkdownContent(content).split("\n");
  const blocks: MarkdownBlock[] = [];
  let paragraphLines: string[] = [];

  function flushParagraph() {
    const paragraph = paragraphLines.join("\n").trim();
    if (paragraph) {
      blocks.push({ type: "paragraph", content: paragraph });
    }
    paragraphLines = [];
  }

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const trimmed = line.trim();
    if (!trimmed) {
      flushParagraph();
      continue;
    }

    const codeFence = trimmed.match(/^```([A-Za-z0-9_+.-]*)\s*$/);
    if (codeFence) {
      flushParagraph();
      const codeLines: string[] = [];
      const language = codeFence[1]?.trim() || "text";
      let closed = false;
      index += 1;
      for (; index < lines.length; index += 1) {
        if (/^\s*```\s*$/.test(lines[index])) {
          closed = true;
          break;
        }
        codeLines.push(lines[index]);
      }
      blocks.push({ type: "code", content: codeLines.join("\n"), language, open: !closed });
      continue;
    }

    const image = trimmed.match(/^!\[([^\]]*)\]\(([^)\s]+)\)$/);
    if (image) {
      flushParagraph();
      blocks.push({ type: "image", alt: image[1].trim(), url: image[2].trim() });
      continue;
    }

    const heading = trimmed.match(/^(#{1,4})\s+(.+?)\s*#*$/);
    if (heading) {
      flushParagraph();
      blocks.push({
        type: "heading",
        level: Math.min(4, heading[1].length) as 1 | 2 | 3 | 4,
        content: heading[2].trim(),
      });
      continue;
    }

    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      flushParagraph();
      blocks.push({ type: "divider" });
      continue;
    }

    if (isMarkdownTableHeader(lines, index)) {
      flushParagraph();
      const headers = parseMarkdownTableRow(lines[index]);
      const rows: string[][] = [];
      index += 2;
      for (; index < lines.length; index += 1) {
        if (!isStreamingTableRow(lines[index])) {
          index -= 1;
          break;
        }
        rows.push(parseMarkdownTableRow(lines[index]));
      }
      blocks.push({ type: "table", headers, rows });
      continue;
    }

    const quoteMatch = trimmed.match(/^>\s?(.*)$/);
    if (quoteMatch) {
      flushParagraph();
      const quoteLines = [quoteMatch[1].trim()];
      for (let nextIndex = index + 1; nextIndex < lines.length; nextIndex += 1) {
        const nextMatch = lines[nextIndex].trim().match(/^>\s?(.*)$/);
        if (!nextMatch) {
          break;
        }
        quoteLines.push(nextMatch[1].trim());
        index = nextIndex;
      }
      blocks.push({ type: "blockquote", content: quoteLines.join("\n").trim() });
      continue;
    }

    const unorderedMatch = trimmed.match(/^[-*]\s+(.+)$/);
    if (unorderedMatch) {
      flushParagraph();
      const items = [unorderedMatch[1].trim()];
      for (let nextIndex = index + 1; nextIndex < lines.length; nextIndex += 1) {
        const nextMatch = lines[nextIndex].trim().match(/^[-*]\s+(.+)$/);
        if (!nextMatch) {
          break;
        }
        items.push(nextMatch[1].trim());
        index = nextIndex;
      }
      blocks.push({ type: "unorderedList", items });
      continue;
    }

    const orderedMatch = trimmed.match(/^\d+[.)]\s+(.+)$/);
    if (orderedMatch) {
      flushParagraph();
      const items = [orderedMatch[1].trim()];
      for (let nextIndex = index + 1; nextIndex < lines.length; nextIndex += 1) {
        const nextMatch = lines[nextIndex].trim().match(/^\d+[.)]\s+(.+)$/);
        if (!nextMatch) {
          break;
        }
        items.push(nextMatch[1].trim());
        index = nextIndex;
      }
      blocks.push({ type: "orderedList", items });
      continue;
    }

    paragraphLines.push(line);
  }

  flushParagraph();
  return blocks;
}

function normalizeStreamingMarkdownContent(content: string) {
  return String(content ?? "").replace(/\r\n/g, "\n");
}

function cachedStableMarkdownBlocks(stableText: string) {
  const cached = stableMarkdownBlockCache.get(stableText);
  if (cached) {
    return cached;
  }
  const blocks = parseStreamingMarkdownBlocks(stableText);
  stableMarkdownBlockCache.set(stableText, blocks);
  if (stableMarkdownBlockCache.size > STABLE_MARKDOWN_BLOCK_CACHE_LIMIT) {
    const oldestKey = stableMarkdownBlockCache.keys().next().value;
    if (oldestKey) {
      stableMarkdownBlockCache.delete(oldestKey);
    }
  }
  return blocks;
}

function splitStableMarkdownText(content: string): { stableText: string; liveText: string } {
  if (content.length <= STREAMING_MARKDOWN_LIVE_TAIL_CHARS) {
    return { stableText: "", liveText: content };
  }
  const cached = growingStableMarkdownSplit(content);
  if (cached) {
    return cached;
  }
  const targetIndex = stableMarkdownTargetIndex(content);
  let splitIndex = stableMarkdownSplitIndex(content);
  if (splitIndex <= 0) {
    return rememberStableMarkdownSplit(content, targetIndex, 0);
  }

  splitIndex = safeStableSplitIndexForCodeFence(content, 0, splitIndex);
  const tableHoldbackStart = recentMarkdownTableHoldbackStart(content, splitIndex);
  if (tableHoldbackStart !== null) {
    splitIndex = tableHoldbackStart;
  }
  if (splitIndex <= 0) {
    return rememberStableMarkdownSplit(content, targetIndex, 0);
  }

  return rememberStableMarkdownSplit(content, targetIndex, splitIndex);
}

function growingStableMarkdownSplit(content: string): { stableText: string; liveText: string } | null {
  const cached = lastStableMarkdownSplitCache;
  if (!cached || !content.startsWith(cached.content)) {
    return null;
  }
  const targetIndex = stableMarkdownTargetIndex(content);
  if (targetIndex < cached.targetIndex) {
    return null;
  }

  let splitIndex = cached.splitIndex;
  const nextSplitIndex = stableMarkdownSplitIndexInRange(content, cached.targetIndex, targetIndex);
  if (nextSplitIndex > splitIndex) {
    splitIndex = safeStableSplitIndexForCodeFence(content, cached.splitIndex, nextSplitIndex);
    const tableHoldbackStart = recentMarkdownTableHoldbackStart(content, splitIndex);
    if (tableHoldbackStart !== null) {
      splitIndex = tableHoldbackStart;
    }
  }
  return rememberStableMarkdownSplit(content, targetIndex, splitIndex);
}

function rememberStableMarkdownSplit(
  content: string,
  targetIndex: number,
  splitIndex: number,
): { stableText: string; liveText: string } {
  const stableText = splitIndex > 0 ? content.slice(0, splitIndex).trimEnd() : "";
  const liveText = splitIndex > 0 ? content.slice(splitIndex).replace(/^\n+/, "") : content;
  lastStableMarkdownSplitCache = {
    content,
    targetIndex,
    splitIndex,
    stableText,
    liveText,
  };
  return { stableText, liveText };
}

function stableMarkdownTargetIndex(content: string) {
  return Math.max(0, content.length - STREAMING_MARKDOWN_LIVE_TAIL_CHARS);
}

function stableMarkdownSplitIndex(content: string) {
  return stableMarkdownSplitIndexInRange(content, 0, stableMarkdownTargetIndex(content));
}

function stableMarkdownSplitIndexInRange(content: string, startIndex: number, endIndex: number) {
  const start = Math.max(0, startIndex - 2);
  const end = Math.min(Math.max(0, endIndex), content.length);
  let searchIndex = end;
  while (searchIndex > start) {
    const secondNewline = content.lastIndexOf("\n", searchIndex - 1);
    if (secondNewline < start) {
      return 0;
    }
    let cursor = secondNewline - 1;
    while (cursor >= start && content[cursor] !== "\n" && /\s/.test(content[cursor])) {
      cursor -= 1;
    }
    if (cursor >= start && content[cursor] === "\n") {
      return secondNewline + 1;
    }
    searchIndex = secondNewline;
  }
  return 0;
}

function safeStableSplitIndexForCodeFence(content: string, startIndex: number, splitIndex: number) {
  const openFenceStart = openCodeFenceStartInRange(content, startIndex, splitIndex);
  return openFenceStart ?? splitIndex;
}

function openCodeFenceStartInRange(content: string, startIndex: number, endIndex: number) {
  const start = previousLineStart(content, startIndex);
  const end = Math.min(Math.max(0, endIndex), content.length);
  let open = false;
  let lastFenceStart = 0;
  let lineStart = start;
  while (lineStart < end) {
    const lineEnd = content.indexOf("\n", lineStart);
    const boundedLineEnd = lineEnd < 0 || lineEnd > end ? end : lineEnd;
    const line = content.slice(lineStart, boundedLineEnd).trim();
    if (/^```[A-Za-z0-9_+.-]*\s*$/.test(line)) {
      open = !open;
      lastFenceStart = lineStart;
    }
    if (lineEnd < 0 || lineEnd >= end) {
      break;
    }
    lineStart = lineEnd + 1;
  }
  return open ? lastFenceStart : null;
}

function recentMarkdownTableHoldbackStart(content: string, splitIndex: number) {
  const windowStart = previousLineStart(
    content,
    Math.max(0, splitIndex - STREAMING_MARKDOWN_LIVE_TAIL_CHARS * 3),
  );
  const windowText = content.slice(windowStart, splitIndex);
  const lines = windowText.split("\n");
  const lineStarts: number[] = [];
  let position = 0;
  for (let index = 0; index < lines.length; index += 1) {
    lineStarts[index] = windowStart + position;
    position += lines[index].length + (index < lines.length - 1 ? 1 : 0);
  }

  let holdbackStart: number | null = null;
  for (let index = 0; index < lines.length; index += 1) {
    if (!isMarkdownTableHeader(lines, index)) {
      continue;
    }
    const tableStart = lineStarts[index];
    let afterTableIndex = index + 2;
    while (afterTableIndex < lines.length && isStreamingTableRow(lines[afterTableIndex])) {
      afterTableIndex += 1;
    }
    const lastTableLineIndex = afterTableIndex - 1;
    const tableEnd = lineStarts[lastTableLineIndex] + lines[lastTableLineIndex].length;
    if (
      tableStart < splitIndex
      && tableEnd <= splitIndex
      && splitIndex - tableStart <= STREAMING_MARKDOWN_LIVE_TAIL_CHARS * 3
    ) {
      holdbackStart = tableStart;
    }
    index = afterTableIndex - 1;
  }
  return holdbackStart;
}

function previousLineStart(content: string, index: number) {
  const boundedIndex = Math.min(Math.max(0, index), content.length);
  const previousNewline = content.lastIndexOf("\n", Math.max(0, boundedIndex - 1));
  return previousNewline < 0 ? 0 : previousNewline + 1;
}

function isMarkdownTableHeader(lines: string[], index: number) {
  return isStreamingTableRow(lines[index]) && isMarkdownTableSeparator(lines[index + 1] ?? "");
}

function isStreamingTableRow(line: string) {
  const trimmed = String(line ?? "").trim();
  return trimmed.startsWith("|") && trimmed.includes("|", 1);
}

function isMarkdownTableSeparator(line: string) {
  const cells = parseMarkdownTableRow(line);
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function parseMarkdownTableRow(line: string) {
  return String(line ?? "")
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}
