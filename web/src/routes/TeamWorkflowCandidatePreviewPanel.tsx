import { type ReactNode } from "react";

import { VButton } from "../components/vui";
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
        <strong>{lang === "zh" ? "候选仓库" : "Candidates"}</strong>
        <div className={styles.workflowCandidateListActions}>
          <VButton
            type="button"
            variant="secondary"
            isDisabled={!canOpenLibrary}
            tooltip={lang === "zh" ? "打开完整候选库" : "Open the full candidate library"}
            onPress={onOpenLibrary}
          >
            {lang === "zh" ? "候选库" : "Library"}
          </VButton>
          <VButton
            type="button"
            variant="primary"
            isDisabled={reviewDisabled}
            disabledReason={reviewDisabled ? reviewTitle : undefined}
            tooltip={reviewDisabled ? undefined : reviewTitle}
            onPress={onOpenReview}
          >
            {lang === "zh" ? "提炼复核" : "Review"}
          </VButton>
        </div>
      </div>
      <div
        className={styles.workflowCandidateListScroll}
        id="research-workflow-candidates"
        role="region"
        tabIndex={0}
        aria-label={lang === "zh" ? "科研流程候选仓库" : "Research workflow candidates"}
      >
        <div className={styles.workflowCandidateList}>
          {items.map(({ id, ...item }) => (
            <TeamCandidateCard key={id} {...item} />
          ))}
        </div>
        {listNeedsScrollHint ? <span className={styles.workflowCandidateListScrollCue} aria-hidden="true" /> : null}
      </div>
    </div>
  );
}
