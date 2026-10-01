import type { MemoryAgentMemoryItemView } from "../MemoryAgentMemoryPanel";
import { toReadableMemoryBlocks, type ReadableMemoryBlock } from "./memoryReadableContent";

export type AgentMemoryReaderItem = MemoryAgentMemoryItemView & {
  readerTitle: string;
  excerpt: string;
  category: "content" | "initialization";
  blocks: ReadableMemoryBlock[];
};

const INITIAL_MEMORY_JSON_SCHEMAS: Array<Record<string, string | number | null>> = [
  {
    core_wisdom: "初始状态",
    current_goal: "",
    last_archive_time: null,
  },
  {
    current_generation: 1,
    core_wisdom: "初始状态",
    current_goal: "熟悉环境",
    last_archive_time: null,
  },
];

const EXCERPT_LIMIT = 240;

export function buildAgentMemoryReaderItems(
  items: MemoryAgentMemoryItemView[],
  lang: "zh" | "en" = "zh",
): AgentMemoryReaderItem[] {
  return items.map((item) => {
    const content = item.content || "";
    const blocks = toReadableMemoryBlocks(content);
    const fileName = getFileName(item.title, item.path);
    const readerTitle = (isMarkdown(item.contentType, fileName) ? findMarkdownTitle(content) : "")
      || fileName
      || item.id.trim()
      || (lang === "zh" ? "未命名记忆" : "Untitled memory");
    const bodyExcerpt = excerptFromBlocks(blocks);

    return {
      ...item,
      readerTitle,
      excerpt: clipExcerpt(bodyExcerpt || summaryExcerpt(item.summary)),
      category: isInitialMemoryIndex(item, content) ? "initialization" : "content",
      blocks,
    };
  });
}

function isInitialMemoryIndex(item: MemoryAgentMemoryItemView, content: string): boolean {
  if (item.truncated || getFileName(item.title, item.path) !== "memory.json" || !content.trim()) {
    return false;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(content);
  } catch {
    return false;
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    return false;
  }

  const record = parsed as Record<string, unknown>;
  return INITIAL_MEMORY_JSON_SCHEMAS.some((schema) => {
    const keys = Object.keys(schema);
    return Object.keys(record).length === keys.length
      && keys.every((key) => Object.hasOwn(record, key) && record[key] === schema[key]);
  });
}

function getFileName(title: string, path: string): string {
  const candidate = title.trim() || path.trim();
  return candidate.split(/[\\/]/).filter(Boolean).at(-1) || "";
}

function isMarkdown(contentType: string, fileName: string): boolean {
  return /markdown/i.test(contentType) || /\.(?:md|markdown)$/i.test(fileName);
}

function findMarkdownTitle(content: string): string {
  let fenceMarker = "";
  for (const line of content.split(/\r?\n/)) {
    const fence = line.match(/^\s{0,3}(`{3,}|~{3,})/);
    if (fence) {
      const marker = fence[1][0];
      if (!fenceMarker) {
        fenceMarker = marker;
      } else if (fenceMarker === marker) {
        fenceMarker = "";
      }
      continue;
    }
    if (fenceMarker) {
      continue;
    }

    const heading = line.match(/^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$/);
    if (heading?.[1]) {
      return heading[1].trim();
    }
  }
  return "";
}

function excerptFromBlocks(blocks: ReadableMemoryBlock[]): string {
  return blocks
    .flatMap((block) => {
      if (block.kind === "paragraph") {
        return [block.text];
      }
      if (block.kind === "fields") {
        return block.entries.map(({ label, value }) => `${label}：${value}`);
      }
      return block.items;
    })
    .join("；")
    .replace(/\s+/g, " ")
    .trim();
}

function summaryExcerpt(summary: string): string {
  const value = summary.trim();
  if (/^Agent 私有记忆文件[:：]/i.test(value)) {
    return "";
  }
  return value;
}

function clipExcerpt(value: string): string {
  if (value.length <= EXCERPT_LIMIT) {
    return value;
  }
  return `${value.slice(0, EXCERPT_LIMIT).trimEnd()}…`;
}
