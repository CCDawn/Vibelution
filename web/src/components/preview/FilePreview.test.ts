import { describe, expect, it } from "vitest";

import { buildFilePreviewKey } from "./FilePreview";
import previewSource from "./FilePreview.tsx?raw";

describe("buildFilePreviewKey", () => {
  it("changes when the preview content or log filter changes", () => {
    const base = buildFilePreviewKey({
      path: "raw/backend.stdout.log",
      language: "text",
      content: "line 1\nline 2",
      highlightAsLog: true,
      severityFilter: "all",
    });
    const filtered = buildFilePreviewKey({
      path: "raw/backend.stdout.log",
      language: "text",
      content: "line 1\nline 2",
      highlightAsLog: true,
      severityFilter: "error",
    });
    const changedContent = buildFilePreviewKey({
      path: "raw/backend.stdout.log",
      language: "text",
      content: "line 1\nline 2\nline 3",
      highlightAsLog: true,
      severityFilter: "all",
    });

    expect(filtered).not.toBe(base);
    expect(changedContent).not.toBe(base);
  });

  it("changes when the same content is shown from another file path or language", () => {
    const base = buildFilePreviewKey({
      path: "raw/backend.stdout.log",
      language: "text",
      content: "same content",
      highlightAsLog: true,
      severityFilter: "all",
    });
    const movedFile = buildFilePreviewKey({
      path: "raw/browser.telemetry.log",
      language: "text",
      content: "same content",
      highlightAsLog: true,
      severityFilter: "all",
    });
    const changedLanguage = buildFilePreviewKey({
      path: "raw/backend.stdout.log",
      language: "json",
      content: "same content",
      highlightAsLog: true,
      severityFilter: "all",
    });

    expect(movedFile).not.toBe(base);
    expect(changedLanguage).not.toBe(base);
  });

  it("keeps the key stable for identical inputs", () => {
    const first = buildFilePreviewKey({
      path: "conversations/session.jsonl",
      language: "json",
      content: '{"ok":true}',
      highlightAsLog: false,
      severityFilter: "all",
    });
    const second = buildFilePreviewKey({
      path: "conversations/session.jsonl",
      language: "json",
      content: '{"ok":true}',
      highlightAsLog: false,
      severityFilter: "all",
    });

    expect(second).toBe(first);
  });
});

describe("FilePreview editor fallback contract", () => {
  it("wraps CodeMirror in a local fallback boundary", () => {
    expect(previewSource).toContain("<PreviewEditorErrorBoundary key={editorKey}");
    expect(previewSource).toContain("fallbackContent={displayContent}");
    expect(previewSource).toContain("className={styles.plainFallback}");
    expect(previewSource).toContain("[file-preview-fallback]");
  });

  it("loads CodeMirror language extensions on demand", () => {
    expect(previewSource).not.toContain('import { javascript } from "@codemirror/lang-javascript"');
    expect(previewSource).not.toContain('import { json } from "@codemirror/lang-json"');
    expect(previewSource).not.toContain('import { markdown } from "@codemirror/lang-markdown"');
    expect(previewSource).not.toContain('import { python } from "@codemirror/lang-python"');
    expect(previewSource).not.toContain('import { yaml } from "@codemirror/lang-yaml"');
    expect(previewSource).toContain('import("@codemirror/lang-javascript")');
    expect(previewSource).toContain('import("@codemirror/lang-json")');
    expect(previewSource).toContain('import("@codemirror/lang-markdown")');
    expect(previewSource).toContain('import("@codemirror/lang-python")');
    expect(previewSource).toContain('import("@codemirror/lang-yaml")');
    expect(previewSource).toContain("useFilePreviewLanguageExtensions(file.language)");
  });
});
