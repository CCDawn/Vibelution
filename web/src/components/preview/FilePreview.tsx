import { Component, type ErrorInfo, type ReactNode, useEffect, useMemo, useState } from "react";

import CodeMirror from "@uiw/react-codemirror";
import { RangeSetBuilder } from "@codemirror/state";
import type { Extension } from "@codemirror/state";
import { Decoration, EditorView } from "@codemirror/view";

import { FileContent } from "../../api/types";
import { type BrowserTelemetryEventInput, postBrowserTelemetry } from "../../app/browserTelemetry";
import { VButton } from "../vui";
import { workbenchCodeMirrorTheme } from "../../design/codeMirrorTheme";
import { useAppI18n } from "../../i18n/useAppI18n";
import { classifyLogText, matchesSeverityFilter, type LogSeverityFilter } from "../../logs/logSeverity";
import { parseStructuredLogPreview } from "../../logs/structuredLogPreview";
import { StructuredLogPreview } from "./StructuredLogPreview";
import styles from "./FilePreview.styles";

export type FilePreviewProps = {
  file: FileContent;
  changed: boolean;
  sourceLabel: string;
  headerActions?: ReactNode;
  highlightAsLog?: boolean;
  severityFilter?: LogSeverityFilter;
};

type PreviewEditorErrorBoundaryProps = {
  previewPath: string;
  fallbackContent: string;
  children: ReactNode;
};

type PreviewEditorErrorBoundaryState = {
  failed: boolean;
};

const reportedPreviewErrorKeys = new Set<string>();
const PREVIEW_PATH_LOG_LIMIT = 240;
const PREVIEW_ERROR_TEXT_LIMIT = 240;

function compactErrorText(error: unknown, limit: number) {
  const text = error instanceof Error
    ? `${error.name}: ${error.message}`
    : String(error ?? "Unknown preview editor error");
  const compacted = text.replace(/\s+/g, " ").trim();
  if (compacted.length <= limit) {
    return compacted || "Unknown preview editor error";
  }
  return `${compacted.slice(0, Math.max(0, limit - 3))}...`;
}

export function safePreviewPathForLog(path: string) {
  const text = String(path || "").replace(/\\/g, "/").trim();
  if (!text) {
    return "";
  }
  const isAbsolute = /^[A-Za-z]:/.test(text) || text.startsWith("/") || text.startsWith("//");
  const escaped = text.includes("..");
  if (isAbsolute || escaped) {
    return (text.split("/").filter(Boolean).at(-1) || "").slice(0, PREVIEW_PATH_LOG_LIMIT);
  }
  return text.slice(0, PREVIEW_PATH_LOG_LIMIT);
}

export function buildPreviewEditorErrorTelemetryEvent(
  error: unknown,
  previewPath: string,
  info?: { componentStackLength?: number },
): BrowserTelemetryEventInput {
  return {
    phase: "error",
    eventCode: "browser.preview.error",
    message: "file preview editor crashed",
    level: "error",
    fields: {
      surface: "file_preview",
      path: safePreviewPathForLog(previewPath),
      errorName: error instanceof Error ? error.name : "Unknown",
      errorMessage: compactErrorText(error, PREVIEW_ERROR_TEXT_LIMIT),
      componentStackLength: info?.componentStackLength ?? 0,
    },
  };
}

export function resetPreviewEditorErrorTelemetryForTests() {
  reportedPreviewErrorKeys.clear();
}

export function reportPreviewEditorError(
  error: unknown,
  previewPath: string,
  info?: { componentStackLength?: number },
) {
  const event = buildPreviewEditorErrorTelemetryEvent(error, previewPath, info);
  const key = [
    String(event.fields?.path ?? ""),
    String(event.fields?.errorName ?? ""),
    String(event.fields?.errorMessage ?? ""),
  ].join("|");
  if (reportedPreviewErrorKeys.has(key)) {
    return;
  }
  reportedPreviewErrorKeys.add(key);
  postBrowserTelemetry(event);
}

class PreviewEditorErrorBoundary extends Component<
  PreviewEditorErrorBoundaryProps,
  PreviewEditorErrorBoundaryState
> {
  state: PreviewEditorErrorBoundaryState = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    const errorName = error instanceof Error ? error.name : typeof error;
    const errorMessage = error instanceof Error ? error.message : String(error);
    const componentStackLength = info.componentStack?.length ?? 0;
    reportPreviewEditorError(error, this.props.previewPath, { componentStackLength });
    console.warn("[file-preview-fallback]", {
      path: safePreviewPathForLog(this.props.previewPath),
      errorName,
      errorMessage,
      componentStackLength,
    });
  }

  render() {
    if (this.state.failed) {
      return <pre className={styles.plainFallbackClass}>{this.props.fallbackContent}</pre>;
    }
    return this.props.children;
  }
}

function buildPreviewFingerprint(value: string) {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) >>> 0;
  }
  return `${value.length}:${hash.toString(36)}`;
}

export function buildFilePreviewKey({
  path,
  language,
  content,
  highlightAsLog,
  severityFilter,
}: {
  path: string;
  language: string;
  content: string;
  highlightAsLog: boolean;
  severityFilter: LogSeverityFilter;
}) {
  return [
    path,
    language,
    highlightAsLog ? "log" : "plain",
    severityFilter,
    buildPreviewFingerprint(content),
  ].join("|");
}

async function loadLanguageExtensions(language: string): Promise<Extension[]> {
  switch (language) {
    case "python":
      return import("@codemirror/lang-python").then((module) => [module.python()]);
    case "json":
      return import("@codemirror/lang-json").then((module) => [module.json()]);
    case "markdown":
      return import("@codemirror/lang-markdown").then((module) => [module.markdown()]);
    case "yaml":
      return import("@codemirror/lang-yaml").then((module) => [module.yaml()]);
    case "javascript":
    case "typescript":
    case "tsx":
      return import("@codemirror/lang-javascript").then((module) => [
        module.javascript({ typescript: true, jsx: language === "tsx" }),
      ]);
    default:
      return [];
  }
}

