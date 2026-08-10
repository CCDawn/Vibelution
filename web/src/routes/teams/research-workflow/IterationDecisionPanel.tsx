/**
 * Structured iteration-decision surface for the research workflow drawer.
 *
 * Wraps the run-level `iteration_decision` command (service.apply_command →
 * apply_iteration_decision): exactly the five structured kinds, no free-form
 * routing strings. The backend owns lineage/forks/budget; this panel only
 * renders facts and submits decisions.
 */
import { useMemo, useState } from "react";

import { postResearchWorkflowCommand } from "../../../api/researchWorkflow";
import type { WorkflowRunRecord } from "../../../api/researchWorkflow";
import type {
  IterationDecisionKind,
} from "../../../api/types/researchWorkflow";
import {
  VButton,
  VEmptyState,
  VInput,
  VPanelHeader,
  VSelect,
  VStateSurface,
  VSurface,
  VTextarea,
} from "../../../components/vui";
import styles from "./IterationDecisionPanel.styles";

export type IterationDecisionPanelProps = {
  runId: string;
  run: WorkflowRunRecord | null;
  busy: boolean;
  onRefresh: () => void;
};

export const DECISION_KINDS: Array<{ id: IterationDecisionKind; label: string }> = [
  { id: "rerun_same_protocol", label: "同协议重跑（rerun）" },
  { id: "revise_protocol", label: "修订协议（revise，创建分支）" },
  { id: "promote_candidate", label: "晋升候选（promote）" },
  { id: "rollback_candidate", label: "回滚候选（rollback）" },
  { id: "stop", label: "停止并打包（stop）" },
];

const KIND_REQUIRES_CANDIDATE: IterationDecisionKind[] = [
  "promote_candidate",
  "rollback_candidate",
];

export function buildIterationDecisionPayload(input: {
  decisionKind: IterationDecisionKind | "";
  reason: string;
  terminalReason?: string;
  candidateRef?: string;
}): Record<string, unknown> | null {
  const { decisionKind, reason } = input;
  if (!decisionKind || !reason.trim()) return null;
  const payload: Record<string, unknown> = {
    decisionKind,
    reason: reason.trim(),
    decidedBy: "operator",
  };
  if (decisionKind === "stop" && input.terminalReason?.trim()) {
    payload.terminalReason = input.terminalReason.trim();
  }
  if (KIND_REQUIRES_CANDIDATE.includes(decisionKind) && input.candidateRef?.trim()) {
    payload.selectedCandidateRef = input.candidateRef.trim();
  }
  return payload;
}

function decisionKindLabel(kind: string): string {
  return DECISION_KINDS.find((item) => item.id === kind)?.label || kind || "—";
}

function shortId(value: string | undefined): string {
  if (!value) return "";
  return value.length > 20 ? `${value.slice(0, 20)}…` : value;
}

