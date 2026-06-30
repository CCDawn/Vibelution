import type { ReactNode } from "react";
import { useMemo } from "react";

import { GitFileDiff } from "../api/types";
import { buildGitDiffRows, type GitDiffLineTone } from "./gitDiffRows";
import { useGitRouteI18n } from "./gitRouteI18n";
import styles from "./GitDiffView.styles";

type GitDiffViewProps = {
  path: string;
  diff: GitFileDiff | undefined;
  loading: boolean;
  changed: boolean;
  sourceLabel: string;
  headerActions?: ReactNode;
};


const toneClassByLine: Record<GitDiffLineTone, string> = {
  added: "bg-[color-mix(in_srgb,var(--state-success)_19%,transparent)] shadow-[var(--vui-shadow-inset-accent)] [&>span]:text-[var(--state-success)]",
  removed: "bg-[color-mix(in_srgb,var(--state-error)_20%,transparent)] shadow-[var(--vui-shadow-inset-accent)] [&>span]:text-[var(--state-error)]",
  hunk: "bg-[color-mix(in_srgb,var(--accent-cool)_15%,transparent)] text-[var(--accent-cool)]",
  section: "bg-[color-mix(in_srgb,var(--accent-warm)_11%,transparent)] uppercase text-[var(--accent-warm-2)]",
  meta: "text-vui-fg-tertiary",
  empty: "text-vui-fg-tertiary",
  context: "text-vui-fg-primary",
};

export function GitDiffView({ path, diff, loading, changed, sourceLabel, headerActions }: GitDiffViewProps) {
  const { t } = useGitRouteI18n();
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
    <div className={styles.surfaceClass}>
      <div className={styles.headerClass}>
        <div className={styles.headerCopyClass}>
          <p className={styles.eyebrowClass}>{t("readonlyPreview")}</p>
          <h2 className={styles.fileNameClass}>{path.split("/").at(-1)}</h2>
          <p className={styles.filePathClass}>{path}</p>
          {diff?.summary ? <p className={styles.summaryClass}>{diff.summary}</p> : null}
        </div>
        <div className={styles.metaBlockClass}>
          {changed ? <span className={styles.changedPillClass}>{t("changed")}</span> : null}
          <span className={styles.sourcePillClass}>{sourceLabel}</span>
          {headerActions}
        </div>
      </div>

      <div className={styles.diffWrapClass} aria-label={t("gitFileDiff")}>
        <div className={styles.diffTableClass}>
          <div className={`${styles.diffRowClass} ${styles.columnHeaderClass}`} aria-hidden="true">
            <span>-</span>
            <span>+</span>
            <span />
            <span />
          </div>
          {rows.map((row) => (
            <div key={row.id} className={`${styles.diffRowClass} ${toneClassByLine[row.tone]}`}>
              <span className={styles.lineNumberClass}>{row.oldLine ?? ""}</span>
              <span className={styles.lineNumberClass}>{row.newLine ?? ""}</span>
              <span className={styles.lineMarkerClass}>{row.marker}</span>
              <code className={styles.lineContentClass}>{row.text || " "}</code>
            </div>
          ))}
        </div>
      </div>

      {diff?.truncated ? <p className={styles.footnoteClass}>{t("previewTruncated")}</p> : null}
    </div>
  );
}
