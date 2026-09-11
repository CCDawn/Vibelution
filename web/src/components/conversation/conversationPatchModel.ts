import type { CodexTranscriptCell } from "./codexTranscriptCells";

export type ConversationPatchLineKind = "add" | "del" | "context" | "hunk";

export type ConversationPatchLine = {
  kind: ConversationPatchLineKind;
  text: string;
  oldLine?: number;
  newLine?: number;
};

export type ConversationPatchFileOp = "update" | "add" | "delete" | "unknown";

export type ConversationPatchFile = {
  path: string;
  moveTo?: string;
  op: ConversationPatchFileOp;
  additions: number;
  deletions: number;
  lines: ConversationPatchLine[];
};

export type ConversationPatchDiff = {
  files: ConversationPatchFile[];
  additions: number;
  deletions: number;
  lineCount: number;
  truncated: boolean;
};

const PATCH_ARGUMENT_KEYS = ["patch_text", "patchText", "patch", "diff"] as const;
const HUNK_HEADER = /^@@(?:\s+-(\d+)(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@)?/;

function emptyPatchDiff(): ConversationPatchDiff {
  return { files: [], additions: 0, deletions: 0, lineCount: 0, truncated: false };
}

function currentFile(files: ConversationPatchFile[]): ConversationPatchFile | null {
  return files.length > 0 ? files[files.length - 1] : null;
}

function startFile(files: ConversationPatchFile[], path: string, op: ConversationPatchFileOp): ConversationPatchFile {
  const file: ConversationPatchFile = { path, op, additions: 0, deletions: 0, lines: [] };
  files.push(file);
  return file;
}

/**
 * Parses the canonical Codex `apply_patch` text (and plain unified diffs) into
 * renderable files and lines. Unknown lines are kept as context so the raw
 * patch stays inspectable instead of being silently dropped.
 */
export function buildConversationPatchDiff(patchText: string): ConversationPatchDiff {
  const text = String(patchText || "");
  if (!text.trim()) {
    return emptyPatchDiff();
  }
  const diff = emptyPatchDiff();
  diff.truncated = text.trimEnd().endsWith("…");
  const files = diff.files;
  let oldCursor = 0;
  let newCursor = 0;
  let numbered = false;
  const pushLine = (
    file: ConversationPatchFile,
    kind: ConversationPatchLineKind,
    raw: string,
    numbering: "old" | "new" | "both" | "none",
  ) => {
    const line: ConversationPatchLine = { kind, text: raw };
    if (numbering === "old" || numbering === "both") {
      line.oldLine = numbered ? oldCursor : undefined;
      oldCursor += 1;
    }
    if (numbering === "new" || numbering === "both") {
      line.newLine = numbered ? newCursor : undefined;
      newCursor += 1;
    }
    file.lines.push(line);
    diff.lineCount += 1;
  };
  const pushContext = (file: ConversationPatchFile | null, raw: string) => {
    const target = file ?? startFile(files, "", "unknown");
    pushLine(target, "context", raw, "both");
  };

  const lines = text.split(/\r?\n/);
  for (let index = 0; index < lines.length; index += 1) {
    const rawLine = lines[index];
    const nextLine = lines[index + 1];
    const fileMatch = /^\*\*\* (Update|Add|Delete) File: (.+)$/.exec(rawLine);
    if (fileMatch) {
      const op = fileMatch[1] === "Update" ? "update" : fileMatch[1] === "Add" ? "add" : "delete";
      startFile(files, fileMatch[2].trim(), op);
      oldCursor = 0;
      newCursor = 0;
      numbered = false;
      continue;
    }
    if (/^\*\*\* (Begin Patch|End Patch)\s*$/.test(rawLine)) {
      continue;
    }
    const moveMatch = /^\*\*\* Move to: (.+)$/.exec(rawLine);
    if (moveMatch) {
      const file = currentFile(files);
      if (file) {
        file.moveTo = moveMatch[1].trim();
      }
      continue;
    }
    if (/^(diff --git|index |new file mode|deleted file mode|similarity index|rename (from|to) )/.test(rawLine)) {
      continue;
    }
    const oldPathMatch = /^--- (?:a\/)?(.+)$/.exec(rawLine);
    if (oldPathMatch && typeof nextLine === "string" && nextLine.startsWith("+++ ")) {
      continue;
    }
    const newPathMatch = /^\+\+\+ (?:b\/)?(.+)$/.exec(rawLine);
    if (newPathMatch && lines[index - 1]?.startsWith("--- ")) {
      const path = newPathMatch[1].trim();
      const file = currentFile(files);
      if (file && !file.path) {
        file.path = path;
      } else if (!file || file.path !== path) {
        startFile(files, path, "unknown");
      }
      oldCursor = 0;
      newCursor = 0;
      numbered = false;
      continue;
    }
    const hunkMatch = HUNK_HEADER.exec(rawLine);
    if (hunkMatch) {
      const file = currentFile(files) ?? startFile(files, "", "unknown");
      if (hunkMatch[1]) oldCursor = Number(hunkMatch[1]);
      if (hunkMatch[2]) newCursor = Number(hunkMatch[2]);
      numbered = Boolean(hunkMatch[1] && hunkMatch[2]);
      pushLine(file, "hunk", rawLine, "none");
      continue;
    }
    if (rawLine.startsWith("+")) {
      const file = currentFile(files) ?? startFile(files, "", "unknown");
      pushLine(file, "add", rawLine.slice(1), "new");
      file.additions += 1;
      diff.additions += 1;
      continue;
    }
    if (rawLine.startsWith("-")) {
      const file = currentFile(files) ?? startFile(files, "", "unknown");
      pushLine(file, "del", rawLine.slice(1), "old");
      file.deletions += 1;
      diff.deletions += 1;
      continue;
    }
    if (rawLine.startsWith(" ")) {
      pushContext(currentFile(files), rawLine.slice(1));
      continue;
    }
    if (rawLine === "\\ No newline at end of file") {
      continue;
    }
    pushContext(currentFile(files), rawLine);
  }

  diff.files = files.filter((file) => file.path || file.lines.length > 0);
  return diff;
}

/** Reads the patch payload from a transcript tool cell's canonical arguments. */
export function conversationToolPatchText(cell: CodexTranscriptCell): string {
  const candidates: Array<Record<string, unknown> | undefined> = [];
  const toolCalls = cell.toolLifecycleModel?.toolCalls ?? [];
  const operationIds = new Set(cell.operationIds ?? []);
  const matched = operationIds.size > 0
    ? toolCalls.filter((toolCall) =>
      operationIds.has(toolCall.rawOperationId)
      || operationIds.has(toolCall.toolCallId)
      || (toolCall.terminalOperationId ? operationIds.has(toolCall.terminalOperationId) : false))
    : [];
  for (const toolCall of matched.length > 0 ? matched : toolCalls) {
    candidates.push(toolCall.arguments);
  }
  candidates.push(cell.toolArguments);
  for (const argumentsRecord of candidates) {
    if (!argumentsRecord) {
      continue;
    }
    for (const key of PATCH_ARGUMENT_KEYS) {
      const value = argumentsRecord[key];
      if (typeof value === "string" && value.trim()) {
        return value;
      }
    }
  }
  return "";
}
