/**
 * Render budget ladder for conversation markdown surfaces (pattern:
 * zai-org/ZCode "keep semantics, cut computation" staged degradation,
 * Apache-2.0). Completed markdown keeps full semantics behind a native
 * `<details>` disclosure; the streaming live tail is capped hard because it
 * re-renders every frame (an unclosed fence holds its whole block in the live
 * tail, so it must be bounded per frame, not just at settle).
 *
 * Pure and React-free: callers decide how to project the slices into DOM.
 */

/** Completed code block: lines rendered before the rest folds behind `<details>`. */
export const CODE_BLOCK_MAX_VISIBLE_LINES = 200;
/** Completed table: data rows rendered before the rest folds behind `<details>`. */
export const TABLE_MAX_VISIBLE_ROWS = 30;
/** Streaming live code block: only the newest lines render per frame. */
export const LIVE_CODE_MAX_VISIBLE_LINES = 60;
/** Streaming live table: only the first rows render while rows flow in. */
export const LIVE_TABLE_MAX_VISIBLE_ROWS = 20;

export type LineBudgetSlice = {
  /** Text kept in the primary render (head or tail, depending on the helper). */
  visible: string;
  /** Text dropped from the primary render, preserved for the caller's disclosure. */
  overflow: string;
  /** Number of lines moved into `overflow`. */
  overflowCount: number;
};

export type RowBudgetSlice<T> = {
  visible: T[];
  overflowCount: number;
};

/** Literal line count: splits on `\n`, so an empty string counts as one line. */
export function countRenderableLines(text: string): number {
  return String(text ?? "").split("\n").length;
}

export function exceedsLineBudget(text: string, maxLines: number): boolean {
  return countRenderableLines(text) > normalizeBudget(maxLines);
}

export function exceedsRowBudget(rows: readonly unknown[], maxRows: number): boolean {
  return rows.length > normalizeBudget(maxRows);
}

/** Keeps the FIRST `maxLines` lines; the rest become the overflow slice. */
export function headLines(text: string, maxLines: number): LineBudgetSlice {
  const lines = String(text ?? "").split("\n");
  const budget = normalizeBudget(maxLines);
  if (lines.length <= budget) {
    return { visible: lines.join("\n"), overflow: "", overflowCount: 0 };
  }
  return {
    visible: lines.slice(0, budget).join("\n"),
    overflow: lines.slice(budget).join("\n"),
    overflowCount: lines.length - budget,
  };
}

/** Keeps the LAST `maxLines` lines (streaming: newest content stays visible). */
export function tailLines(text: string, maxLines: number): LineBudgetSlice {
  const lines = String(text ?? "").split("\n");
  const budget = normalizeBudget(maxLines);
  if (lines.length <= budget) {
    return { visible: lines.join("\n"), overflow: "", overflowCount: 0 };
  }
  return {
    visible: lines.slice(lines.length - budget).join("\n"),
    overflow: lines.slice(0, lines.length - budget).join("\n"),
    overflowCount: lines.length - budget,
  };
}

/** Keeps the FIRST `maxRows` rows; overflow is only counted, never dropped silently. */
export function headRows<T>(rows: readonly T[], maxRows: number): RowBudgetSlice<T> {
  const budget = normalizeBudget(maxRows);
  if (rows.length <= budget) {
    return { visible: [...rows], overflowCount: 0 };
  }
  return { visible: rows.slice(0, budget), overflowCount: rows.length - budget };
}

function normalizeBudget(max: number): number {
  const value = Math.floor(Number(max));
  return Number.isFinite(value) && value >= 1 ? value : 1;
}