function useFilePreviewLanguageExtensions(language: string) {
  const [languageExtensions, setLanguageExtensions] = useState<Extension[]>([]);

  useEffect(() => {
    let cancelled = false;
    setLanguageExtensions([]);
    void loadLanguageExtensions(language).then((extensions) => {
      if (!cancelled) {
        setLanguageExtensions(extensions);
      }
    }).catch(() => {
      if (!cancelled) {
        setLanguageExtensions([]);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [language]);

  return languageExtensions;
}

const logLineDecorations = EditorView.decorations.compute([], (state) => {
  const builder = new RangeSetBuilder<Decoration>();
  for (let lineNumber = 1; lineNumber <= state.doc.lines; lineNumber += 1) {
    const line = state.doc.line(lineNumber);
    const severity = classifyLogText(line.text);
    if (severity === "error") {
      builder.add(line.from, line.from, Decoration.line({ class: "cm-logLineError" }));
      continue;
    }
    if (severity === "warning") {
      builder.add(line.from, line.from, Decoration.line({ class: "cm-logLineWarning" }));
    }
  }
  return builder.finish();
});

const logHighlightTheme = EditorView.baseTheme({
  ".cm-logLineError": {
    backgroundColor: "rgba(187, 108, 93, 0.14)",
    color: "var(--state-error)",
  },
  ".cm-logLineWarning": {
    backgroundColor: "rgba(215, 160, 84, 0.12)",
    color: "var(--state-warning)",
  },
  ".cm-logLineError .cm-cursor, .cm-logLineWarning .cm-cursor": {
    borderLeftColor: "currentColor",
  },
});

export function FilePreview({
  file,
  changed,
  sourceLabel,
  headerActions,
  highlightAsLog = false,
  severityFilter = "all",
}: FilePreviewProps) {
  const { t } = useAppI18n({ domains: ["chat"] });
  const [viewMode, setViewMode] = useState<"structured" | "raw">("structured");
  const languageExtensions = useFilePreviewLanguageExtensions(file.language);
  const editorExtensions = useMemo(() => {
    const extensions = [...languageExtensions, EditorView.lineWrapping];
    return highlightAsLog ? [...extensions, logLineDecorations, logHighlightTheme] : extensions;
  }, [languageExtensions, highlightAsLog]);
  const displayContent = useMemo(() => {
    if (!highlightAsLog || severityFilter === "all") {
      return file.content;
    }
    const matchingLines = file.content
      .split(/\r?\n/)
      .filter((line) => matchesSeverityFilter(classifyLogText(line), severityFilter));
    return matchingLines.length > 0 ? matchingLines.join("\n") : t("logSeverityEmpty");
  }, [file.content, highlightAsLog, severityFilter, t]);
  const editorKey = buildFilePreviewKey({
    path: file.path,
    language: file.language,
    content: displayContent,
    highlightAsLog,
    severityFilter,
  });
  const structuredModel = useMemo(() => {
    if (!highlightAsLog) {
      return null;
    }
    return parseStructuredLogPreview(file.content);
  }, [file.content, highlightAsLog]);
  const showStructuredPreview = Boolean(structuredModel && viewMode === "structured");
  const previewModeActions = structuredModel ? (
    <div className={styles.previewModeGroupClass} role="group" aria-label={t("logPreviewMode")}>
      <VButton
        type="button"
        variant="ghost"
        className={viewMode === "structured" ? `${styles.previewModeButtonClass} ${styles.previewModeButtonActiveClass}` : styles.previewModeButtonClass}
        onPress={() => setViewMode("structured")}
      >
        {t("logPreviewStructured")}
      </VButton>
      <VButton
        type="button"
        variant="ghost"
        className={viewMode === "raw" ? `${styles.previewModeButtonClass} ${styles.previewModeButtonActiveClass}` : styles.previewModeButtonClass}
        onPress={() => setViewMode("raw")}
      >
        {t("logPreviewRaw")}
      </VButton>
    </div>
  ) : null;

  return (
    <div className={styles.surfaceClass}>
      <div className={styles.headerClass}>
        <div className={styles.headerCopyClass}>
          <p className={styles.eyebrowClass}>{t("readonlyPreview")}</p>
          <h2 className={styles.fileNameClass}>{file.path.split("/").at(-1)}</h2>
          <p className={styles.filePathClass}>{file.path}</p>
        </div>
        <div className={styles.metaBlockClass}>
          {changed ? <span className={styles.changedPillClass}>{t("changed")}</span> : null}
          <span className={styles.sourcePillClass}>{sourceLabel}</span>
          {previewModeActions}
          {headerActions}
        </div>
      </div>

      <div className={styles.editorWrapClass}>
        {showStructuredPreview && structuredModel ? (
          <StructuredLogPreview model={structuredModel} severityFilter={severityFilter} />
        ) : (
          <PreviewEditorErrorBoundary key={editorKey} previewPath={file.path} fallbackContent={displayContent}>
            <CodeMirror
              value={displayContent}
              editable={false}
              theme={workbenchCodeMirrorTheme}
              height="100%"
              extensions={editorExtensions}
              basicSetup={{
                foldGutter: false,
                dropCursor: false,
                allowMultipleSelections: false,
                indentOnInput: false,
              }}
            />
          </PreviewEditorErrorBoundary>
        )}
      </div>

      {file.truncated ? <p className={styles.footnoteClass}>{t("previewTruncated")}</p> : null}
    </div>
  );
}
