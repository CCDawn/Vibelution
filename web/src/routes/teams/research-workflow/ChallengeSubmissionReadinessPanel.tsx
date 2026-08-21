import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { queryKeys } from "../../../api/queryKeys";
import { fetchChallengeSubmissionReadiness } from "../../../api/teamExperiment";
import { exportResearchDeliverables } from "../../../api/teamResearchOps";
import type {
  ChallengeDeliverablesInspection,
  ChallengeSubmissionReadiness,
} from "../../../api/types/challengeCup";
import { VButton, VStateSurface, VStatusChip } from "../../../components/vui";
import styles from "./ChallengeSubmissionReadinessPanel.styles";

export type ChallengeSubmissionReadinessPanelProps = {
  teamId: string;
  lang?: "zh" | "en";
  onOpenQuestion: (questionId: string) => void;
};

const submissionArtifactLabels: Record<string, { zh: string; en: string }> = {
  full_catalog_results: { zh: "125 题结果包", en: "125-question results" },
  deep_experiment_suite: { zh: "两个深实验包", en: "Two deep experiment packages" },
  technical_proposal_pdf: { zh: "20 页以内技术方案 PDF", en: "Technical proposal PDF (20 pages max)" },
  demo_video: { zh: "10 分钟以内演示视频", en: "Demo video (10 minutes max)" },
  test_api: { zh: "稳定测试 API", en: "Stable test API" },
  source_code: { zh: "源码与复现说明", en: "Source and reproduction notes" },
};

const submissionBlockerLabels: Record<string, { zh: string; en: string }> = {
  full_catalog_results_incomplete: { zh: "125 题结果仍有未完成项", en: "Some 125-question results are incomplete" },
  deep_experiment_suite_incomplete: { zh: "深实验仍有未完成项", en: "Some deep experiments are incomplete" },
  technical_proposal_pdf_not_packaged: { zh: "技术方案 PDF 尚未确认", en: "Technical proposal PDF is not confirmed" },
  test_api_not_packaged: { zh: "测试 API 尚未确认", en: "Test API is not confirmed" },
  source_code_not_packaged: { zh: "源码提交包尚未确认", en: "Source package is not confirmed" },
  submission_direction_requirements_not_captured: { zh: "方向专属提交要求尚未核对", en: "Direction-specific requirements are not confirmed" },
};

function submissionActionLabel(action: { kind: string; target: string }, zh: boolean): string {
  if (action.kind === "repair" && action.target === "full-catalog-results") return zh ? "修复缺失结果" : "Fix missing results";
  if (action.kind === "repair" && action.target === "deep-experiment-suite") return zh ? "修复深实验" : "Fix deep experiment";
  return zh ? "检查交付材料" : "Inspect deliverables";
}

function localizedArtifactLabel(key: string, _fallback: string, zh: boolean): string {
  return submissionArtifactLabels[key]?.[zh ? "zh" : "en"] ?? (zh ? "提交材料" : "Submission item");
}

function localizedBlockerLabel(code: string, _fallback: string, zh: boolean): string {
  return submissionBlockerLabels[code]?.[zh ? "zh" : "en"] ?? (zh ? "待处理阻塞项" : "Pending blocker");
}

