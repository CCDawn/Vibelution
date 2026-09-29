import { Component, type ReactNode } from "react";

import { markdownErrorNoteLang } from "./LazyConversationMarkdownRenderer.errorBoundary";
// Shared degradation chrome (re-export of the message-level fallback tokens —
// see conversationMarkdownBlockBoundary.styles.ts).
import boundaryStyles from "./conversationMarkdownBlockBoundary.styles";

type ConversationMarkdownBlockBoundaryProps = {
  /**
   * Extracted plain text of the wrapped block (see `markdownBlockSourceText`).
   * Doubles as the reset key: value comparison means only a real content
   * change (streaming growth) retries the real renderer, while a stable
   * re-render keeps the degraded state without re-throwing every frame.
   */
  source: string;
  /** Host `responseSegmentPre` chrome so the degraded block matches siblings. */
  preClassName?: string;
  children: ReactNode;
};

type ConversationMarkdownBlockBoundaryState = {
  failed: boolean;
};

/**
 * Block-scope guard inside one markdown message (ZCode-aligned granularity):
 * a crash while rendering ONE block degrades that block to its raw text and
 * leaves every sibling block untouched. The whole-message boundary in
 * `LazyConversationMarkdownRenderer.errorBoundary` stays mounted above this as
 * the last line of defense for failures a block boundary structurally cannot
 * see — chiefly remark/rehype transform-time throws (e.g. an escaping KaTeX
 * error), which happen inside ReactMarkdown's render before any block
 * component exists. Display-math containers are unreachable here by design:
 * rehype-katex splices the `div.math-display` / ```math `pre` out of the hast
 * tree before the `components` mapping runs, so there is no math container
 * left to wrap; KaTeX degrades its own ParseErrors to a source-text span.
 *
 * Coverage: `pre` (fenced code + mermaid detection) and `table` — the two
 * blocks whose render paths run non-trivial code (formatting, truncation,
 * mermaid machine, host callbacks). Remaining block overrides (p, headings,
 * lists, blockquote) are single DOM-element pass-throughs that cannot throw.
 *
 * The fallback is idempotent-safe: it renders `{source}` as a plain text child
 * of a `<pre>` — no markdown pipeline, no recursion into the boundary itself.
 */
export class ConversationMarkdownBlockBoundary extends Component<
  ConversationMarkdownBlockBoundaryProps,
  ConversationMarkdownBlockBoundaryState
> {
  state: ConversationMarkdownBlockBoundaryState = { failed: false };

  static getDerivedStateFromError(): ConversationMarkdownBlockBoundaryState {
    return { failed: true };
  }

  componentDidCatch(error: unknown): void {
    // Same quiet-degrade posture as the message-level boundary: keep the raw
    // text readable, log only the message for diagnosis.
    console.warn(
      "[conversation-markdown-block-render-error]",
      error instanceof Error ? error.message : String(error),
    );
  }

  componentDidUpdate(previousProps: ConversationMarkdownBlockBoundaryProps): void {
    // Content under this block changed (streaming append / edit): retry the
    // real renderer once. String comparison is by value, so an unchanged
    // block never churns through throw → degrade → retry on parent updates.
    if (this.state.failed && previousProps.source !== this.props.source) {
      this.setState({ failed: false });
    }
  }

  render() {
    if (!this.state.failed) {
      return this.props.children;
    }
    const text = String(this.props.source ?? "");
    const lang = markdownErrorNoteLang();
    const note = lang === "zh"
      ? "Markdown 块渲染出错，已显示原文。"
      : "Markdown block rendering failed; showing the raw text.";
    return (
      <div className={boundaryStyles.errorBox} data-markdown-block-error-fallback="true">
        <pre
          className={[boundaryStyles.fallbackPre, this.props.preClassName].filter(Boolean).join(" ")}
        >
          {text}
        </pre>
        <p className={boundaryStyles.errorNote}>{note}</p>
      </div>
    );
  }
}

/** Structural view of the hast nodes react-markdown hands to `components`. */
type HastNodeLike = {
  type?: unknown;
  value?: unknown;
  tagName?: unknown;
  children?: unknown;
  position?: {
    start?: {
      line?: unknown;
      column?: unknown;
    };
  };
};

/**
 * Element tags whose rendered text reads as one visual line: a newline is
 * inserted between such children so degraded tables/list items stay readable.
 * Everything else joins directly, which preserves code-block whitespace
 * (`pre > code` chains stay byte-faithful).
 */
const FLOW_LINE_TAGS = new Set([
  "blockquote",
  "details",
  "div",
  "dl",
  "dt",
  "dd",
  "figure",
  "figcaption",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "hr",
  "li",
  "ol",
  "p",
  "pre",
  "section",
  "summary",
  "table",
  "tbody",
  "tfoot",
  "thead",
  "tr",
  "ul",
]);

function childJoinSeparator(node: unknown): string {
  if (typeof node !== "object" || node === null) {
    return "";
  }
  const tagName = (node as HastNodeLike).tagName;
  if (tagName === "td" || tagName === "th") {
    // Table cells: two spaces keeps columns scannable without table markup.
    return "  ";
  }
  return typeof tagName === "string" && FLOW_LINE_TAGS.has(tagName) ? "\n" : "";
}

function hastTextValue(node: unknown): string {
  if (typeof node !== "object" || node === null) {
    return "";
  }
  const { type, value, children } = node as HastNodeLike;
  if (type === "text") {
    return typeof value === "string" ? value : "";
  }
  if (!Array.isArray(children)) {
    return "";
  }
  let out = "";
  for (const child of children) {
    const part = hastTextValue(child);
    if (!part) {
      continue;
    }
    if (out) {
      out += childJoinSeparator(child);
    }
    out += part;
  }
  return out;
}

/**
 * Raw-ish source text of one markdown block, extracted from the hast `node`
 * react-markdown passes to `components` (passNode: true).
 *
 * Trade-off vs. alternatives: the hast text is the exact payload the pipeline
 * consumed (post normalize/math-guard), not the user's original bytes — a
 * degraded block therefore shows what the renderer actually choked on, which
 * beats a raw slice that may no longer correspond to the parsed shape. It is
 * text content, not markdown syntax (fence markers are gone); for a code
 * fence the payload is the essential part and reads perfectly inside a `<pre>`.
 * `markdownBlockSourceText` is throw-safe: extraction is a pure data walk, and
 * a malformed tree degrades to "" rather than breaking the fallback path.
 */
export function markdownBlockSourceText(node: unknown): string {
  try {
    return hastTextValue(node);
  } catch {
    return "";
  }
}

/**
 * Stable per-block identity for React reconciliation, derived from the source
 * position of the hast node. Blocks keep their boundary instance across
 * re-renders and lose it (→ fresh retry state) when the surrounding content
 * shifts their position. Returns undefined when the parser omitted position
 * data; positional reconciliation of the single-child override still holds.
 */
export function markdownBlockBoundaryKey(node: unknown): string | undefined {
  try {
    const start = (node as HastNodeLike | null)?.position?.start;
    if (typeof start?.line === "number" && typeof start?.column === "number") {
      return `md-block-${start.line}:${start.column}`;
    }
  } catch {
    // Position is metadata only — never let it break the render path.
  }
  return undefined;
}
