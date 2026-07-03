import { type ReactNode } from "react";

import { VNativeButton, VNativeSelect } from "../components/vui";
import styles from "./TeamsRoute.styles";

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
  assignments: TeamSourceCollectionFindingAssignment[];
  queries: TeamSourceCollectionFindingQuery[];
  storageActions: ReactNode;
  onRunChange: (runId: string) => void;
  onAssignmentSelect: (assignmentId: string) => void;
};

export function TeamSourceCollectionFindingDetailsPanel({
  lang,
  selectedRunId,
  runs,
  assignments,
  queries,
  storageActions,
  onRunChange,
  onAssignmentSelect,
}: TeamSourceCollectionFindingDetailsPanelProps) {
  const isZh = lang === "zh";

  return (
    <>
      <div className={styles.workflowSourceCollectionRuns}>
        <label>
          <span>{isZh ? "最近批次" : "Recent runs"}</span>
          <VNativeSelect
            value={selectedRunId}
            onChange={(event) => onRunChange(event.target.value)}
            disabled={!runs.length}
          >
            {runs.length ? (
              runs.map((run) => (
                <option key={run.id} value={run.id}>
                  {run.label}
                </option>
              ))
            ) : (
              <option value="">{isZh ? "暂无批次" : "No runs"}</option>
            )}
          </VNativeSelect>
        </label>
      </div>
      {storageActions}
      <details className={styles.workflowSourceCollectionDetails}>
        <summary>
          <span>{isZh ? "查询与分工详情" : "Query and assignment details"}</span>
        </summary>
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
          <div className={styles.empty}>{isZh ? "还没有生成 Agent 分工。" : "No Agent assignments yet."}</div>
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
      </details>
    </>
  );
}