export function ChallengeSubmissionReadinessPanel({
  teamId,
  lang = "zh",
  onOpenQuestion,
}: ChallengeSubmissionReadinessPanelProps) {
  const zh = lang === "zh";
  const submissionReadinessQuery = useQuery({
    queryKey: queryKeys.challengeSubmissionReadiness(teamId),
    queryFn: () => fetchChallengeSubmissionReadiness<ChallengeSubmissionReadiness>(teamId),
    enabled: Boolean(teamId.trim()),
    staleTime: 30_000,
  });
  const [deliverablesInspection, setDeliverablesInspection] = useState<ChallengeDeliverablesInspection | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  async function inspectSubmissionDeliverables(): Promise<ChallengeDeliverablesInspection> {
    return exportResearchDeliverables<ChallengeDeliverablesInspection>(teamId, { requestedByAgent: "Challenge Cup Delivery" });
  }
  const exportMutation = useMutation({
    mutationFn: inspectSubmissionDeliverables,
    onSuccess: (result) => {
      setExportError(null);
      setDeliverablesInspection(result);
    },
    onError: (reason: unknown) => {
      setExportError(reason instanceof Error ? reason.message : String(reason));
    },
  });
  const submissionReadiness = submissionReadinessQuery.data;
  const submissionBlocker = submissionReadiness?.blockers[0];
  const submissionAction = submissionBlocker?.action ?? {
    kind: "inspect",
    target: "submission-package",
    label: zh ? "检查交付材料" : "Inspect deliverables",
  };
  const submissionActionPending = exportMutation.isPending || submissionReadinessQuery.isPending;
  const runSubmissionAction = () => {
    if (submissionAction.kind === "repair" && submissionAction.questionId) {
      onOpenQuestion(submissionAction.questionId);
      return;
    }
    setExportError(null);
    exportMutation.mutate();
  };

  if (submissionReadinessQuery.isPending) {
    return <VStateSurface tone="loading" title={zh ? "读取提交包就绪状态" : "Loading submission readiness"} className={styles.fill} />;
  }
  if (submissionReadinessQuery.isError || !submissionReadiness) {
    return (
      <VStateSurface
        tone="error"
        title={zh ? "提交包状态不可用" : "Submission readiness unavailable"}
        className={styles.fill}
        actions={<VButton type="button" variant="secondary" onClick={() => void submissionReadinessQuery.refetch()}>{zh ? "重试" : "Retry"}</VButton>}
      />
    );
  }
  return (
    <section className={styles.submissionReadiness} aria-label={zh ? "挑战杯提交包就绪状态" : "Challenge Cup submission readiness"} data-vui="challenge-submission-readiness">
      <div className={styles.sectionHeader}>
        <div>
          <strong>{zh ? "提交包" : "Submission package"}</strong>
          <div className={styles.submissionSummary}>
            {zh ? `${submissionReadiness.readyCount}/${submissionReadiness.requiredCount} 项必需材料就绪` : `${submissionReadiness.readyCount}/${submissionReadiness.requiredCount} required items ready`}
          </div>
        </div>
        <VStatusChip tone={submissionReadiness.status === "ready" ? "success" : "warning"}>
          {submissionReadiness.status === "ready" ? (zh ? "可提交" : "Ready") : (zh ? `${submissionReadiness.blockerCount} 项待处理` : `${submissionReadiness.blockerCount} blockers`)}
        </VStatusChip>
      </div>
      <div className={styles.submissionGrid}>
        {submissionReadiness.artifacts.map((artifact) => (
          <div className={styles.submissionItem} key={artifact.key}>
            <span className={styles.submissionItemLabel}>{localizedArtifactLabel(artifact.key, artifact.label, zh)}</span>
            <VStatusChip tone={artifact.status === "ready" ? "success" : artifact.status === "optional" ? "neutral" : "warning"}>
              {artifact.status === "ready" ? (zh ? "已就绪" : "Ready") : artifact.status === "optional" ? (zh ? "可选" : "Optional") : (zh ? "待处理" : "Blocked")}
            </VStatusChip>
          </div>
        ))}
      </div>
      <div className={styles.submissionActionRow}>
        <VButton type="button" variant="primary" isPending={submissionActionPending} isDisabled={submissionActionPending} onClick={runSubmissionAction}>
          {submissionActionLabel(submissionAction, zh)}
        </VButton>
        <VButton type="button" variant="ghost" onClick={() => void submissionReadinessQuery.refetch()}>{zh ? "刷新" : "Refresh"}</VButton>
      </div>
      {exportError ? (
        <div
          className="rounded border border-[color-mix(in_srgb,var(--state-error)_35%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-error)_8%,transparent)] px-2 py-1.5 [font-size:var(--vui-font-2xs)] text-[var(--state-error)]"
          data-testid="submission-export-error"
          role="alert"
        >
          {zh ? `交付材料导出失败：${exportError}，请重试。` : `Deliverables export failed: ${exportError}. Retry the inspection.`}
        </div>
      ) : null}
      {deliverablesInspection ? (
        <div className={styles.submissionSummary} role="status">
          {zh ? `交付材料检查：${deliverablesInspection.status === "ready" ? "可用" : "有阻塞"}，${deliverablesInspection.blockers.length} 项阻塞` : `Deliverables inspection: ${deliverablesInspection.status === "ready" ? "ready" : "blocked"}, ${deliverablesInspection.blockers.length} blockers`}
        </div>
      ) : null}
      {submissionReadiness.blockers.length > 0 ? (
        <details className={styles.submissionDetails}>
          <summary>{zh ? "查看阻塞项" : "View blockers"}</summary>
          <ul className={styles.submissionBlockers}>
            {submissionReadiness.blockers.map((blocker) => <li key={blocker.code}>{localizedBlockerLabel(blocker.code, blocker.label, zh)}</li>)}
          </ul>
        </details>
      ) : null}
    </section>
  );
}
