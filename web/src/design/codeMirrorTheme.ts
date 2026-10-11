import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { tags } from "@lezer/highlight";
import { EditorView } from "@codemirror/view";

export const workbenchCodeMirrorSyntaxHighlightStyle = HighlightStyle.define([
  { tag: [tags.meta, tags.comment], color: "var(--fg-secondary)" },
  { tag: [tags.keyword, tags.operatorKeyword], color: "var(--accent-cool-2)" },
  {
    tag: [tags.name, tags.character, tags.propertyName, tags.macroName],
    color: "var(--accent-warm-2)",
  },
  {
    tag: [tags.function(tags.variableName), tags.labelName],
    color: "var(--fg-primary)",
  },
  {
    tag: [
      tags.color,
      tags.constant(tags.name),
      tags.standard(tags.name),
      tags.number,
      tags.changed,
      tags.annotation,
      tags.modifier,
      tags.self,
      tags.namespace,
    ],
    color: "color-mix(in srgb, var(--state-warning) 80%, var(--fg-primary) 20%)",
  },
  {
    tag: [
      tags.operator,
      tags.url,
      tags.escape,
      tags.regexp,
      tags.link,
      tags.special(tags.string),
    ],
    color: "var(--accent-cool-2)",
  },
  { tag: tags.separator, color: "var(--fg-primary)" },
  { tag: [tags.typeName, tags.className], color: "var(--accent-warm-2)" },
  {
    tag: [tags.atom, tags.bool, tags.special(tags.variableName)],
    color: "color-mix(in srgb, var(--state-warning) 80%, var(--fg-primary) 20%)",
  },
  {
    tag: [tags.string, tags.inserted],
    color: "color-mix(in srgb, var(--state-success) 78%, var(--fg-primary) 22%)",
  },
  {
    tag: tags.deleted,
    color: "color-mix(in srgb, var(--state-error) 82%, var(--fg-primary) 18%)",
  },
  { tag: tags.strong, fontWeight: "bold" },
  { tag: tags.emphasis, fontStyle: "italic" },
  { tag: tags.strikethrough, textDecoration: "line-through" },
  {
    tag: tags.link,
    color: "var(--accent-cool-2)",
    textDecoration: "underline",
  },
  {
    tag: tags.heading,
    fontWeight: "bold",
    color: "color-mix(in srgb, var(--state-error) 82%, var(--fg-primary) 18%)",
  },
  {
    tag: tags.invalid,
    color: "color-mix(in srgb, var(--state-error) 82%, var(--fg-primary) 18%)",
    textDecoration: "underline wavy",
  },
]);

export const workbenchCodeMirrorTheme = [
  EditorView.theme({
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
      backgroundColor:
        "color-mix(in srgb, var(--vui-surface-panel) 92%, var(--vui-surface-row-hover))",
      borderColor: "var(--border-strong)",
      color: "var(--fg-primary)",
    },
  }),
  syntaxHighlighting(workbenchCodeMirrorSyntaxHighlightStyle),
] as const;
