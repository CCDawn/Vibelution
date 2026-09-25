import type { CodexTranscriptCell } from "./codexTranscriptCells";
import {
  codexTranscriptToolRawName,
} from "./conversationToolActivityModel";
import {
  conversationToolActivityHasNonzeroTerminalExit,
  conversationToolActivityIsNoMatchTerminalExit,
  type ConversationToolActivityPresentationItem,
} from "./conversationToolActivityPresentation";
import {
  conversationToolCategoryForCell,
  conversationToolCategoryLabel,
  type ConversationToolCategory,
} from "./conversationToolCategory";
import type { ConversationToolPresentationLanguage } from "./conversationToolPresentation";

/**
 * Category-level grouping pass, aligned with ZCode's assistant work items:
 * - a run escalates to a parent group only once TWO OR MORE consecutive items
 *   share a category; a lone first item keeps its plain row immediately
 *   (conversationAssistantWorkItems.ts "first item renders as the raw tool").
 * - the group identity anchors to the FIRST child's stable tool identity, so
 *   streaming appends update children in place instead of remounting the
 *   parent and losing the user's expand state (ZCode buildExploreGroup note).
 * - uncategoryable and agent rows are barriers: they end the current run and
 *   never join a group.
 *
 * The pass runs ON TOP of the existing same-name batching: a same-name run
 * stays one inner batch item, and the category layer merges distinct runs of
 * one category (e.g. read + grep + glob under one "探索" parent). One item
 * alone — even a multi-call batch — never gains a parent wrapper.
 */

/** Category group switches, mirroring ZCode's four toggles. */
export const ENABLE_EXPLORE_CATEGORY_GROUPING = true;
export const ENABLE_EXECUTE_CATEGORY_GROUPING = true;
export const ENABLE_CHANGES_CATEGORY_GROUPING = false;
export const ENABLE_CUA_CATEGORY_GROUPING = true;

export type ConversationToolCategoryGroupItem = {
  kind: "categoryGroup";
  /** Anchored to the first child's stable persist key — no tail/count suffix. */
  id: string;
  category: ConversationToolCategory;
  title: string;
  /** Total tool calls under the group (batch children count all their cells). */
  count: number;
  items: readonly ConversationToolActivityPresentationItem[];
  running: boolean;
  attentionCount: number;
  failedCount: number;
  /** First attention-worthy child cell, for the parent row's failure tooltip. */
  firstAttentionCell: CodexTranscriptCell | null;
};

export type ConversationToolCategorizedItem =
  | ConversationToolActivityPresentationItem
  | ConversationToolCategoryGroupItem;

export interface ConversationToolCategoryGroupOptions {
  enableExploreGrouping?: boolean;
  enableExecuteGrouping?: boolean;
  enableChangesGrouping?: boolean;
  enableCuaGrouping?: boolean;
}

/**
 * The B2 row-open persistence identity: the tool call id, falling back to the
 * cell id. Group ids reuse this exact key (prefixed) so the parent anchor and
 * its first child stay 1:1 comparable without colliding in the shared map.
 */
export function conversationToolPersistKey(cell: CodexTranscriptCell): string {
  return cell.toolLifecycleModel?.toolCalls?.[0]?.toolCallId || cell.id;
}

function categoryGroupingEnabled(
  category: ConversationToolCategory,
  options: ConversationToolCategoryGroupOptions,
): boolean {
  if (category === "explore") {
    return options.enableExploreGrouping ?? ENABLE_EXPLORE_CATEGORY_GROUPING;
  }
  if (category === "execute") {
    return options.enableExecuteGrouping ?? ENABLE_EXECUTE_CATEGORY_GROUPING;
  }
  if (category === "changes") {
    return options.enableChangesGrouping ?? ENABLE_CHANGES_CATEGORY_GROUPING;
  }
  if (category === "cua") {
    return options.enableCuaGrouping ?? ENABLE_CUA_CATEGORY_GROUPING;
  }
  return false;
}

