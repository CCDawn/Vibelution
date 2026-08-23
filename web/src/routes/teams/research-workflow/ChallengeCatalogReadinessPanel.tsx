import { useQuery } from "@tanstack/react-query";

import { queryKeys } from "../../../api/queryKeys";
import { fetchChallengeCatalogReadiness } from "../../../api/teamExperiment";
import type { ChallengeCatalogReadiness } from "../../../api/types/challengeCup";
import {
  VButton,
  VEmbeddedPanel,
  VMetricStrip,
  VStateSurface,
  VStatusChip,
  type VStatusTone,
} from "../../../components/vui";
import styles from "./ChallengeCatalogReadinessPanel.styles";

export type ChallengeCatalogReadinessPanelProps = {
  teamId: string;
  lang?: "zh" | "en";
};

const EVIDENCE = [
  { id: "r0", zh: "R0 来源", en: "R0 source" },
  { id: "r1", zh: "R1 克隆", en: "R1 clone" },
  { id: "api", zh: "API", en: "API" },
  { id: "frontend", zh: "前端", en: "Frontend" },
  { id: "browser", zh: "浏览器", en: "Browser" },
] as const;

type EvidenceId = (typeof EVIDENCE)[number]["id"];

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isNonNegativeNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function isCatalogReadiness(value: unknown): value is ChallengeCatalogReadiness {
  if (!isRecord(value)) return false;
  const resultSet = value.catalogResultSet;
  const counts = isRecord(resultSet) ? resultSet.counts : undefined;
  const evidence = value.evidence;
  if (!isRecord(counts) || !isRecord(evidence)) return false;
  if (typeof value.status !== "string" || typeof value.realCampaignAllowed !== "boolean") return false;
  if (typeof value.researchAuthorizationRequired !== "boolean" || !Array.isArray(value.blockers)) return false;
  const countFields = [
    "present_count",
    "missing_count",
    "duplicate_count",
    "submission_eligible_count",
    "package_backed_count",
    "quality_approved_count",
    "human_gate_approved_count",
    "receipt_complete_count",
    "required_question_count",
  ];
  if (countFields.some((field) => !isNonNegativeNumber(counts[field]))) return false;
  if (EVIDENCE.some(({ id }) => !isRecord(evidence[id]) || typeof evidence[id]?.status !== "string")) return false;
  return true;
}

function evidenceTone(status: string): VStatusTone {
  if (status === "PASS") return "success";
  if (status === "FAIL") return "danger";
  if (status === "BLOCKED") return "warning";
  return "neutral";
}

function evidenceStatusLabel(status: string, hasLocator: boolean, zh: boolean): string {
  if (status === "PASS" && hasLocator) return zh ? "通过" : "Pass";
  if (status === "PASS") return zh ? "缺定位" : "No locator";
  if (status === "FAIL") return zh ? "失败" : "Fail";
  if (status === "BLOCKED") return zh ? "阻塞" : "Blocked";
  if (status === "MISSING") return zh ? "缺失" : "Missing";
  return zh ? "未确认" : "Unconfirmed";
}

function blockerLabel(blocker: string, zh: boolean): string {
  const labels: Record<string, { zh: string; en: string }> = {
    real_batch_missing: { zh: "real-125 结果包尚未生成", en: "The real-125 result envelope is missing" },
    result_set_incomplete: { zh: "125 题结果集尚未完整", en: "The 125-question result set is incomplete" },
    evidence_incomplete: { zh: "交付证据尚未齐全", en: "Required delivery evidence is incomplete" },
    model_policy_missing: { zh: "模型策略证据缺失", en: "The model-policy evidence is missing" },
  };
  return labels[blocker]?.[zh ? "zh" : "en"] ?? blocker;
}

