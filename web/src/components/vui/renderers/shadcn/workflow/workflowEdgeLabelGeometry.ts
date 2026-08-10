/**
 * Edge label geometry contract — the SINGLE source of truth for label sizing.
 *
 * Both the layout input (spacer node size fed to the outer ELK graph) and the
 * React renderer (WorkflowSemanticEdge label box) consume this module, so the
 * ELK-claimed label rect always matches what is drawn. Truncation keeps the
 * drawn box within the declared size.
 */

export const EDGE_LABEL_FONT_SIZE = 11;
export const EDGE_LABEL_PADDING_X = 6;
export const EDGE_LABEL_MAX_WIDTH = 152;
/** Compact single-line control height; shared by ELK reservation and the DOM. */
export const EDGE_LABEL_HEIGHT = 20;

/** Approximate glyph advance for CJK/ASCII mixed text at 11px. */
const CHAR_ADVANCE = 11;

export type EdgeLabelSpec = {
  text: string;
  /** Rendered text after truncation (ellipsis appended when truncated). */
  displayText: string;
  /** Final label box (the ONLY rect the layout and renderer agree on). */
  width: number;
  height: number;
};

/**
 * Computes the label geometry for a given text. Width is capped at
 * EDGE_LABEL_MAX_WIDTH; longer text is truncated with an ellipsis but the box
 * stays at the declared width (truncation never changes layout).
 */
export function resolveEdgeLabelSpec(text: string): EdgeLabelSpec {
  const trimmed = String(text ?? "").trim();
  const natural = trimmed.length * CHAR_ADVANCE + EDGE_LABEL_PADDING_X * 2;
  const width = Math.min(EDGE_LABEL_MAX_WIDTH, Math.max(24, natural));
  const truncated = trimmed.length * CHAR_ADVANCE > EDGE_LABEL_MAX_WIDTH - EDGE_LABEL_PADDING_X * 2 - 8;
  const displayText = truncated ? `${trimmed.slice(0, Math.max(1, Math.floor((EDGE_LABEL_MAX_WIDTH - EDGE_LABEL_PADDING_X * 2 - 8) / CHAR_ADVANCE)))}…` : trimmed;
  return { text: trimmed, displayText, width, height: EDGE_LABEL_HEIGHT };
}
