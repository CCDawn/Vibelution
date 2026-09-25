import type { CSSProperties } from "react";

import type { PaneHeightMap, PaneHeightSpec } from "./paneHeightPersistence";
import type { PaneSpec, PaneWidthMap } from "./paneLayoutPersistence";

/**
 * CSS variable channel for pane resize (Wave 5B, borrowed from zai-org/ZCode
 * WorkbenchSplitDivider drag discipline, Apache-2.0): during a pointer drag the
 * hook writes `--pane-w-*` / `--pane-h-*` straight onto the registered split
 * container element, so the React subtree never re-renders mid-drag. State
 * catches up once on pointerup, and the render-time variable style below keeps
 * the same variables correct before the first drag and after every commit.
 */

/** Characters that are unsafe inside a CSS custom property identifier. */
const UNSAFE_CSS_IDENT = /[^a-zA-Z0-9_-]/g;

function sanitizePaneCssIdent(paneId: string): string {
  const safe = paneId.replace(UNSAFE_CSS_IDENT, "-");
  return safe.length > 0 ? safe : "pane";
}

/** CSS variable carrying a pane width on the registered split container. */
export function paneWidthCssVar(paneId: string): string {
  return `--pane-w-${sanitizePaneCssIdent(paneId)}`;
}

/** CSS variable carrying a pane height on the registered split container. */
export function paneHeightCssVar(paneId: string): string {
  return `--pane-h-${sanitizePaneCssIdent(paneId)}`;
}

/** Render-time width variables for every pane; spread onto the container. */
export function paneWidthVariablesStyle(
  panes: readonly PaneSpec[],
  widths: PaneWidthMap,
): CSSProperties {
  const style: Record<string, string> = {};
  for (const pane of panes) {
    style[paneWidthCssVar(pane.id)] = `${widths[pane.id] ?? pane.defaultWidth}px`;
  }
  return style as CSSProperties;
}

/** Render-time height variables for every pane; spread onto the container. */
export function paneHeightVariablesStyle(
  panes: readonly PaneHeightSpec[],
  heights: PaneHeightMap,
): CSSProperties {
  const style: Record<string, string> = {};
  for (const pane of panes) {
    style[paneHeightCssVar(pane.id)] = `${heights[pane.id] ?? pane.defaultHeight}px`;
  }
  return style as CSSProperties;
}
