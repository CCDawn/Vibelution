import { lazy, Suspense } from "react";

import type { FileContent, GitFileDiff } from "../../api/types";
import { VButton, VStateSurface } from "../../components/vui";
import { ChatFilePreviewPanel } from "./ChatFilePreviewPanel";
import styles from "./ChatChangeRail.styles";

const GitDiffView = lazy(() =>
  import("../GitDiffView").then((module) => ({ default: module.GitDiffView })),
);

type ChatChangeRailProps = {
  className: string;
  lang: "zh" | "en";
  paths: string[];
  selectedPath: string | null;
  changedPaths: ReadonlySet<string>;
  diff: GitFileDiff | undefined;
  diffLoading: boolean;
  hasDiff: boolean;
  file: FileContent | null | undefined;
  fileLoading: boolean;
  fileError: string;
  sourceLabel: string;
  onSelect: (path: string) => void;
};

function fileName(path: string) {
  return path.split("/").at(-1) || path;
}

export function ChatChangeRail({
  className,
  lang,
  paths,
  selectedPath,
  changedPaths,
  diff,
  diffLoading,
  hasDiff,
  file,
  fileLoading,
  fileError,
  sourceLabel,
  onSelect,
}: ChatChangeRailProps) {
  const title = lang === "zh" ? "本轮改动" : "Changes";
  const loadingLabel = lang === "zh" ? "正在打开文件" : "Opening the file";
  const emptyLabel = lang === "zh" ? "这次对话还没有改动文件" : "This chat has no changed files yet";
  const preview = selectedPath && hasDiff && diff ? (
    <GitDiffView
      path={selectedPath}
      diff={diff}
      loading={false}
      changed={changedPaths.has(selectedPath)}
      sourceLabel={sourceLabel}
    />
  ) : selectedPath ? (
    <ChatFilePreviewPanel
      changed={changedPaths.has(selectedPath)}
      errorMessage={fileError}
      file={file}
      loadingLabel={fileLoading ? loadingLabel : (lang === "zh" ? "这个文件没有可显示的差异" : "This file has no diff to show")}
      sourceLabel={sourceLabel}
    />
  ) : null;

  return (
    <aside id="chat-status-pane" className={`${styles.rail} ${className}`} aria-label={title}>
      <div className={styles.header}>
        <h2 className={styles.title}>{title}</h2>
        {paths.length > 0 ? <span className={styles.count}>{paths.length}</span> : null}
      </div>
      {paths.length > 0 ? <ul className={styles.list}>
        {paths.map((path) => {
          const selected = path === selectedPath;
          return (
            <li key={path}>
              <VButton
                type="button"
                variant="ghost"
                contentLayout="plain"
                aria-pressed={selected}
                title={path}
                className={selected ? `${styles.fileButton} ${styles.fileButtonActive}` : styles.fileButton}
                onClick={() => onSelect(path)}
              >
                <span className={styles.fileName}>{fileName(path)}</span>
                <span className={styles.filePath}>{path}</span>
              </VButton>
            </li>
          );
        })}
      </ul> : null}
      <div className={styles.body}>
        {paths.length === 0 ? (
          <VStateSurface tone="empty" title={emptyLabel} fill role="status" />
        ) : diffLoading ? (
          <VStateSurface tone="loading" title={loadingLabel} role="status" />
        ) : (
          <Suspense fallback={<VStateSurface tone="loading" title={loadingLabel} role="status" />}>
            {preview}
          </Suspense>
        )}
      </div>
    </aside>
  );
}
