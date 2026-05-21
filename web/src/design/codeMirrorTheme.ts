import { EditorView } from "@codemirror/view";

export const workbenchCodeMirrorTheme = EditorView.theme({
  "&": {
    backgroundColor: "var(--surface-code)",
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
    backgroundColor: "var(--surface-panel)",
    borderRightColor: "var(--border-soft)",
    color: "var(--fg-tertiary)",
  },
  ".cm-activeLine, .cm-activeLineGutter": {
    backgroundColor: "var(--surface-card-muted)",
  },
  ".cm-foldPlaceholder": {
    backgroundColor: "var(--surface-card)",
    borderColor: "var(--border-soft)",
    color: "var(--fg-secondary)",
  },
  ".cm-tooltip": {
    backgroundColor: "var(--surface-panel-strong)",
    borderColor: "var(--border-strong)",
    color: "var(--fg-primary)",
  },
});
