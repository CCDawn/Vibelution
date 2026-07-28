import type { CodexTranscriptCell } from "./codexTranscriptCells";
import { codexTranscriptToolRawName } from "./conversationToolActivityModel";
import type { ConversationToolPresentationLanguage } from "./conversationToolPresentation";
import {
  conversationToolRendererFor,
  conversationToolRendererForPresentationLabel,
  conversationToolRendererLabel,
} from "./conversationToolRendererRegistry";

const BATCH_MINIMUM = 2;
const DIGEST_META_GROUP_LIMIT = 3;

export type ConversationToolActivityPresentationItem =
  | {
    kind: "single";
    id: string;
    cell: CodexTranscriptCell;
  }
  | {
    kind: "batch";
    id: string;
    title: string;
    count: number;
    cells: readonly CodexTranscriptCell[];
  };

export type ConversationToolActivityDigestPresentation = {
  state: "completed" | "running" | "attention";
  count: number;
  attentionCount: number;
  title: string;
  attentionLabel: string;
  meta: string;
};

export function conversationToolActivityTerminalExitCode(cell: CodexTranscriptCell) {
  for (const operation of cell.toolLifecycleModel?.terminalOperations ?? []) {
    const exitCode = operation.result?.exitCode;
    if (typeof exitCode === "number") {
      return exitCode;
    }
  }
  return null;
}

export function conversationToolActivityHasNonzeroTerminalExit(cell: CodexTranscriptCell) {
  const exitCode = conversationToolActivityTerminalExitCode(cell);
  return exitCode !== null && exitCode !== 0;
}

export function conversationToolActivityIsNoMatchTerminalExit(cell: CodexTranscriptCell) {
  if (conversationToolActivityTerminalExitCode(cell) !== 1) {
    return false;
  }
  const terminalText = (cell.toolLifecycleModel?.terminalOperations ?? [])
    .flatMap((operation) => [
      operation.request?.displayCommand,
      operation.result?.formattedOutput,
      operation.result?.stdout,
      operation.result?.stderr,
    ])
    .filter(Boolean)
    .join("\n");
  return /\b(?:findstr|grep|rg)\b/i.test(terminalText)
    && /(?:无输出|no output|no matches?|not found)/i.test(terminalText);
}

export function conversationToolActivityRendererForCell(
  cell: CodexTranscriptCell,
  language: ConversationToolPresentationLanguage,
) {
  const rawName = codexTranscriptToolRawName(cell);
  const direct = conversationToolRendererFor(rawName);
  if (direct.family !== "generic") {
    return direct;
  }
  return conversationToolRendererForPresentationLabel(
    conversationToolRendererLabel(rawName || cell.title || "", language),
    language,
  );
}

function toolInvocationCount(cell: CodexTranscriptCell) {
  if (cell.failureCount && cell.failureCount > 0) {
    return cell.failureCount;
  }
  return Math.max(1, cell.toolLifecycleModel?.toolCalls?.length ?? 0);
}

function needsAttention(cell: CodexTranscriptCell) {
  if (conversationToolActivityIsNoMatchTerminalExit(cell)) {
    return false;
  }
  return cell.status === "failed"
    || cell.status === "degraded"
    || cell.tone === "warning"
    || cell.tone === "error"
    || conversationToolActivityHasNonzeroTerminalExit(cell);
}

function digestTitle(
  count: number,
  state: ConversationToolActivityDigestPresentation["state"],
  language: ConversationToolPresentationLanguage,
) {
  if (state === "running") {
    if (language === "zh") {
      return count > 1 ? `正在运行 ${count} 个工具` : "正在运行工具";
    }
    return count > 1 ? `Running ${count} tools` : "Running tool";
  }
  if (language === "zh") {
    return `运行了 ${count} 个工具`;
  }
  return `Ran ${count} ${count === 1 ? "tool" : "tools"}`;
}

function attentionLabel(count: number, language: ConversationToolPresentationLanguage) {
  if (count === 0) {
    return "";
  }
  if (language === "zh") {
    return `${count} 项需关注`;
  }
  return count === 1 ? "1 item needs attention" : `${count} items need attention`;
}

