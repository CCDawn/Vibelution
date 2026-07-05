import { type ReactNode, type SyntheticEvent } from "react";

import panelFrameStyles from "./TeamSourceCollectionPanelFrame.styles";
import styles from "./TeamSourceCollectionScreeningPanel.styles";

export type TeamSourceCollectionScreeningPanelStat = {
  key: string;
  label: ReactNode;
  value: ReactNode;
};

type TeamSourceCollectionScreeningPanelProps = {
  lang: "zh" | "en";
  focused: boolean;
  open: boolean;
  rangeText: ReactNode;
  filterBar: ReactNode;
  stats: TeamSourceCollectionScreeningPanelStat[];
  actions: ReactNode;
  hasCandidates: boolean;
  listNeedsScrollHint: boolean;
  emptyMessage: ReactNode;
  pagination: ReactNode;
  statusItems: ReactNode;
  errors: ReactNode;
  children: ReactNode;
  onToggle: (event: SyntheticEvent<HTMLDetailsElement>) => void;
};

export function TeamSourceCollectionScreeningPanel({
  lang,
  focused,
  open,
  rangeText,
  filterBar,
  stats,
  actions,
  hasCandidates,
  listNeedsScrollHint,
  emptyMessage,
  pagination,
  statusItems,
  errors,
  children,
  onToggle,
}: TeamSourceCollectionScreeningPanelProps) {
  const className = [
    panelFrameStyles.workflowSourceCollectionDetails,
    focused ? panelFrameStyles.sourceCollectionFocusedPanel : "",
  ].filter(Boolean).join(" ");

  return (
    <details
      id="source-collection-screening-panel"
      className={className}
      open={open}
      onToggle={onToggle}
      tabIndex={-1}
    >
      <summary>
        <span>{lang === "zh" ? "资料提炼复核" : "Source review"}</span>
        <small>{rangeText}</small>
      </summary>
      {filterBar}
      <div id="source-collection-screening-stats" className={styles.workflowSourceQualityStats}>
        {stats.map((stat) => (
          <span key={stat.key}>
            {stat.label} <strong>{stat.value}</strong>
          </span>
        ))}
      </div>
      <div className={styles.sourceCollectionPanelActions}>{actions}</div>
      {hasCandidates ? (
        <div
          className={styles.sourceCollectionScreeningListShell}
          role="region"
          tabIndex={0}
          aria-label={lang === "zh" ? "资料提炼复核候选列表，可向下滚动查看更多" : "Source review candidate list, scroll for more"}
        >
          <div className={`${styles.workflowCandidateList} ${styles.sourceCollectionScreeningList}`}>
            {children}
          </div>
          {listNeedsScrollHint ? (
            <div className={styles.sourceCollectionScreeningScrollHint} aria-hidden="true">
              <span>{lang === "zh" ? "向下滚动查看更多本页候选" : "Scroll down for more candidates on this page"}</span>
            </div>
          ) : null}
        </div>
      ) : (
        <div className={styles.empty}>{emptyMessage}</div>
      )}
      {pagination}
      {statusItems ? (
        <div className={styles.workflowIngestionActions}>{statusItems}</div>
      ) : null}
      {errors}
    </details>
  );
}
