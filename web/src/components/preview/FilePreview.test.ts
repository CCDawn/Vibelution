import { afterEach, describe, expect, it, vi } from "vitest";

import { postBrowserTelemetry } from "../../app/browserTelemetry";
import {
  buildFilePreviewKey,
  buildPreviewEditorErrorTelemetryEvent,
  reportPreviewEditorError,
  resetPreviewEditorErrorTelemetryForTests,
  safePreviewPathForLog,
} from "./FilePreview";
import previewSource from "./FilePreview.tsx?raw";
import stylesSource from "./FilePreview.styles.ts?raw";

vi.mock("../../app/browserTelemetry", () => ({
  postBrowserTelemetry: vi.fn(),
}));

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
    expect(previewSource).toContain("className={styles.plainFallbackClass}");
    expect(stylesSource).toContain("plainFallbackClass");
    expect(previewSource).toContain("[file-preview-fallback]");
    expect(previewSource).toContain("reportPreviewEditorError");
    expect(previewSource).toContain("browser.preview.error");
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

describe("PreviewEditorErrorBoundary telemetry", () => {
  afterEach(() => {
    resetPreviewEditorErrorTelemetryForTests();
    vi.mocked(postBrowserTelemetry).mockClear();
  });

  it("builds a scene-ready preview crash event without file body text", () => {
    const error = new Error("CodeMirror exploded");
    const event = buildPreviewEditorErrorTelemetryEvent(error, "web/src/routes/GitRoute.tsx", {
      componentStackLength: 42,
    });

    expect(event).toMatchObject({
      phase: "error",
      eventCode: "browser.preview.error",
      level: "error",
      message: "file preview editor crashed",
      fields: {
        surface: "file_preview",
        path: "web/src/routes/GitRoute.tsx",
        errorName: "Error",
        errorMessage: "Error: CodeMirror exploded",
        componentStackLength: 42,
      },
    });
    expect(JSON.stringify(event)).not.toContain("fallback");
    expect(JSON.stringify(event)).not.toContain("displayContent");
  });

  it("redacts absolute and escaped preview paths to a basename", () => {
    expect(safePreviewPathForLog(String.raw`C:\Users\Administrator\secret\notes.md`)).toBe("notes.md");
    expect(safePreviewPathForLog("../secret.txt")).toBe("secret.txt");
    expect(safePreviewPathForLog("core/web/services/file_service.py")).toBe("core/web/services/file_service.py");
  });

  it("posts one telemetry event per unique preview crash", () => {
    const error = new Error("unique preview crash");
    reportPreviewEditorError(error, "raw/backend.stdout.log", { componentStackLength: 12 });
    reportPreviewEditorError(error, "raw/backend.stdout.log", { componentStackLength: 12 });

    expect(postBrowserTelemetry).toHaveBeenCalledTimes(1);
    expect(vi.mocked(postBrowserTelemetry).mock.calls[0]?.[0]).toMatchObject({
      eventCode: "browser.preview.error",
      fields: {
        path: "raw/backend.stdout.log",
        errorMessage: "Error: unique preview crash",
      },
    });
  });
});
