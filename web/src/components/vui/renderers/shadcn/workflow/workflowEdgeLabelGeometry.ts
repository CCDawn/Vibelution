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

const CJK_ADVANCE = 11;
const ASCII_ADVANCE = 6.5;

/** Protocol / English definition labels that must stay short on the canvas. */
const CANVAS_EDGE_LABEL_ALIASES: Record<string, string> = {
  "Knowledge Package": "知识包",
  "knowledge package": "知识包",
  "Smoke 放行": "试跑放行",
};

export type EdgeLabelSpec = {
  text: string;
  /** Rendered text after truncation (ellipsis appended when truncated). */
  displayText: string;
  /** Final label box (the ONLY rect the layout and renderer agree on). */
  width: number;
  height: number;
};

export function canvasEdgeDisplayLabel(raw: string): string {
  const trimmed = String(raw ?? "").trim();
  return CANVAS_EDGE_LABEL_ALIASES[trimmed] ?? CANVAS_EDGE_LABEL_ALIASES[trimmed.toLowerCase()] ?? trimmed;
}

function glyphAdvance(char: string): number {
  return /[\u3400-\u9fff]/.test(char) ? CJK_ADVANCE : ASCII_ADVANCE;
}

function measureText(text: string): number {
  let width = 0;
  for (const char of text) {
    width += glyphAdvance(char);
  }
  return width;
}

function truncateToWidth(text: string, maxInner: number): string {
  if (measureText(text) <= maxInner) return text;
  const ellipsis = "…";
  const budget = maxInner - measureText(ellipsis);
  let used = 0;
  let cut = "";
  for (const char of text) {
    const next = used + glyphAdvance(char);
    if (next > budget) break;
    used = next;
    cut += char;
  }
  return `${cut || text.slice(0, 1)}${ellipsis}`;
}

/**
 * Computes the label geometry for a given text. Width is capped at
 * EDGE_LABEL_MAX_WIDTH; longer text is truncated with an ellipsis but the box
 * stays at the declared width (truncation never changes layout).
 */
export function resolveEdgeLabelSpec(text: string): EdgeLabelSpec {
  const source = String(text ?? "").trim();
  const display = canvasEdgeDisplayLabel(source);
  const innerMax = EDGE_LABEL_MAX_WIDTH - EDGE_LABEL_PADDING_X * 2;
  const natural = measureText(display);
  const truncated = natural > innerMax;
  const displayText = truncated ? truncateToWidth(display, innerMax) : display;
  const width = Math.min(EDGE_LABEL_MAX_WIDTH, Math.max(24, measureText(displayText) + EDGE_LABEL_PADDING_X * 2));
  return { text: source, displayText, width, height: EDGE_LABEL_HEIGHT };
}
