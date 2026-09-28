import type { CodexTranscriptCell } from "./codexTranscriptCells";
import { buildConversationPatchDiff, patchTextFromArguments } from "./conversationPatchModel";

export type ConversationFileDelivery = {
  path: string;
  content?: string;
  deleted: boolean;
};

/** Per-turn disk-truth change summary from assistant message metadata (`metadata.changedFiles`). */
export type ConversationChangedFileSummary = {
  path: string;
  additions?: number;
  deletions?: number;
  state?: ConversationFileDeliveryState;
};

export type ConversationFileDeliveryState = "created" | "modified" | "deleted" | string;

/** Delivery row enriched with the disk-truth state and +/- line counts when known. */
export type ConversationFileDeliveryView = ConversationFileDelivery & {
  additions?: number;
  deletions?: number;
  state?: ConversationFileDeliveryState;
};

const WRITE_TOOLS = new Set(["write_file_tool", "create_file", "create_file_tool", "write_file"]);
const PATCH_TOOLS = new Set(["apply_patch_tool", "apply_patch", "apply_patch_edit"]);
const REPLACE_TOOLS = new Set(["apply_diff_edit_tool", "apply_diff_edit", "edit_file", "edit_local_file"]);
const MAX_CONTENT = 200_000;

function replacementPatch(path: string, args: Record<string, unknown>): string {
  if (/[\r\n]/.test(path)) return "";
  const blocks: Array<[string, string]> = [];
  if (typeof args.search_string === "string" && typeof args.replace_string === "string") {
    blocks.push([args.search_string, args.replace_string]);
  } else if (typeof args.diff_text === "string" && args.diff_text.length <= MAX_CONTENT) {
    if (args.diff_text.trimStart().startsWith("*** Begin Patch")) return args.diff_text;
    const pattern = /<<<<<<<\s*(?:SEARCH)?\s*\n([\s\S]*?)\n=======\s*\n([\s\S]*?)\n>>>>>>>(?:\s*REPLACE)?/g;
    for (const match of args.diff_text.matchAll(pattern)) blocks.push([match[1], match[2]]);
  }
  if (!blocks.length) return "";
  return ["*** Begin Patch", `*** Update File: ${path}`, ...blocks.flatMap(([before, after]) => [
    "@@", ...before.split(/\r?\n/).map((line) => `-${line}`), ...after.split(/\r?\n/).map((line) => `+${line}`),
  ]), "*** End Patch"].join("\n");
}

/** Read-only projection of successful calls in ONE turn. Never use session changedFiles. */
export function collectConversationFileDeliveries(cells: readonly CodexTranscriptCell[]) {
  const files = new Map<string, ConversationFileDelivery>();
  const patches: Array<{ id: string; text: string }> = [];
  const seen = new Set<string>();
  for (const cell of cells) {
    if (cell.kind !== "tool_call") continue;
    for (const call of cell.toolLifecycleModel?.toolCalls ?? []) {
      if (call.status !== "completed" || call.error) continue;
      const ids = cell.operationIds;
      if (ids?.length && !ids.includes(call.rawOperationId) && !ids.includes(call.toolCallId)) continue;
      const id = call.toolCallId || call.rawOperationId;
      if (!id || seen.has(id)) continue;
      seen.add(id);
      if (/\[(?:FAIL|ERROR|SECURITY)\]|\[(?:编辑|文件编辑|patch)\]\s*(?:错误|格式错误|格式验证失败)/i.test(call.resultPreview || "")) continue;
      const name = (call.rawToolName || "").split(".").at(-1) || "";
      const args = call.arguments;
      if (WRITE_TOOLS.has(name) && args) {
        const path = typeof args.file_path === "string" ? args.file_path : args.path;
        if (typeof path !== "string" || !path.trim()) continue;
        const content = typeof args.content === "string" && args.content.length <= MAX_CONTENT
          && !args.content.trimEnd().endsWith("…") ? args.content : undefined;
        files.set(path, { path, content, deleted: false });
      } else if (PATCH_TOOLS.has(name) || REPLACE_TOOLS.has(name)) {
        const path = typeof args?.file_path === "string" ? args.file_path : "";
        if (REPLACE_TOOLS.has(name) && path) files.set(path, { path, content: undefined, deleted: false });
        const text = REPLACE_TOOLS.has(name) && args && path
          ? replacementPatch(path, args) : patchTextFromArguments(args);
        if (!text || text.length > MAX_CONTENT) continue;
        const patch = buildConversationPatchDiff(text);
        patches.push({ id, text });
        for (const file of patch.files) {
          if (!file.path) continue;
          if (file.moveTo) files.delete(file.path);
          const path = file.moveTo || file.path;
          // A patch update is NOT a complete file. Invalidate any earlier write snapshot.
          files.set(path, {
            path,
            deleted: file.op === "delete",
            content: file.op === "add" && !patch.truncated
              ? file.lines.filter((line) => line.kind === "add").map((line) => line.text).join("\n")
              : undefined,
          });
        }
      }
    }
  }
  return { files: [...files.values()], patches };
}

