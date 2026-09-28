import { conversationMarkdownCodeBlockStyles } from "./ConversationMarkdownRenderer.styles";

/**
 * ```mermaid block chrome reuses the completed code-block header pieces so the
 * fence reads as the same card family (language label + right-side control).
 * Only the mermaid-specific surfaces live here: status rows, the scrollable
 * SVG canvas, and the budget/failed hints.
 */
export default {
  shell: "vui-components-conversationview markdownMermaidBlock min-w-0 max-w-full",
  status:
    "vui-components-conversationview markdownMermaidStatus flex min-w-0 items-center gap-x-1.5 border border-b-0 border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] px-2.5 py-1 text-vui-2xs text-[var(--fg-tertiary)]",
  statusSpinner: "vui-components-conversationview markdownMermaidStatusSpinner inline-block animate-spin",
  // Rendered diagram viewport: bounded height, scrollable, SVG scales to fit width.
  canvas:
    "vui-components-conversationview markdownMermaidCanvas max-h-[420px] min-w-0 overflow-auto rounded-b-[var(--radius-control)] border border-t-0 border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-3 [&_svg]:mx-auto [&_svg]:h-auto [&_svg]:max-w-full",
  hint: "vui-components-conversationview markdownMermaidHint min-w-0",
  // The plaintext body reuses the host pre chrome minus its top rounding/border
  // so header/status/body read as one card (same trick as preAttached).
  preAttached: "vui-components-conversationview markdownMermaidPre mt-0 rounded-t-none border-t-0",
  codeBlock: conversationMarkdownCodeBlockStyles,
} as const;
