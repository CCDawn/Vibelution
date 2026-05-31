import { Component, type ErrorInfo, type ReactNode, useMemo, useState } from "react";

import CodeMirror from "@uiw/react-codemirror";
import { RangeSetBuilder } from "@codemirror/state";
import { Decoration, EditorView } from "@codemirror/view";
import { javascript } from "@codemirror/lang-javascript";
import { json } from "@codemirror/lang-json";
import { markdown } from "@codemirror/lang-markdown";
import { python } from "@codemirror/lang-python";
import { yaml } from "@codemirror/lang-yaml";

import { FileContent } from "../../api/types";
import { workbenchCodeMirrorTheme } from "../../design/codeMirrorTheme";
import { useAppI18n } from "../../i18n/useAppI18n";
import { classifyLogText, matchesSeverityFilter, type LogSeverityFilter } from "../../logs/logSeverity";
import { parseStructuredLogPreview } from "../../logs/structuredLogPreview";
import styles from "./FilePreview.module.css";
import { StructuredLogPreview } from "./StructuredLogPreview";

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
    console.warn("[file-preview-fallback]", {
      path: this.props.previewPath,
      errorName,
      errorMessage,
      componentStackLength: info.componentStack?.length ?? 0,
    });
  }

  render() {
    if (this.state.failed) {
      return <pre className={styles.plainFallback}>{this.props.fallbackContent}</pre>;
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

function getExtensions(language: string) {
  switch (language) {
    case "python":
      return [python(), EditorView.lineWrapping];
    case "json":
      return [json(), EditorView.lineWrapping];
    case "markdown":
      return [markdown(), EditorView.lineWrapping];
    case "yaml":
      return [yaml(), EditorView.lineWrapping];
    case "javascript":
    case "typescript":
    case "tsx":
      return [javascript({ typescript: true, jsx: language === "tsx" }), EditorView.lineWrapping];
    default:
      return [EditorView.lineWrapping];
  }
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
  },
  ".cm-logLineWarning": {
    backgroundColor: "rgba(215, 160, 84, 0.12)",
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
  const { t } = useAppI18n();
  const [viewMode, setViewMode] = useState<"structured" | "raw">("structured");
  const editorExtensions = useMemo(() => {
    const extensions = getExtensions(file.language);
    return highlightAsLog ? [...extensions, logLineDecorations, logHighlightTheme] : extensions;
  }, [file.language, highlightAsLog]);
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
    <div className={styles.previewModeGroup} role="group" aria-label={t("logPreviewMode")}>
      <button
        type="button"
        className={viewMode === "structured" ? `${styles.previewModeButton} ${styles.previewModeButtonActive}` : styles.previewModeButton}
        onClick={() => setViewMode("structured")}
      >
        {t("logPreviewStructured")}
      </button>
      <button
        type="button"
        className={viewMode === "raw" ? `${styles.previewModeButton} ${styles.previewModeButtonActive}` : styles.previewModeButton}
        onClick={() => setViewMode("raw")}
      >
        {t("logPreviewRaw")}
      </button>
    </div>
  ) : null;

  return (
    <div className={styles.surface}>
      <div className={styles.header}>
        <div className={styles.headerCopy}>
          <p className={styles.eyebrow}>{t("readonlyPreview")}</p>
          <h2 className={styles.fileName}>{file.path.split("/").at(-1)}</h2>
          <p className={styles.filePath}>{file.path}</p>
        </div>
        <div className={styles.metaBlock}>
          {changed ? <span className={styles.changedPill}>{t("changed")}</span> : null}
          <span className={styles.sourcePill}>{sourceLabel}</span>
          {previewModeActions}
          {headerActions}
        </div>
      </div>

      <div className={styles.editorWrap}>
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

      {file.truncated ? <p className={styles.footnote}>{t("previewTruncated")}</p> : null}
    </div>
  );
}
