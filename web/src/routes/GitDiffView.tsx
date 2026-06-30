import type { ReactNode } from "react";
import { useMemo } from "react";

import { GitFileDiff } from "../api/types";
import { buildGitDiffRows, type GitDiffLineTone } from "./gitDiffRows";
import { useGitRouteI18n } from "./gitRouteI18n";

type GitDiffViewProps = {
  path: string;
  diff: GitFileDiff | undefined;
  loading: boolean;
  changed: boolean;
  sourceLabel: string;
  headerActions?: ReactNode;
};

const surfaceClass = "grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden rounded-lg border border-vui-border-soft bg-[var(--surface-panel)]";
const headerClass = "flex items-start justify-between gap-4 border-b border-vui-border-soft px-5 pb-3.5 pt-[18px]";
const headerCopyClass = "min-w-0";
const eyebrowClass = "m-0 mb-1 text-[0.76rem] uppercase tracking-[0.08em] text-vui-fg-tertiary";
const fileNameClass = "m-0 font-[var(--font-display)] text-[1.28rem] text-vui-fg-primary";
const filePathClass = "m-0 mt-2 break-all leading-[1.4] text-vui-fg-secondary";
const summaryClass = "m-0 mt-2 break-all text-[0.8rem] leading-[1.4] text-vui-fg-tertiary";
const metaBlockClass = "flex flex-wrap justify-end gap-2";
const pillClass = "inline-flex min-h-7 items-center whitespace-nowrap rounded-full px-2.5 text-[0.8rem]";
const changedPillClass = `${pillClass} border border-[color-mix(in_srgb,var(--accent-warm)_18%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_12%,transparent)] text-[var(--accent-warm-2)]`;
const sourcePillClass = `${pillClass} border border-[color-mix(in_srgb,var(--accent-cool)_18%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,transparent)] text-vui-fg-secondary`;
const diffWrapClass = "min-h-0 overflow-auto bg-[var(--surface-code)]";
const diffTableClass = "w-max min-w-full py-2 font-[var(--font-mono)] text-[0.78rem] leading-[1.55]";
const diffRowClass = "grid min-w-full grid-cols-[54px_54px_24px_minmax(0,1fr)] pr-[18px]";
const columnHeaderClass = "sticky top-0 z-[2] border-b border-[var(--border-hairline,var(--border-soft))] bg-[var(--surface-panel-muted)] text-vui-fg-tertiary";
const lineNumberClass = "min-w-0 select-none py-px pr-2.5 text-right text-vui-fg-tertiary";
const lineMarkerClass = "min-w-0 select-none py-px text-center text-vui-fg-tertiary";
const lineContentClass = "block min-w-0 whitespace-pre py-px";
const footnoteClass = "m-0 border-t border-vui-border-soft px-5 pb-3.5 pt-2.5 text-[0.82rem] text-vui-fg-tertiary";

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
    <div className={surfaceClass}>
      <div className={headerClass}>
        <div className={headerCopyClass}>
          <p className={eyebrowClass}>{t("readonlyPreview")}</p>
          <h2 className={fileNameClass}>{path.split("/").at(-1)}</h2>
          <p className={filePathClass}>{path}</p>
          {diff?.summary ? <p className={summaryClass}>{diff.summary}</p> : null}
        </div>
        <div className={metaBlockClass}>
          {changed ? <span className={changedPillClass}>{t("changed")}</span> : null}
          <span className={sourcePillClass}>{sourceLabel}</span>
          {headerActions}
        </div>
      </div>

      <div className={diffWrapClass} aria-label={t("gitFileDiff")}>
        <div className={diffTableClass}>
          <div className={`${diffRowClass} ${columnHeaderClass}`} aria-hidden="true">
            <span>-</span>
            <span>+</span>
            <span />
            <span />
          </div>
          {rows.map((row) => (
            <div key={row.id} className={`${diffRowClass} ${toneClassByLine[row.tone]}`}>
              <span className={lineNumberClass}>{row.oldLine ?? ""}</span>
              <span className={lineNumberClass}>{row.newLine ?? ""}</span>
              <span className={lineMarkerClass}>{row.marker}</span>
              <code className={lineContentClass}>{row.text || " "}</code>
            </div>
          ))}
        </div>
      </div>

      {diff?.truncated ? <p className={footnoteClass}>{t("previewTruncated")}</p> : null}
    </div>
  );
}
