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
  let splitIndex = stableMarkdownSplitIndex(content);
  if (splitIndex <= 0) {
    return { stableText: "", liveText: content };
  }

  const stableCandidate = content.slice(0, splitIndex);
  if (hasOpenCodeFence(stableCandidate)) {
    splitIndex = lastCodeFenceLineStart(stableCandidate);
  }
  if (splitIndex <= 0) {
    return { stableText: "", liveText: content };
  }

  return {
    stableText: content.slice(0, splitIndex).trimEnd(),
    liveText: content.slice(splitIndex).replace(/^\n+/, ""),
  };
}

function stableMarkdownSplitIndex(content: string) {
  const targetIndex = Math.max(0, content.length - STREAMING_MARKDOWN_LIVE_TAIL_CHARS);
  const searchText = content.slice(0, targetIndex);
  const boundaries = [...searchText.matchAll(/\n\s*\n/g)];
  const boundary = boundaries[boundaries.length - 1];
  if (!boundary || boundary.index === undefined) {
    return 0;
  }
  return boundary.index + boundary[0].length;
}

function codeFenceLineStarts(content: string) {
  return [...content.matchAll(/(^|\n)```[A-Za-z0-9_+.-]*\s*($|\n)/g)].map((match) => {
    const index = match.index ?? 0;
    return match[1] === "\n" ? index + 1 : index;
  });
}

function hasOpenCodeFence(content: string) {
  return codeFenceLineStarts(content).length % 2 === 1;
}

function lastCodeFenceLineStart(content: string) {
  const starts = codeFenceLineStarts(content);
  return starts[starts.length - 1] ?? 0;
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