export function fileDeliveryFollowupDraft(draft: string, path: string, language: "zh" | "en") {
  const request = language === "zh"
    ? `请继续修改文件 ${JSON.stringify(path)}：`
    : `Please continue editing ${JSON.stringify(path)}: `;
  return draft.trim() ? `${draft}\n\n${request}` : request;
}

/**
 * Tool args carry absolute OS paths while the ledger summary carries
 * project-relative posix paths; compare on slashes/drive/leading-dot noise.
 */
function normalizeDeliveryPath(path: string): string {
  return path.replace(/\\/g, "/").replace(/^[A-Za-z]:/, "").replace(/^\/+/, "").replace(/^\.\//, "");
}

function sameDeliveryPath(a: string, b: string): boolean {
  const left = normalizeDeliveryPath(a);
  const right = normalizeDeliveryPath(b);
  if (!left || !right) return false;
  if (left === right) return true;
  // Absolute tool path vs project-relative summary of the same file.
  return left.endsWith(`/${right}`) || right.endsWith(`/${left}`);
}

/**
 * Panels render the turn's file list. When the session detail carries the
 * ledger's `changedFiles` summary it is the disk-truth authority: it defines
 * the row set, states and +/- counts, while tool-transcript extras (view
 * content, patches, continue editing) are matched back per path and
 * transcript-only rows are kept appended. Without the summary this is exactly
 * `collectConversationFileDeliveries`.
 */
export function mergeConversationFileDeliveries(
  cells: readonly CodexTranscriptCell[],
  changedFiles?: readonly ConversationChangedFileSummary[] | null,
): { files: ConversationFileDeliveryView[]; patches: Array<{ id: string; text: string }> } {
  const extracted = collectConversationFileDeliveries(cells);
  const summaries = (changedFiles ?? []).filter(
    (entry) => entry && typeof entry.path === "string" && entry.path.trim(),
  );
  if (!summaries.length) return extracted;
  const matched = new Set<ConversationFileDelivery>();
  const files: ConversationFileDeliveryView[] = [];
  for (const summary of summaries) {
    const match = extracted.files.find(
      (entry) => !matched.has(entry) && sameDeliveryPath(entry.path, summary.path),
    );
    if (match) matched.add(match);
    const state = typeof summary.state === "string" && summary.state ? summary.state : undefined;
    // Disk truth wins for state; a deleted file has nothing to preview.
    const deleted = state ? state === "deleted" : Boolean(match?.deleted);
    files.push({
      path: match?.path ?? summary.path,
      content: deleted ? undefined : match?.content,
      deleted,
      additions: typeof summary.additions === "number" ? summary.additions : undefined,
      deletions: typeof summary.deletions === "number" ? summary.deletions : undefined,
      state,
    });
  }
  for (const entry of extracted.files) {
    if (!matched.has(entry)) files.push(entry);
  }
  return { files, patches: extracted.patches };
}
