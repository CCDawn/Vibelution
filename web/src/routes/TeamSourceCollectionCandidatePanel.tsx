import { type ReactNode, type SyntheticEvent } from "react";

import { PersistedHeightListShell } from "../components/layout/PersistedHeightListShell";
import panelFrameStyles from "./TeamSourceCollectionPanelFrame.styles";
import styles from "./TeamSourceCollectionCandidatePanel.styles";
import {
  TEAM_SOURCE_COLLECTION_CANDIDATES_HEIGHT_PANE,
  TEAM_SOURCE_COLLECTION_LAYOUT_ID,
} from "./teamSourceCollectionListHeights";

export type TeamSourceCollectionCandidatePanelStat = {
  key: string;
  label: ReactNode;
  value: ReactNode;
};

type TeamSourceCollectionCandidatePanelProps = {
  lang: "zh" | "en";
  focused: boolean;
  open: boolean;
  rangeText: ReactNode;
  filterBar: ReactNode;
  stats: TeamSourceCollectionCandidatePanelStat[];
  loading: boolean;
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
  focused,
  open,
  rangeText,
  filterBar,
  stats,
  loading,
  hasCandidates,
  listNeedsScrollHint,
  emptyMessage,
  recoveryPanel,
  pagination,
  children,
  onToggle,
}: TeamSourceCollectionCandidatePanelProps) {
  const className = [
    panelFrameStyles.workflowSourceCollectionDetails,
    focused ? panelFrameStyles.sourceCollectionFocusedPanel : "",
  ].filter(Boolean).join(" ");

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
        <PersistedHeightListShell
          layoutId={TEAM_SOURCE_COLLECTION_LAYOUT_ID}
          pane={TEAM_SOURCE_COLLECTION_CANDIDATES_HEIGHT_PANE}
          label={lang === "zh" ? "调整资料提炼候选列表高度" : "Resize extracted candidate list height"}
          className={styles.sourceCollectionCandidateListShell}
          resizeHandleClassName={styles.sourceCollectionListResizeHandle}
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
        </PersistedHeightListShell>
      ) : loading && !hasCandidates ? (
        <PersistedHeightListShell
          layoutId={TEAM_SOURCE_COLLECTION_LAYOUT_ID}
          pane={TEAM_SOURCE_COLLECTION_CANDIDATES_HEIGHT_PANE}
          label={lang === "zh" ? "调整资料提炼候选列表高度" : "Resize extracted candidate list height"}
          className={styles.sourceCollectionCandidateListShell}
          resizeHandleClassName={styles.sourceCollectionListResizeHandle}
          role="region"
          tabIndex={0}
          aria-busy="true"
          aria-label={lang === "zh" ? "资料提炼候选列表正在同步" : "Extracted candidate list is syncing"}
        >
          <div className={styles.sourceCollectionCandidateSkeletonList}>
            {Array.from({ length: 4 }).map((_, index) => (
              <div key={index} className={styles.sourceCollectionCandidateSkeletonRow}>
                <span className={styles.sourceCollectionCandidateSkeletonTitle} />
                <span className={styles.sourceCollectionCandidateSkeletonMeta} />
              </div>
            ))}
          </div>
        </PersistedHeightListShell>
      ) : (
        <div className={styles.empty}>{emptyMessage}</div>
      )}
      {recoveryPanel}
      {pagination}
    </details>
  );
}
