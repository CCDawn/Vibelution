import { type ReactNode } from "react";

import { VNativeButton, VStringSelect } from "../components/vui";
import styles from "./TeamSourceCollectionFindingDetailsPanel.styles";

type TeamSourceCollectionFindingDetailsLang = "zh" | "en";

export type TeamSourceCollectionFindingRunOption = {
  id: string;
  label: string;
};

export type TeamSourceCollectionFindingAssignment = {
  id: string;
  roleLabel: string;
  statusLabel: string;
  queryCountLabel: string;
  active: boolean;
};

export type TeamSourceCollectionFindingQuery = {
  id: string;
  title: string;
  meta: string;
};

type TeamSourceCollectionFindingDetailsPanelProps = {
  lang: TeamSourceCollectionFindingDetailsLang;
  selectedRunId: string;
  runs: TeamSourceCollectionFindingRunOption[];
  runStats?: ReactNode;
  assignments: TeamSourceCollectionFindingAssignment[];
  queries: TeamSourceCollectionFindingQuery[];
  storageActions: ReactNode;
  assignmentEmptyMessage?: string;
  wrapInDetails?: boolean;
  onRunChange: (runId: string) => void;
  onAssignmentSelect: (assignmentId: string) => void;
};

export function TeamSourceCollectionFindingDetailsPanel({
  lang,
  selectedRunId,
  runs,
  runStats,
  assignments,
  queries,
  storageActions,
  assignmentEmptyMessage,
  wrapInDetails = true,
  onRunChange,
  onAssignmentSelect,
}: TeamSourceCollectionFindingDetailsPanelProps) {
  const isZh = lang === "zh";
  const detailContent = (
    <>
      {assignments.length ? (
        <div className={styles.workflowSourceCollectionAssignments}>
          {assignments.map((assignment) => (
            <VNativeButton
              key={assignment.id}
              type="button"
              className={assignment.active ? styles.workflowSourceCollectionAssignmentActive : ""}
              onClick={() => onAssignmentSelect(assignment.id)}
            >
              <strong>{assignment.roleLabel}</strong>
              <span>
                {assignment.statusLabel} · {assignment.queryCountLabel}
              </span>
            </VNativeButton>
          ))}
        </div>
      ) : (
        <div className={styles.empty}>
          {assignmentEmptyMessage ?? (isZh ? "还没有生成 Agent 分工。" : "No Agent assignments yet.")}
        </div>
      )}
      {queries.length ? (
        <div className={styles.workflowSourceCollectionQueries}>
          {queries.map((query) => (
            <span key={query.id}>
              <strong>{query.title}</strong>
              <small>{query.meta}</small>
            </span>
          ))}
        </div>
      ) : null}
    </>
  );

  return (
    <>
      <div className={styles.workflowSourceCollectionRuns}>
        <label>
          <span>{isZh ? "最近批次" : "Recent runs"}</span>
          <VStringSelect
            ariaLabel={isZh ? "批次" : "Run"}
            value={selectedRunId}
            isDisabled={!runs.length}
            onValueChange={onRunChange}
            options={
              runs.length
                ? runs.map((run) => ({ value: run.id, label: run.label }))
                : [{ value: "", label: isZh ? "暂无批次" : "No runs" }]
            }
          />
        </label>
        {runStats}
      </div>
      {storageActions}
      {wrapInDetails ? (
        <details className={styles.workflowSourceCollectionDetails}>
          <summary>
            <span>{isZh ? "查询与分工详情" : "Query and assignment details"}</span>
          </summary>
          {detailContent}
        </details>
      ) : detailContent}
    </>
  );
}
