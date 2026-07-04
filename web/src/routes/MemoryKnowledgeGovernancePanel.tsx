import { CheckCircle2, Eye } from "lucide-react";

import type { KnowledgeGovernancePlanPayload, KnowledgeGovernanceTask, KnowledgeOperationsHealthPayload } from "../api/types";
import { VButton } from "../components/vui";
import styles from "./MemoryKnowledgeGovernancePanel.styles";

export type MemoryKnowledgeGovernancePanelCopy = {
  operationsHealth: string;
  healthFindings: string;
  knowledgeBases: string;
  pendingProposals: string;
  ratingSuggestions: string;
  formalKnowledge: string;
  noIssues: string;
  governancePlan: string;
  planOnly: string;
  noDirectApply: string;
  reviewerRequired: string;
  stewardNextActions: string;
  createsKnowledgeItem: string;
  governanceTasks: string;
  teamKnowledgeDomain: string;
  traceability: string;
  yes: string;
  no: string;
};

type MemoryKnowledgeGovernancePanelProps = {
  copy: MemoryKnowledgeGovernancePanelCopy;
  operationsHealth: KnowledgeOperationsHealthPayload | undefined;
  governancePlan: KnowledgeGovernancePlanPayload | undefined;
  governanceTasks: KnowledgeGovernanceTask[];
  operationsPending: boolean;
  governanceTasksPending: boolean;
  openGovernanceTaskCount: number;
  onTraceTarget: (targetId: string) => void;
};

export function MemoryKnowledgeGovernancePanel({
  copy,
  operationsHealth,
  governancePlan,
  governanceTasks,
  operationsPending,
  governanceTasksPending,
  openGovernanceTaskCount,
  onTraceTarget,
}: MemoryKnowledgeGovernancePanelProps) {
  return (
    <>
      <section className={styles.managementPanel}>
        <div className={styles.managementHeader}>
          <div>
            <p className={styles.panelEyebrow}>{copy.operationsHealth}</p>
            <h2>{copy.healthFindings}</h2>
          </div>
          <span className={styles.countPill}>{operationsHealth?.summary.findingCount ?? 0}</span>
        </div>
        <div className={styles.healthStrip}>
          <span>{copy.knowledgeBases}: {operationsHealth?.summary.knowledgeBaseCount ?? 0}</span>
          <span>{copy.pendingProposals}: {operationsHealth?.summary.pendingProposalCount ?? 0}</span>
          <span>{copy.ratingSuggestions}: {operationsHealth?.summary.pendingRatingSuggestionCount ?? 0}</span>
          <span>{copy.formalKnowledge}: {operationsHealth?.summary.unratedItemCount ?? 0}</span>
        </div>
        <div className={styles.knowledgeProposalList}>
          {(operationsHealth?.findings ?? []).slice(0, 8).map((finding) => (
            <section key={finding.findingId} className={styles.knowledgeRow}>
              <span className={styles.statusPill}>{finding.severity}</span>
              <strong>{finding.findingType}</strong>
              <span>{finding.message}</span>
              <small>{finding.knowledgeBaseName} · {finding.count}</small>
              <small>{finding.nextReviewTargetIds.slice(0, 2).join(", ") || "-"}</small>
            </section>
          ))}
          {!operationsPending && !(operationsHealth?.findings ?? []).length ? (
            <section className={styles.emptyDetail}>
              <CheckCircle2 size={20} />
              <strong>{copy.noIssues}</strong>
            </section>
          ) : null}
        </div>
      </section>

      <section className={styles.managementPanel}>
        <div className={styles.managementHeader}>
          <div>
            <p className={styles.panelEyebrow}>{copy.governancePlan}</p>
            <h2>{copy.planOnly}</h2>
          </div>
          <span className={styles.statusPillMuted}>{governancePlan?.mode ?? "recommendations_only"}</span>
        </div>
        <div className={styles.healthStrip}>
          <span>{copy.noDirectApply}: {governancePlan?.operatingBoundary.canDirectlyApplyKnowledge ? copy.yes : copy.no}</span>
          <span>{copy.reviewerRequired}: {governancePlan?.operatingBoundary.formalKnowledgeRequiresReviewer ? copy.yes : copy.no}</span>
          <span>{copy.stewardNextActions}: {governancePlan?.summary.actionCount ?? 0}</span>
        </div>
        <div className={styles.knowledgeProposalList}>
          {(governancePlan?.actions ?? []).slice(0, 8).map((action) => (
            <section key={action.planActionId} className={styles.knowledgeRow}>
              <span className={styles.statusPill}>{action.priority}</span>
              <strong>{action.title}</strong>
              <span>{action.nextStep}</span>
              <small>{action.kind} · {action.recommendedTool}</small>
              <small>{action.mutatesFormalKnowledge ? copy.createsKnowledgeItem : copy.planOnly}</small>
            </section>
          ))}
          {!operationsPending && !(governancePlan?.actions ?? []).length ? (
            <section className={styles.emptyDetail}>
              <CheckCircle2 size={20} />
              <strong>{copy.noIssues}</strong>
            </section>
          ) : null}
        </div>
      </section>

      <section className={styles.managementPanel}>
        <div className={styles.managementHeader}>
          <div>
            <p className={styles.panelEyebrow}>{copy.governanceTasks}</p>
            <h2>{copy.teamKnowledgeDomain}</h2>
          </div>
          <span className={styles.countPill}>{openGovernanceTaskCount}</span>
        </div>
        <div className={styles.knowledgeProposalList}>
          {governanceTasks.slice(0, 8).map((task) => (
            <section key={task.taskId} className={styles.knowledgeRow}>
              <span className={styles.statusPill}>{task.priority}</span>
              <strong>{task.title}</strong>
              <span>{task.summary || task.targetId}</span>
              <small>{task.taskType} · {task.targetStatus} · {task.knowledgeBaseName}</small>
              <VButton type="button" className={styles.detailActionButton} onClick={() => onTraceTarget(task.targetId)}>
                <Eye size={14} />
                <span>{copy.traceability}</span>
              </VButton>
            </section>
          ))}
          {!governanceTasksPending && !governanceTasks.length ? (
            <section className={styles.emptyDetail}>
              <CheckCircle2 size={20} />
              <strong>{copy.noIssues}</strong>
            </section>
          ) : null}
        </div>
      </section>
    </>
  );
}
