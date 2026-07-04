import { Sparkles, Trash2 } from "lucide-react";

import type { EvolutionProposalDetail } from "../api/types";
import { VNativeButton } from "../components/vui";
import type { TranslationKey } from "../i18n/dictionary";
import styles from "./EvolutionProposalActionBandsPanel.styles";

export type EvolutionProposalActionBandsPanelLabels = {
  t: (key: TranslationKey) => string;
  proposalActionLabel: (action: string) => string;
};

export type EvolutionProposalActionBandsPanelProps = {
  proposal: EvolutionProposalDetail;
  labels: EvolutionProposalActionBandsPanelLabels;
  runLocked: boolean;
  actionFeedback: string;
  actionError: string;
  actionPending: boolean;
  deleteProposalError: string;
  deleteProposalPending: boolean;
  onRunAction: (sourceRun: string, action: string) => void;
  onDeleteProposal: (sourceRun: string) => void;
};

function formatAvailableActions(actions: string[] | undefined, proposalActionLabel: (action: string) => string) {
  if (!actions || actions.length === 0) {
    return "--";
  }
  return actions.map((action) => proposalActionLabel(action)).join(", ");
}

function renderReviewList(lines: string[]) {
  if (lines.length === 0) {
    return <p>--</p>;
  }
  return (
    <ul className={styles.detailList}>
      {lines.map((line) => (
        <li key={line}>{line}</li>
      ))}
    </ul>
  );
}

export function EvolutionProposalActionBandsPanel({
  proposal,
  labels,
  runLocked,
  actionFeedback,
  actionError,
  actionPending,
  deleteProposalError,
  deleteProposalPending,
  onRunAction,
  onDeleteProposal,
}: EvolutionProposalActionBandsPanelProps) {
  const { t, proposalActionLabel } = labels;

  return (
    <>
      <div className={styles.detailSection}>
        <h3>{t("availableActions")}</h3>
        <p>{formatAvailableActions(proposal.availableActions, proposalActionLabel)}</p>
        {proposal.availableActions.length > 0 ? (
          <div className={styles.actionRow}>
            {proposal.availableActions.map((action) => (
              <VNativeButton
                key={action}
                type="button"
                className={styles.inlineAction}
                disabled={runLocked || actionPending}
                onClick={() => onRunAction(proposal.sourceRun, action)}
              >
                <Sparkles size={15} />
                {proposalActionLabel(action)}
              </VNativeButton>
            ))}
          </div>
        ) : null}
        {actionFeedback ? <p className={styles.feedbackText}>{actionFeedback}</p> : null}
        {actionError ? <p className={styles.errorText}>{actionError}</p> : null}
      </div>

      <div className={styles.detailSection}>
        <h3>{t("deleteAndCleanup")}</h3>
        <div className={styles.relatedList}>
          <article className={styles.relatedRow}>
            <strong>{proposal.canDelete ? t("deletionAllowed") : t("deletionBlocked")}</strong>
            <span>{proposal.canDelete ? t("deleteProposal") : proposal.deleteBlockReason || "--"}</span>
          </article>
        </div>
        <p>{proposal.review.deleteImpact}</p>
        {proposal.review.evidenceNotes.length > 0 ? renderReviewList(proposal.review.evidenceNotes) : null}
        <div className={styles.actionRow}>
          <VNativeButton
            type="button"
            className={styles.inlineAction}
            disabled={!proposal.canDelete || deleteProposalPending}
            onClick={() => onDeleteProposal(proposal.sourceRun)}
          >
            <Trash2 size={15} />
            {t("deleteProposal")}
          </VNativeButton>
        </div>
        {deleteProposalError ? <p className={styles.errorText}>{deleteProposalError}</p> : null}
      </div>
    </>
  );
}