function readinessStatus(readiness: ChallengeCatalogReadiness, zh: boolean): {
  label: string;
  tone: VStatusTone;
  summary: string;
} {
  const readyCounts = readiness.catalogResultSet.counts;
  const completeCounts = readyCounts.required_question_count === 125
    && readyCounts.present_count === 125
    && readyCounts.missing_count === 0
    && readyCounts.duplicate_count === 0
    && readyCounts.submission_eligible_count === 125
    && readyCounts.package_backed_count === 125
    && readyCounts.quality_approved_count === 125
    && readyCounts.human_gate_approved_count === 125
    && readyCounts.receipt_complete_count === 125;
  const locatedEvidence = EVIDENCE.every(({ id }) => {
    const evidence = readiness.evidence[id as EvidenceId];
    return evidence?.status === "PASS" && Boolean(evidence.locator?.trim());
  });
  const ready = readiness.status === "READY"
    && readiness.realCampaignAllowed === false
    && readiness.researchAuthorizationRequired === true
    && completeCounts
    && locatedEvidence;
  if (ready) {
    return {
      label: zh ? "主链就绪" : "Mainline ready",
      tone: "success",
      summary: zh
        ? "125 题结果与证据已满足当前就绪契约；真实批次仍需单独科研授权。"
        : "The 125-question result and evidence contract is ready; a real batch still needs separate research authorization.",
    };
  }
  if (readiness.status === "NOT_READY") {
    return {
      label: zh ? "未就绪" : "Not ready",
      tone: "warning",
      summary: zh
        ? "结果集或证据仍不完整，真实批次保持关闭。"
        : "The result set or evidence is incomplete; real batches remain disabled.",
    };
  }
  return {
    label: zh ? "边界异常，已阻断" : "Boundary invalid; blocked",
    tone: "danger",
    summary: zh
      ? "服务端就绪数据不完整，已按失败关闭处理，不允许暗示可运行真实批次。"
      : "The server readiness boundary is incomplete; fail-closed and do not imply a real batch can run.",
  };
}

function errorText(reason: unknown): string {
  if (reason instanceof Error && reason.message) return reason.message;
  return String(reason || "unavailable");
}

