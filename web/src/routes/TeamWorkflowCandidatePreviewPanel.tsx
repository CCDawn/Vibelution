import { type ReactNode } from "react";

import { VNativeButton } from "../components/vui";
import {
  TeamCandidateCard,
  type TeamCandidateCardProps,
} from "../components/vui/product/team-management";
import styles from "./TeamWorkflowCandidatePreviewPanel.styles";

export type TeamWorkflowCandidatePreviewItem = TeamCandidateCardProps & {
  id: string;
};

type TeamWorkflowCandidatePreviewPanelProps = {
  lang: "zh" | "en";
  items: TeamWorkflowCandidatePreviewItem[];
  canOpenLibrary: boolean;
  reviewDisabled: boolean;
  reviewTitle: string;
  listNeedsScrollHint: boolean;
  emptyMessage: ReactNode;
  onOpenLibrary: () => void;
  onOpenReview: () => void;
};

export function TeamWorkflowCandidatePreviewPanel({
  lang,
  items,
  canOpenLibrary,
  reviewDisabled,
  reviewTitle,
  listNeedsScrollHint,
  emptyMessage,
  onOpenLibrary,
  onOpenReview,
}: TeamWorkflowCandidatePreviewPanelProps) {
  if (!items.length) {
    return <div className={styles.empty}>{emptyMessage}</div>;
  }

  return (
    <div className={styles.workflowCandidateListPanel}>
      <div className={styles.workflowCandidateListHeader}>
        <div>
          <strong>{lang === "zh" ? "候选仓库预览" : "Candidate library preview"}</strong>
          <span>
            {lang === "zh"
              ? `当前显示 ${items.length} 条候选；完整筛选、分页和详情在资料工作台中处理。`
              : `${items.length} candidates shown; use the source workspace for filtering, paging, and details.`}
          </span>
        </div>
        <div>
          <VNativeButton type="button" onClick={onOpenLibrary} disabled={!canOpenLibrary}>
            {lang === "zh" ? "查看完整候选库" : "Full library"}
          </VNativeButton>
          <VNativeButton
            type="button"
            onClick={onOpenReview}
            disabled={reviewDisabled}
            title={reviewTitle}
          >
            {lang === "zh" ? "进入资料提炼复核" : "Open review"}
          </VNativeButton>
        </div>
      </div>
      <div
        className={styles.workflowCandidateListScroll}
        id="research-workflow-candidates"
        role="region"
        tabIndex={0}
        aria-label={lang === "zh" ? "科研流程候选仓库预览，可向下滚动查看更多" : "Research workflow candidate preview, scroll for more"}
      >
        <div className={styles.workflowCandidateList}>
          {items.map(({ id, ...item }) => (
            <TeamCandidateCard key={id} {...item} />
          ))}
        </div>
        {listNeedsScrollHint ? (
          <div className={styles.workflowCandidateListScrollHint} aria-hidden="true">
            <span>{lang === "zh" ? "向下滚动查看更多候选，或打开完整候选库分页处理" : "Scroll for more candidates, or open the full paged library"}</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}
