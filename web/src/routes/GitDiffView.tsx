import type { ReactNode } from "react";
import { useMemo } from "react";

import { GitFileDiff } from "../api/types";
import { useShellI18n } from "../i18n/useShellI18n";
import { buildGitDiffRows } from "./gitDiffRows";
import styles from "./GitDiffView.module.css";

type GitDiffViewProps = {
  path: string;
  diff: GitFileDiff | undefined;
  loading: boolean;
  changed: boolean;
  sourceLabel: string;
  headerActions?: ReactNode;
};

export function GitDiffView({ path, diff, loading, changed, sourceLabel, headerActions }: GitDiffViewProps) {
  const { t } = useShellI18n();
  const rows = useMemo(
    () =>
      buildGitDiffRows({
        diff: diff?.diff,
        content: diff?.content,
        binary: diff?.binary,
        loading,
        loadingText: t("loading"),
        binaryText: t("gitBinaryFile"),
        emptyText: t("gitDiffEmpty"),
      }),
    [diff?.binary, diff?.content, diff?.diff, loading, t],
  );

  return (
    <div className={styles.surface}>
      <div className={styles.header}>
        <div className={styles.headerCopy}>
          <p className={styles.eyebrow}>{t("readonlyPreview")}</p>
          <h2 className={styles.fileName}>{path.split("/").at(-1)}</h2>
          <p className={styles.filePath}>{path}</p>
          {diff?.summary ? <p className={styles.summary}>{diff.summary}</p> : null}
        </div>
        <div className={styles.metaBlock}>
          {changed ? <span className={styles.changedPill}>{t("changed")}</span> : null}
          <span className={styles.sourcePill}>{sourceLabel}</span>
          {headerActions}
        </div>
      </div>

      <div className={styles.diffWrap} aria-label={t("gitFileDiff")}>
        <div className={styles.diffTable}>
          <div className={`${styles.diffRow} ${styles.columnHeader}`} aria-hidden="true">
            <span>-</span>
            <span>+</span>
            <span />
            <span />
          </div>
          {rows.map((row) => (
            <div key={row.id} className={`${styles.diffRow} ${styles[`line_${row.tone}`]}`}>
              <span className={styles.lineNumber}>{row.oldLine ?? ""}</span>
              <span className={styles.lineNumber}>{row.newLine ?? ""}</span>
              <span className={styles.lineMarker}>{row.marker}</span>
              <code className={styles.lineContent}>{row.text || " "}</code>
            </div>
          ))}
        </div>
      </div>

      {diff?.truncated ? <p className={styles.footnote}>{t("previewTruncated")}</p> : null}
    </div>
  );
}
