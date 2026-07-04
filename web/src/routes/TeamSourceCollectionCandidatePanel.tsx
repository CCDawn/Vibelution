import { type ReactNode, type SyntheticEvent } from "react";

import styles from "./TeamSourceCollectionCandidatePanel.styles";

export type TeamSourceCollectionCandidatePanelStat = {
  key: string;
  label: ReactNode;
  value: ReactNode;
};

type TeamSourceCollectionCandidatePanelProps = {
  lang: "zh" | "en";
  className: string;
  open: boolean;
  rangeText: ReactNode;
  filterBar: ReactNode;
  stats: TeamSourceCollectionCandidatePanelStat[];
  hasCandidates: boolean;
  listNeedsScrollHint: boolean;
  emptyMessage: ReactNode;
  recoveryPanel: ReactNode;
  pagination: ReactNode;
  children: ReactNode;
  onToggle: (event: SyntheticEvent<HTMLDetailsElement>) => void;
};

export function TeamSourceCollectionCandidatePanel({
  lang,
  className,
  open,
  rangeText,
  filterBar,
  stats,
  hasCandidates,
  listNeedsScrollHint,
  emptyMessage,
  recoveryPanel,
  pagination,
  children,
  onToggle,
}: TeamSourceCollectionCandidatePanelProps) {
  return (
    <details
      id="source-collection-candidates-panel"
      className={className}
      open={open}
      onToggle={onToggle}
      tabIndex={-1}
    >
      <summary>
        <span>{lang === "zh" ? "资料提炼结果" : "Extracted sources"}</span>
        <small>{rangeText}</small>
      </summary>
      {filterBar}
      <div className={styles.workflowSourceQualityStats}>
        {stats.map((stat) => (
          <span key={stat.key}>
            {stat.label} <strong>{stat.value}</strong>
          </span>
        ))}
      </div>
      {hasCandidates ? (
        <div
          className={styles.sourceCollectionCandidateListShell}
          role="region"
          tabIndex={0}
          aria-label={lang === "zh" ? "资料提炼候选列表，可向下滚动查看更多" : "Extracted candidate list, scroll for more"}
        >
          <div className={styles.workflowCandidateList}>{children}</div>
          {listNeedsScrollHint ? (
            <div className={styles.sourceCollectionScreeningScrollHint} aria-hidden="true">
              <span>{lang === "zh" ? "向下滚动查看更多本页候选" : "Scroll down for more candidates on this page"}</span>
            </div>
          ) : null}
        </div>
      ) : (
        <div className={styles.empty}>{emptyMessage}</div>
      )}
      {recoveryPanel}
      {pagination}
    </details>
  );
}
