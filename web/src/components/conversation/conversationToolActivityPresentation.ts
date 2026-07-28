import type { CodexTranscriptCell } from "./codexTranscriptCells";
import { codexTranscriptToolRawName } from "./conversationToolActivityModel";
import type { ConversationToolPresentationLanguage } from "./conversationToolPresentation";
import {
  conversationToolRendererFor,
  conversationToolRendererLabel,
} from "./conversationToolRendererRegistry";

const BATCH_MINIMUM = 2;

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
