import { Component, type ErrorInfo, type ReactNode, useEffect, useMemo, useState } from "react";

import CodeMirror from "@uiw/react-codemirror";
import { RangeSetBuilder } from "@codemirror/state";
import type { Extension } from "@codemirror/state";
import { Decoration, EditorView } from "@codemirror/view";

import { FileContent } from "../../api/types";
import { VButton } from "../vui";
import { workbenchCodeMirrorTheme } from "../../design/codeMirrorTheme";
import { useAppI18n } from "../../i18n/useAppI18n";
import { classifyLogText, matchesSeverityFilter, type LogSeverityFilter } from "../../logs/logSeverity";
import { parseStructuredLogPreview } from "../../logs/structuredLogPreview";
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

const surfaceClass = "grid h-full min-h-0 grid-rows-[auto_1fr_auto]";
const headerClass = "flex items-start justify-between gap-4 border-b border-vui-border-soft px-5 pb-3.5 pt-[18px]";
const headerCopyClass = "min-w-0";
const eyebrowClass = "m-0 mb-1 text-[var(--vui-font-xs)] uppercase tracking-[0.08em] text-vui-fg-tertiary";
const fileNameClass = "m-0 font-[var(--font-body)] text-[1.02rem] font-bold text-vui-fg-primary";
const filePathClass = "m-0 mt-2 break-all text-vui-fg-secondary";
const metaBlockClass = "flex flex-wrap justify-end gap-2";
const pillClass = "inline-flex items-center rounded-[var(--radius-control)] px-2.5 py-1.5 text-[0.8rem]";
const changedPillClass = `${pillClass} border border-[color-mix(in_srgb,var(--accent-warm)_18%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_12%,transparent)] text-[var(--accent-warm-2)]`;
const sourcePillClass = `${pillClass} border border-[color-mix(in_srgb,var(--accent-cool)_18%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,transparent)] text-vui-fg-secondary`;
const previewModeGroupClass = "inline-flex items-center gap-1 rounded-lg border border-vui-border-soft bg-[color-mix(in_srgb,var(--surface-raised)_72%,transparent)] p-[3px]";
const previewModeButtonClass = "min-h-[26px] border-0 bg-transparent px-2 py-[3px] text-[var(--vui-font-xs)] font-[inherit] text-vui-fg-secondary shadow-none";
const previewModeButtonActiveClass = "bg-[color-mix(in_srgb,var(--accent-cool)_18%,var(--surface-panel))] text-vui-fg-primary";
const editorWrapClass = [
  "grid min-h-0 overflow-hidden",
  "[&_.cm-theme]:h-full [&_.cm-theme]:min-h-0",
  "[&_.cm-editor]:h-full [&_.cm-editor]:min-h-0",
  "[&_.cm-scroller]:overflow-auto",
  "[&_.cm-content]:min-h-full [&_.cm-gutter]:min-h-full",
].join(" ");
const plainFallbackClass = "m-0 h-full min-h-0 overflow-auto whitespace-pre-wrap break-words bg-[var(--surface-panel)] px-4 py-3.5 font-[var(--font-mono)] text-[var(--vui-font-xs)] leading-[1.55] text-vui-fg-primary";
const footnoteClass = "m-0 border-t border-vui-border-soft px-5 pb-3.5 pt-2.5 text-[var(--vui-font-xs)] text-vui-fg-tertiary";

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
      return <pre className={plainFallbackClass}>{this.props.fallbackContent}</pre>;
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
  const { t } = useAppI18n();
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
    <div className={previewModeGroupClass} role="group" aria-label={t("logPreviewMode")}>
      <VButton
        type="button"
        variant="ghost"
        className={viewMode === "structured" ? `${previewModeButtonClass} ${previewModeButtonActiveClass}` : previewModeButtonClass}
        onPress={() => setViewMode("structured")}
      >
        {t("logPreviewStructured")}
      </VButton>
      <VButton
        type="button"
        variant="ghost"
        className={viewMode === "raw" ? `${previewModeButtonClass} ${previewModeButtonActiveClass}` : previewModeButtonClass}
        onPress={() => setViewMode("raw")}
      >
        {t("logPreviewRaw")}
      </VButton>
    </div>
  ) : null;

  return (
    <div className={surfaceClass}>
      <div className={headerClass}>
        <div className={headerCopyClass}>
          <p className={eyebrowClass}>{t("readonlyPreview")}</p>
          <h2 className={fileNameClass}>{file.path.split("/").at(-1)}</h2>
          <p className={filePathClass}>{file.path}</p>
        </div>
        <div className={metaBlockClass}>
          {changed ? <span className={changedPillClass}>{t("changed")}</span> : null}
          <span className={sourcePillClass}>{sourceLabel}</span>
          {previewModeActions}
          {headerActions}
        </div>
      </div>

      <div className={editorWrapClass}>
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

      {file.truncated ? <p className={footnoteClass}>{t("previewTruncated")}</p> : null}
    </div>
  );
}
