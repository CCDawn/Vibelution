import { EditorView } from "@codemirror/view";

export const workbenchCodeMirrorTheme = EditorView.theme({
  "&": {
    backgroundColor: "var(--vui-surface-workspace)",
    color: "var(--fg-primary)",
  },
  ".cm-content": {
    caretColor: "var(--accent-warm-2)",
  },
  ".cm-cursor, .cm-dropCursor": {
    borderLeftColor: "var(--accent-warm-2)",
  },
  "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection": {
    backgroundColor: "color-mix(in srgb, var(--accent-warm) 28%, transparent)",
  },
  ".cm-gutters": {
    backgroundColor: "var(--vui-surface-panel)",
    borderRightColor: "var(--border-soft)",
    color: "var(--fg-tertiary)",
  },
  ".cm-activeLine, .cm-activeLineGutter": {
    backgroundColor: "var(--vui-surface-row-hover)",
  },
  ".cm-foldPlaceholder": {
    backgroundColor: "var(--vui-surface-row)",
    borderColor: "var(--border-soft)",
    color: "var(--fg-secondary)",
  },
  ".cm-tooltip": {
    backgroundColor: "color-mix(in srgb, var(--vui-surface-panel) 92%, var(--vui-surface-row-hover))",
    borderColor: "var(--border-strong)",
    color: "var(--fg-primary)",
  },
});