/** Items with no groupable category (incl. agent rows) pass through untouched. */
function groupableCategoryOfItem(
  item: ConversationToolActivityPresentationItem,
  options: ConversationToolCategoryGroupOptions,
): ConversationToolCategory | null {
  const cell = item.kind === "batch" ? item.cells[0] : item.cell;
  if (!cell) {
    return null;
  }
  const category = conversationToolCategoryForCell(cell);
  if (!category || !categoryGroupingEnabled(category, options)) {
    return null;
  }
  return category;
}

function cellNeedsAttention(cell: CodexTranscriptCell): boolean {
  if (conversationToolActivityIsNoMatchTerminalExit(cell)) {
    return false;
  }
  return cell.status === "failed"
    || cell.status === "degraded"
    || cell.tone === "warning"
    || cell.tone === "error"
    || conversationToolActivityHasNonzeroTerminalExit(cell);
}

function cellIsSettledFailure(cell: CodexTranscriptCell): boolean {
  return cellNeedsAttention(cell)
    && (cell.status === "failed" || cell.status === "degraded" || cell.tone === "error");
}

function cellsOfItem(item: ConversationToolActivityPresentationItem): readonly CodexTranscriptCell[] {
  return item.kind === "batch" ? item.cells : [item.cell];
}

function firstCellOfItem(item: ConversationToolActivityPresentationItem): CodexTranscriptCell | null {
  return item.kind === "batch" ? item.cells[0] ?? null : item.cell;
}

function buildCategoryGroup(
  category: ConversationToolCategory,
  run: readonly ConversationToolActivityPresentationItem[],
  language: ConversationToolPresentationLanguage,
): ConversationToolCategoryGroupItem {
  const firstCell = run
    .map(firstCellOfItem)
    .find((cell): cell is CodexTranscriptCell => cell !== null);
  if (!firstCell) {
    throw new Error("A category group requires at least one child cell.");
  }
  let count = 0;
  let attentionCount = 0;
  let failedCount = 0;
  let running = false;
  let firstAttentionCell: CodexTranscriptCell | null = null;
  for (const item of run) {
    for (const cell of cellsOfItem(item)) {
      count += 1;
      if (cell.status === "running" || cell.status === "pending") {
        running = true;
      }
      if (cellNeedsAttention(cell)) {
        attentionCount += 1;
        if (!firstAttentionCell) {
          firstAttentionCell = cell;
        }
        if (cellIsSettledFailure(cell)) {
          failedCount += 1;
        }
      }
    }
  }
  return {
    kind: "categoryGroup",
    id: `tool-category-group:${conversationToolPersistKey(firstCell)}`,
    category,
    title: conversationToolCategoryLabel(category, language),
    count,
    items: run,
    running,
    attentionCount,
    failedCount,
    firstAttentionCell,
  };
}

/**
 * Folds consecutive same-category presentation items into at most one parent
 * group per run. Runs of one item, categories without grouping, and barrier
 * rows (uncategoryable / agent) are returned as-is.
 */
export function buildConversationToolCategoryGroups(
  items: readonly ConversationToolActivityPresentationItem[],
  language: ConversationToolPresentationLanguage,
  options: ConversationToolCategoryGroupOptions = {},
): ConversationToolCategorizedItem[] {
  const result: ConversationToolCategorizedItem[] = [];
  let run: ConversationToolActivityPresentationItem[] = [];
  let runCategory: ConversationToolCategory | null = null;

  const flush = () => {
    if (run.length === 1) {
      result.push(run[0]);
    } else if (run.length >= 2 && runCategory) {
      result.push(buildCategoryGroup(runCategory, run, language));
    }
    run = [];
    runCategory = null;
  };

  for (const item of items) {
    const category = groupableCategoryOfItem(item, options);
    if (!category) {
      flush();
      result.push(item);
      continue;
    }
    if (runCategory && runCategory !== category) {
      flush();
    }
    runCategory = category;
    run.push(item);
  }
  flush();
  return result;
}

/** Raw tool word for diagnostics/tests: category name of a cell, if any. */
export function conversationToolCategoryNameForCell(cell: CodexTranscriptCell): string {
  return codexTranscriptToolRawName(cell);
}