export function buildConversationToolActivityDigestPresentation(
  cells: readonly CodexTranscriptCell[],
  language: ConversationToolPresentationLanguage,
): ConversationToolActivityDigestPresentation {
  const count = cells.reduce((total, cell) => total + toolInvocationCount(cell), 0);
  const attentionCount = cells.filter(needsAttention).length;
  const state = cells.some((cell) => cell.status === "running" || cell.status === "pending")
    ? "running"
    : attentionCount > 0
      ? "attention"
      : "completed";
  const groups = new Map<string, number>();
  for (const cell of cells) {
    const descriptor = conversationToolActivityRendererForCell(cell, language);
    const label = descriptor.groupLabel[language];
    groups.set(label, (groups.get(label) ?? 0) + toolInvocationCount(cell));
  }
  const groupEntries = [...groups.entries()];
  const hiddenGroupCount = Math.max(0, groupEntries.length - DIGEST_META_GROUP_LIMIT);
  const boundedMeta = groupEntries
    .slice(0, DIGEST_META_GROUP_LIMIT)
    .map(([label, groupCount]) => `${label} ${groupCount}`);
  if (hiddenGroupCount > 0) {
    boundedMeta.push(language === "zh" ? `另 ${hiddenGroupCount} 类` : `${hiddenGroupCount} more types`);
  }
  return {
    state,
    count,
    attentionCount,
    title: digestTitle(count, state, language),
    attentionLabel: attentionLabel(attentionCount, language),
    meta: boundedMeta.join(" · "),
  };
}

function completedToolIdentity(cell: CodexTranscriptCell) {
  if (cell.kind !== "tool_call" || cell.status !== "completed" || cell.tone !== "neutral") {
    return "";
  }
  if (
    cell.toolLifecycleModel?.terminalOperations.some(
      (operation) => typeof operation.result?.exitCode === "number" && operation.result.exitCode !== 0,
    )
  ) {
    return "";
  }
  const rawName = codexTranscriptToolRawName(cell).trim().toLowerCase();
  const family = conversationToolRendererFor(rawName).family;
  return family === "generic" ? `generic:${rawName}` : family;
}

function presentationRunTitle(
  cell: CodexTranscriptCell,
  language: ConversationToolPresentationLanguage,
) {
  const rawName = codexTranscriptToolRawName(cell);
  const descriptor = conversationToolRendererFor(rawName);
  return descriptor.family === "generic"
    ? conversationToolRendererLabel(rawName, language)
    : descriptor.groupLabel[language];
}

function appendPresentationRun(
  items: ConversationToolActivityPresentationItem[],
  cells: readonly CodexTranscriptCell[],
  language: ConversationToolPresentationLanguage,
) {
  if (cells.length < BATCH_MINIMUM) {
    items.push(...cells.map((cell) => ({ kind: "single" as const, id: cell.id, cell })));
    return;
  }
  const first = cells[0];
  const last = cells.at(-1);
  if (!first || !last) {
    return;
  }
  items.push({
    kind: "batch",
    id: `tool-batch:${first.id}:${last.id}`,
    title: presentationRunTitle(first, language),
    count: cells.length,
    cells,
  });
}

/**
 * Builds a display-only projection for one contiguous tool activity. A batch
 * never moves events across commentary boundaries: it represents only an
 * adjacent run of successful calls in the same semantic work stage.
 */
export function buildConversationToolActivityPresentation(
  cells: readonly CodexTranscriptCell[],
  language: ConversationToolPresentationLanguage,
): ConversationToolActivityPresentationItem[] {
  const items: ConversationToolActivityPresentationItem[] = [];
  let currentRun: CodexTranscriptCell[] = [];
  let currentIdentity = "";

  const flush = () => {
    if (currentRun.length > 0) {
      appendPresentationRun(items, currentRun, language);
    }
    currentRun = [];
    currentIdentity = "";
  };

  for (const cell of cells) {
    const identity = completedToolIdentity(cell);
    if (!identity) {
      flush();
      items.push({ kind: "single", id: cell.id, cell });
      continue;
    }
    if (currentIdentity && currentIdentity !== identity) {
      flush();
    }
    currentIdentity = identity;
    currentRun.push(cell);
  }
  flush();
  return items;
}
