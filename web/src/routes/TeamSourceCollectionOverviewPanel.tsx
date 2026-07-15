import { type ReactNode } from "react";

import {
  TeamSourceCollectionFindingDetailsPanel,
  type TeamSourceCollectionFindingAssignment,
  type TeamSourceCollectionFindingQuery,
  type TeamSourceCollectionFindingRunOption,
} from "./TeamSourceCollectionFindingDetailsPanel";
import {
  TeamSourceCollectionRunSettingsPanel,
  type TeamSourceCollectionRunSettingsDraft,
} from "./TeamSourceCollectionRunSettingsPanel";
import styles from "./TeamSourceCollectionOverviewPanel.styles";

type TeamSourceCollectionOverviewLang = "zh" | "en";

export type TeamSourceCollectionOverviewStat = {
  key: string;
  label: string;
  value: string;
};

export type TeamSourceCollectionOverviewPlan = {
  planId: string;
  seeds: string;
  promptCache: string;
  boundary: string;
};

export type TeamSourceCollectionOverviewResult = {
  title: string;
  detail: string;
};

type TeamSourceCollectionOverviewPanelProps = {
  lang: TeamSourceCollectionOverviewLang;
  title: string;
  summary: string;
  statusLabel: string;
  statusClassName: string;
  draft: TeamSourceCollectionRunSettingsDraft;
  modeFields: ReactNode;
  canStart: boolean;
  startPending: boolean;
  selectedRunId: string;
  runs: TeamSourceCollectionFindingRunOption[];
  stats: TeamSourceCollectionOverviewStat[];
  assignments: TeamSourceCollectionFindingAssignment[];
  assignmentEmptyMessage: string;
  queries: TeamSourceCollectionFindingQuery[];
  phaseCloseGate?: ReactNode;
  storageActions: ReactNode;
  plan: TeamSourceCollectionOverviewPlan | null;
  manualWriteback: ReactNode;
  boundaryItems: string[];
  errorMessages: string[];
  result: TeamSourceCollectionOverviewResult | null;
  onDraftChange: (patch: Partial<TeamSourceCollectionRunSettingsDraft>) => void;
  onStart: () => void;
  onRunChange: (runId: string) => void;
  onAssignmentSelect: (assignmentId: string) => void;
};

export function TeamSourceCollectionOverviewPanel({
  lang,
  title,
  summary,
  statusLabel,
  statusClassName,
  draft,
  modeFields,
  canStart,
  startPending,
  selectedRunId,
  runs,
  stats,
  assignments,
  assignmentEmptyMessage,
  queries,
  phaseCloseGate,
  storageActions,
  plan,
  manualWriteback,
  boundaryItems,
  errorMessages,
  result,
  onDraftChange,
  onStart,
  onRunChange,
  onAssignmentSelect,
}: TeamSourceCollectionOverviewPanelProps) {
  const isZh = lang === "zh";

  return (
    <div className={styles.workflowSourceCollectionPanel} id="research-workflow-source-collection">
      <div className={styles.workflowIngestionHeader}>
        <div>
          <strong>{title}</strong>
          <span>{summary}</span>
        </div>
        <span className={`${styles.workflowTag} ${statusClassName}`}>{statusLabel}</span>
      </div>
      <TeamSourceCollectionRunSettingsPanel
        lang={lang}
        draft={draft}
        modeFields={modeFields}
        open
        wrapInDetails={false}
        canStart={canStart}
        startPending={startPending}
        onDraftChange={onDraftChange}
        onSubmit={onStart}
      />
      <TeamSourceCollectionFindingDetailsPanel
        lang={lang}
        selectedRunId={selectedRunId}
        runs={runs}
        runStats={
          <div className={styles.workflowSourceCollectionStats}>
            {stats.map((stat) => (
              <span key={stat.key}>
                {stat.label} <strong>{stat.value}</strong>
              </span>
            ))}
          </div>
        }
        assignments={assignments}
        assignmentEmptyMessage={assignmentEmptyMessage}
        queries={queries}
        storageActions={storageActions}
        wrapInDetails={false}
        onRunChange={onRunChange}
        onAssignmentSelect={onAssignmentSelect}
      />
      {phaseCloseGate}
      {plan ? (
        <div className={styles.workflowSourceCollectionPlan}>
          <div>
            <span>plan</span>
            <strong>{plan.planId}</strong>
          </div>
          <div>
            <span>{isZh ? "seeds" : "seeds"}</span>
            <strong>{plan.seeds}</strong>
          </div>
          <div>
            <span>KV</span>
            <strong>{plan.promptCache}</strong>
          </div>
          <div>
            <span>{isZh ? "边界" : "boundary"}</span>
            <strong>{plan.boundary}</strong>
          </div>
        </div>
      ) : null}
      {manualWriteback}
      <div className={styles.workflowIngestionBoundary}>
        {boundaryItems.map((item) => (
          <span key={item}>{item}</span>
        ))}
      </div>
      {errorMessages.map((message) => (
        <div key={message} className={styles.messageError}>{message}</div>
      ))}
      {result ? (
        <div className={styles.messageResult}>
          <strong>{result.title}</strong>
          <span>{result.detail}</span>
        </div>
      ) : null}
    </div>
  );
}
