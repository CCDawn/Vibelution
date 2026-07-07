export type CodexStreamSegmentKind = "stable" | "tail";

export type CodexStreamSegment = {
  kind: CodexStreamSegmentKind;
  source: string;
};

export type CodexStreamDrainResult = {
  segments: CodexStreamSegment[];
  consolidatedSource: string;
  allIdle: boolean;
};

export type CodexStreamSnapshot = {
  emittedStableText: string;
  queuedStableText: string;
  liveTailText: string;
  consolidatedSource: string;
};

type CodexStreamControllerOptions = {
  nowMs?: () => number;
};

type CodexStreamDrainOptions = {
  nowMs?: number;
};

type QueuedSegment = {
  source: string;
  queuedAtMs: number;
};

const ENTER_CATCH_UP_QUEUE_DEPTH = 8;
const ENTER_CATCH_UP_OLDEST_AGE_MS = 120;

export function createCodexStreamController(options: CodexStreamControllerOptions = {}) {
  return new CodexStreamController(options);
}

class CodexStreamController {
  private readonly nowMs: () => number;
  private collector = "";
  private committedSource = "";
  private emittedStableText = "";
  private queuedSegments: QueuedSegment[] = [];
  private liveTailText = "";

  constructor(options: CodexStreamControllerOptions) {
    this.nowMs = options.nowMs ?? Date.now;
  }

  push(delta: string) {
    if (!delta) {
      return;
    }
    this.collector += normalizeNewlines(delta);
    this.commitCompleteSource();
  }

  drainTick(options: CodexStreamDrainOptions = {}): CodexStreamDrainResult {
    const nowMs = options.nowMs ?? this.nowMs();
    const count = this.shouldCatchUp(nowMs) ? this.queuedSegments.length : Math.min(1, this.queuedSegments.length);
    const drained = this.queuedSegments.splice(0, count);
    const text = drained.map((segment) => segment.source).join("");
    if (text) {
      this.emittedStableText += text;
    }
    return {
      segments: text ? [{ kind: "stable", source: text }] : [],
      consolidatedSource: this.consolidatedSource(),
      allIdle: this.queuedSegments.length === 0,
    };
  }

  finalize(): CodexStreamDrainResult {
    const remainder = this.collector.slice(this.committedSource.length);
    if (remainder) {
      this.committedSource += ensureTrailingNewline(remainder);
    }
    const unprocessedSource = this.committedSource.slice(this.emittedStableText.length);
    const consolidatedSource = this.committedSource;
    this.reset();
    return {
      segments: unprocessedSource ? [{ kind: "tail", source: unprocessedSource }] : [],
      consolidatedSource,
      allIdle: true,
    };
  }

  snapshot(): CodexStreamSnapshot {
    return {
      emittedStableText: this.emittedStableText,
      queuedStableText: this.queuedSegments.map((segment) => segment.source).join(""),
      liveTailText: this.liveTailText,
      consolidatedSource: this.consolidatedSource(),
    };
  }

  private commitCompleteSource() {
    const commitEnd = this.collector.lastIndexOf("\n") + 1;
    if (commitEnd <= this.committedSource.length) {
      this.updateLiveTail();
      return;
    }

    this.committedSource = this.collector.slice(0, commitEnd);
    this.rebuildStableQueue();
    this.updateLiveTail();
  }

  private rebuildStableQueue() {
    const stableEnd = stableCommitEnd(this.committedSource);
    const emittedLen = this.emittedStableText.length;
    const queuedText = this.queuedSegments.map((segment) => segment.source).join("");
    const queuedStart = emittedLen + queuedText.length;
    if (stableEnd <= queuedStart) {
      if (stableEnd < queuedStart) {
        this.queuedSegments = [];
      }
      return;
    }

    const newStableText = this.committedSource.slice(queuedStart, stableEnd);
    for (const segment of splitCompleteLineSegments(newStableText, this.nowMs())) {
      this.queuedSegments.push(segment);
    }
  }

  private updateLiveTail() {
    const stableEnd = stableCommitEnd(this.committedSource);
    const committedTail = this.committedSource.slice(stableEnd);
    const partialTail = this.collector.slice(this.committedSource.length);
    this.liveTailText = committedTail + partialTail;
  }

  private shouldCatchUp(nowMs: number) {
    if (this.queuedSegments.length >= ENTER_CATCH_UP_QUEUE_DEPTH) {
      return true;
    }
    const oldest = this.queuedSegments[0];
    return Boolean(oldest && nowMs - oldest.queuedAtMs >= ENTER_CATCH_UP_OLDEST_AGE_MS);
  }

  private consolidatedSource() {
    return this.committedSource + this.collector.slice(this.committedSource.length);
  }

  private reset() {
    this.collector = "";
    this.committedSource = "";
    this.emittedStableText = "";
    this.queuedSegments = [];
    this.liveTailText = "";
  }
}

function normalizeNewlines(value: string) {
  return String(value ?? "").replace(/\r\n/g, "\n");
}

function ensureTrailingNewline(value: string) {
  return value.endsWith("\n") ? value : `${value}\n`;
}

function splitCompleteLineSegments(source: string, queuedAtMs: number): QueuedSegment[] {
  if (!source) {
    return [];
  }
  const lines = source.match(/[^\n]*\n/g) ?? [];
  const segments: string[] = [];
  for (const line of lines) {
    if (line.trim() === "" && segments.length > 0) {
      segments[segments.length - 1] += line;
      continue;
    }
    segments.push(line);
  }
  return segments.map((segment) => ({ source: segment, queuedAtMs }));
}

function stableCommitEnd(source: string) {
  const openFenceStart = openCodeFenceStart(source);
  if (openFenceStart !== null) {
    return openFenceStart;
  }
  const tableStart = markdownTableHoldbackStart(source);
  if (tableStart !== null) {
    return tableStart;
  }
  return source.length;
}

function openCodeFenceStart(source: string) {
  let openFenceStart: number | null = null;
  let cursor = 0;
  for (const line of source.split(/(?<=\n)/)) {
    if (/^\s*```[A-Za-z0-9_+.-]*\s*\n?$/.test(line)) {
      openFenceStart = openFenceStart === null ? cursor : null;
    }
    cursor += line.length;
  }
  return openFenceStart;
}

function markdownTableHoldbackStart(source: string) {
  const lines = source.split(/(?<=\n)/);
  const starts: number[] = [];
  let cursor = 0;
  for (let index = 0; index < lines.length; index += 1) {
    starts[index] = cursor;
    cursor += lines[index].length;
  }

  for (let index = 0; index < lines.length - 1; index += 1) {
    if (isMarkdownTableHeader(lines, index)) {
      return starts[index];
    }
  }
  return null;
}

function isMarkdownTableHeader(lines: string[], index: number) {
  return isMarkdownTableRow(lines[index]) && isMarkdownTableSeparator(lines[index + 1] ?? "");
}

function isMarkdownTableRow(line: string) {
  const trimmed = String(line ?? "").trim();
  return trimmed.startsWith("|") && trimmed.includes("|", 1);
}

function isMarkdownTableSeparator(line: string) {
  const cells = String(line ?? "")
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}