export function ChallengeCatalogReadinessPanel({
  teamId,
  lang = "zh",
}: ChallengeCatalogReadinessPanelProps) {
  const zh = lang === "zh";
  const readinessQuery = useQuery({
    queryKey: queryKeys.challengeCatalogReadiness(teamId),
    queryFn: ({ signal }: { signal?: AbortSignal }) => fetchChallengeCatalogReadiness(teamId, { signal }),
    enabled: Boolean(teamId.trim()),
    staleTime: 30_000,
    retry: false,
  });

  if (!teamId.trim()) {
    return (
      <VStateSurface
        tone="empty"
        density="compact"
        title={zh ? "125 题主链待选择团队" : "Select a team for catalog readiness"}
      />
    );
  }
  if (readinessQuery.isPending) {
    return (
      <VStateSurface
        tone="loading"
        density="compact"
        title={zh ? "读取 125 题主链状态" : "Loading 125-question mainline"}
      />
    );
  }
  if (readinessQuery.isError) {
    return (
      <VStateSurface
        tone="error"
        density="compact"
        title={zh ? "125 题主链状态不可用" : "Catalog readiness unavailable"}
        actions={(
          <VButton type="button" variant="secondary" onClick={() => void readinessQuery.refetch()}>
            {zh ? "重试" : "Retry"}
          </VButton>
        )}
      >
        <span className={styles.errorDetail}>{errorText(readinessQuery.error)}</span>
      </VStateSurface>
    );
  }

  const readiness = readinessQuery.data;
  if (!isCatalogReadiness(readiness)) {
    return (
      <VStateSurface
        tone="unavailable"
        density="compact"
        title={zh ? "125 题主链未就绪" : "Catalog readiness is not ready"}
        actions={(
          <VButton type="button" variant="secondary" onClick={() => void readinessQuery.refetch()}>
            {zh ? "重新读取" : "Reload"}
          </VButton>
        )}
      >
        {zh ? "缺少服务端结果集或证据，当前不会运行真实批次。" : "The server result set or evidence is missing; real batches remain disabled."}
      </VStateSurface>
    );
  }

  const presentation = readinessStatus(readiness, zh);
  const counts = readiness.catalogResultSet.counts;
  const blockers = readiness.blockers.map((blocker) => String(blocker).trim()).filter(Boolean);

  return (
    <VEmbeddedPanel
      ariaLabel={zh ? "125 题主链就绪状态" : "125-question mainline readiness"}
      className={styles.root}
      data-testid="catalog-readiness"
    >
      <div className={styles.header}>
        <div className={styles.titleBlock}>
          <strong className={styles.title}>{zh ? "125 题假说主链" : "125-question hypothesis mainline"}</strong>
          <span className={styles.summary}>{presentation.summary}</span>
        </div>
        <div className={styles.actions}>
          <VStatusChip tone={presentation.tone}>{presentation.label}</VStatusChip>
          <VButton type="button" variant="ghost" density="compact" onClick={() => void readinessQuery.refetch()}>
            {zh ? "刷新" : "Refresh"}
          </VButton>
        </div>
      </div>

      <VMetricStrip
        ariaLabel={zh ? "125 题主链计数" : "125-question mainline counts"}
        className={styles.metrics}
        metrics={[
          { id: "required", label: zh ? "总题数" : "Total", value: counts.required_question_count, tone: "accent" },
          { id: "present", label: zh ? "已有结果" : "Results", value: counts.present_count },
          { id: "quality", label: zh ? "质量通过" : "Quality", value: counts.quality_approved_count, tone: counts.quality_approved_count === counts.required_question_count ? "success" : "warning" },
          { id: "receipts", label: zh ? "收据完整" : "Receipts", value: counts.receipt_complete_count, tone: counts.receipt_complete_count === counts.required_question_count ? "success" : "warning" },
        ]}
      />

      <div className={styles.evidence} data-testid="catalog-readiness-evidence">
        {EVIDENCE.map(({ id, zh: labelZh, en: labelEn }) => {
          const evidence = readiness.evidence[id as EvidenceId];
          const status = String(evidence?.status || "MISSING").toUpperCase();
          const hasLocator = Boolean(evidence?.locator?.trim());
          return (
            <div className={styles.evidenceItem} key={id} title={hasLocator ? (zh ? "已记录证据定位" : "Evidence locator recorded") : (zh ? "尚未记录证据定位" : "Evidence locator missing")}>
              <span className={styles.evidenceLabel}>{zh ? labelZh : labelEn}</span>
              <span className={styles.evidenceStatus}>
                <VStatusChip tone={evidenceTone(status)}>{evidenceStatusLabel(status, hasLocator, zh)}</VStatusChip>
              </span>
              <span className={styles.evidenceLocator}>{hasLocator ? (zh ? "已记录" : "Located") : (zh ? "无定位" : "No locator")}</span>
            </div>
          );
        })}
      </div>

      {readiness.realCampaignAllowed === false && readiness.researchAuthorizationRequired ? (
        <div className={styles.boundary} role="note">
          {zh ? "运行边界：realCampaignAllowed=false；此面板只展示就绪证据，不会启动真实科研批次。" : "Run boundary: realCampaignAllowed=false; this panel only reports evidence and never starts a real research batch."}
        </div>
      ) : null}

      {blockers.length > 0 ? (
        <details className={styles.blockers} data-testid="catalog-readiness-blockers">
          <summary className={styles.blockersSummary}>
            {zh ? `查看关键阻塞项（${blockers.length}）` : `View key blockers (${blockers.length})`}
          </summary>
          <ul className={styles.blockerList}>
            {blockers.slice(0, 5).map((blocker, index) => (
              <li className={styles.blocker} key={`${blocker}-${index}`}>
                {blockerLabel(blocker, zh)}
              </li>
            ))}
          </ul>
          {blockers.length > 5 ? (
            <div className={styles.blockerMore}>
              {zh ? `另有 ${blockers.length - 5} 项已折叠。` : `${blockers.length - 5} more blockers are collapsed.`}
            </div>
          ) : null}
        </details>
      ) : null}
    </VEmbeddedPanel>
  );
}