export function IterationDecisionPanel({
  runId,
  run,
  busy,
  onRefresh,
}: IterationDecisionPanelProps) {
  const [decisionKind, setDecisionKind] = useState<IterationDecisionKind | "">("");
  const [reason, setReason] = useState("");
  const [terminalReason, setTerminalReason] = useState("");
  const [candidateRef, setCandidateRef] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const decisions = useMemo(() => run?.iterationDecisions ?? [], [run]);
  const atIterationDecision = (run?.runtimeCurrentNodeIds ?? []).includes("iteration_decision");
  const hasPendingHumanTask = Boolean((run?.humanTasks ?? []).some((t) => String(t.status) === "pending"));

  if (!run) {
    return (
      <VSurface tone="panel" className={styles.panel}>
        <VEmptyState title="迭代决策" className={styles.emptyState}>
          创建运行后，在迭代决策节点提交结构化决策。
        </VEmptyState>
      </VSurface>
    );
  }

  const canSubmit =
    decisionKind !== ""
    && reason.trim().length > 0
    && !submitting
    && !busy;

  const onSubmit = async () => {
    if (!canSubmit || !decisionKind) return;
    const payload = buildIterationDecisionPayload({
      decisionKind,
      reason,
      terminalReason,
      candidateRef,
    });
    if (!payload) return;
    setSubmitError(null);
    setSubmitting(true);
    try {
      await postResearchWorkflowCommand(runId, {
        command: "iteration_decision",
        idempotencyKey: `wf-iter-${crypto.randomUUID()}`,
        payload,
      });
      setReason("");
      setTerminalReason("");
      setCandidateRef("");
      onRefresh();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <VSurface tone="panel" className={styles.panel} data-vui="iteration-decision-panel">
      <VPanelHeader title="迭代决策" headingLevel={3} />

      {!atIterationDecision ? (
        <div
          className={styles.notice}
          role="status"
        >
          流程当前不在迭代决策节点；决策将在引擎到达决策门后生效。
        </div>
      ) : null}
      {hasPendingHumanTask ? (
        <div
          className={styles.notice}
          role="status"
        >
          存在待处理人工任务；stop 决策会因未决任务被后端拒绝。
        </div>
      ) : null}

      <div className={styles.formGrid}>
        <label className={styles.fieldLabel}>
          决策类型
          <VSelect
            density="compact"
            aria-label="决策类型"
            placeholder="选择结构化决策"
            selectedKey={decisionKind || null}
            options={DECISION_KINDS.map((item) => ({ id: item.id, label: item.label }))}
            onSelectionChange={(key) => {
              setDecisionKind((key == null ? "" : String(key)) as IterationDecisionKind | "");
            }}
          />
        </label>
        <label className={styles.fieldLabel}>
          决策理由
          <VTextarea
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="说明该决策的评估依据与理由"
            rows={3}
          />
        </label>
        {decisionKind === "stop" ? (
          <label className={styles.fieldLabel}>
            终止原因（terminalReason，必需）
            <VInput
              value={terminalReason}
              onChange={(event) => setTerminalReason(event.target.value)}
              placeholder="例如：enough_evidence"
            />
          </label>
        ) : null}
        {decisionKind && KIND_REQUIRES_CANDIDATE.includes(decisionKind) ? (
          <label className={styles.fieldLabel}>
            目标候选引用（可留空，缺省用基线/当前候选）
            <VInput
              value={candidateRef}
              onChange={(event) => setCandidateRef(event.target.value)}
              placeholder="candidate:…"
            />
          </label>
        ) : null}
        <VButton type="button" variant="primary" onClick={() => void onSubmit()} isDisabled={!canSubmit}>
          {submitting ? "提交中…" : "提交决策"}
        </VButton>
      </div>

      {submitError ? (
        <div
          className={styles.notice}
          role="alert"
        >
          决策提交失败：{submitError}
        </div>
      ) : null}

      <div className={styles.sectionGrid}>
        <div className={styles.sectionLabel}>
          决策历史（{decisions.length}）
        </div>
        {decisions.length === 0 ? (
          <p className={styles.emptyText}>暂无决策记录</p>
        ) : (
          <ul className={styles.list}>
            {decisions.map((item) => (
              <li
                key={String(item.decisionId || item.idempotencyKey)}
                className={styles.listItem}
              >
                <div className={styles.listItemTitle}>
                  {decisionKindLabel(String(item.decisionKind))}
                  {item.iterationAttempt ? ` · 第 ${item.iterationAttempt} 次迭代` : ""}
                </div>
                <div className={styles.listItemMeta}>
                  {shortId(item.reason || "—")}
                  {item.selectedCandidateRef ? ` · ${item.selectedCandidateRef}` : ""}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {run.status === "succeeded" ? (
        <div
          className={styles.notice}
          role="status"
        >
          运行已完成：{run.completionKind || "—"}
          {run.terminalReason ? ` · ${run.terminalReason}` : ""}
        </div>
      ) : null}

      {run.status === "blocked" ? (
        <VStateSurface tone="error" title="运行已阻塞" className={styles.autoHeight}>
          {run.blockedReason || "未知阻塞原因"}
        </VStateSurface>
      ) : null}
    </VSurface>
  );
}
