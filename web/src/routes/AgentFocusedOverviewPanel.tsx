import { Activity, AlertTriangle, Gauge, Settings2, Users } from "lucide-react";
import { type ReactNode } from "react";

import type {
  AgentEffectiveConfigurationField,
  AgentRunSnapshot,
} from "../api/types";
import {
  VButton,
  VMetricStrip,
  VStatusChip,
  VSurface,
  type VStatusTone,
} from "../components/vui";
import type { AgentOverviewActivityView } from "./AgentOverviewOperationsPanel";
import styles from "./AgentFocusedOverviewPanel.styles";

export type AgentFocusedOverviewAttention = {
  id: string;
  title: string;
  detail: string;
  tone: "neutral" | "warning" | "danger";
};

export type AgentFocusedOverviewPanelProps = {
  lang: "zh" | "en";
  summary: {
    statusLabel: string;
    statusTone: VStatusTone;
    statusDetail: string;
    modelLabel: string;
    modelDetail: string;
    revisionLabel: string;
    latestRunLabel: string;
  };
  effectiveFields: AgentEffectiveConfigurationField[];
  activities: AgentOverviewActivityView[];
  activityState: "loading" | "ready" | "error";
  activityError?: string;
  identity: {
    roleLabel: string;
    modeLabel: string;
    workspaceLabel: string;
    teamNames: string[];
  };
  runs: AgentRunSnapshot[];
  pendingApprovalCount: number;
  attentionItems: AgentFocusedOverviewAttention[];
  onOpenConfig: () => void;
  onOpenActivity: () => void;
};

export type AgentRunHealthSummary = {
  runCount24h: number;
  successRate: number | null;
  p95DurationMs: number | null;
};

const SUCCESS_STATUSES = new Set(["completed", "done", "success", "succeeded"]);
const FAILURE_STATUSES = new Set([
  "blocked",
  "canceled",
  "cancelled",
  "error",
  "failed",
  "stopped",
]);

export function summarizeAgentRuns(
  runs: AgentRunSnapshot[],
  nowMs = Date.now(),
): AgentRunHealthSummary {
  const cutoff = nowMs - 24 * 60 * 60 * 1000;
  const recentRuns = runs.filter((run) => {
    const startedAt = Date.parse(run.startedAt);
    return Number.isFinite(startedAt) && startedAt >= cutoff && startedAt <= nowMs;
  });
  const terminalRuns = recentRuns.filter((run) => {
    const status = String(run.status || "").trim().toLowerCase();
    return SUCCESS_STATUSES.has(status) || FAILURE_STATUSES.has(status);
  });
  const successfulRuns = terminalRuns.filter((run) =>
    SUCCESS_STATUSES.has(String(run.status || "").trim().toLowerCase()),
  );
  const durations = recentRuns
    .map((run) => {
      const startedAt = Date.parse(run.startedAt);
      const endedAt = Date.parse(run.finishedAt || run.updatedAt);
      return Number.isFinite(startedAt) && Number.isFinite(endedAt) && endedAt >= startedAt
        ? endedAt - startedAt
        : null;
    })
    .filter((duration): duration is number => duration !== null)
    .sort((left, right) => left - right);
  const percentileIndex = durations.length
    ? Math.max(0, Math.ceil(durations.length * 0.95) - 1)
    : -1;

  return {
    runCount24h: recentRuns.length,
    successRate: terminalRuns.length
      ? Math.round((successfulRuns.length / terminalRuns.length) * 100)
      : null,
    p95DurationMs: percentileIndex >= 0 ? durations[percentileIndex] : null,
  };
}

function copyFor(lang: "zh" | "en") {
  return lang === "zh"
    ? {
        summary: "Agent 概览摘要",
        status: "状态",
        model: "模型",
        revision: "Revision",
        latestRun: "最近运行",
        effectiveEyebrow: "运行时真值",
        effective: "有效配置",
        effectiveHint: "展示实际生效的值与来源，不重复完整编辑表单。",
        field: "配置项",
        value: "有效值",
        source: "来源",
        state: "状态",
        ready: "可用",
        warning: "需关注",
        blocked: "受阻",
        configured: "已配置",
        enabled: "已启用",
        disabled: "未启用",
        items: "项",
        editConfig: "打开配置",
        activityEyebrow: "运行与变更",
        activity: "最近活动",
        allActivity: "查看全部",
        noActivity: "还没有可汇总的运行、消息或配置活动。",
        activityLoading: "正在加载最近活动…",
        activityError: "最近活动暂时不可用，请到活动页重试。",
        identityEyebrow: "归属",
        identity: "身份与团队",
        role: "角色",
        mode: "模式",
        workspace: "工作区",
        team: "团队",
        noTeam: "未加入可见团队",
        healthEyebrow: "最近 24 小时",
        health: "运行健康",
        runCount: "运行次数",
        successRate: "成功率",
        p95: "P95 时延",
        approvals: "待审批",
        insufficient: "不足以计算",
        attentionEyebrow: "下一步",
        attention: "需要关注",
        noAttention: "当前没有阻塞、警告或待处理配置项。",
        noEffective: "暂无有效配置投影。",
      }
    : {
        summary: "Agent overview summary",
        status: "Status",
        model: "Model",
        revision: "Revision",
        latestRun: "Latest run",
        effectiveEyebrow: "Runtime truth",
        effective: "Effective configuration",
        effectiveHint: "Shows values actually in effect and their sources without repeating the full editor.",
        field: "Field",
        value: "Effective value",
        source: "Source",
        state: "Status",
        ready: "Available",
        warning: "Attention",
        blocked: "Blocked",
        configured: "Configured",
        enabled: "Enabled",
        disabled: "Disabled",
        items: "items",
        editConfig: "Open config",
        activityEyebrow: "Runs and changes",
        activity: "Recent activity",
        allActivity: "View all",
        noActivity: "No run, message, or configuration activity is available yet.",
        activityLoading: "Loading recent activity…",
        activityError: "Recent activity is unavailable. Retry from the Activity tab.",
        identityEyebrow: "Ownership",
        identity: "Identity and team",
        role: "Role",
        mode: "Mode",
        workspace: "Workspace",
        team: "Team",
        noTeam: "No visible team membership",
        healthEyebrow: "Last 24 hours",
        health: "Runtime health",
        runCount: "Runs",
        successRate: "Success rate",
        p95: "P95 latency",
        approvals: "Approvals",
        insufficient: "Insufficient data",
        attentionEyebrow: "Next steps",
        attention: "Needs attention",
        noAttention: "No blockers, warnings, or pending configuration actions.",
        noEffective: "No effective configuration projection is available.",
      };
}

function effectiveTone(status: string): VStatusTone {
  if (status === "blocked") return "danger";
  if (status === "warning") return "warning";
  return "success";
}

function effectiveStatusLabel(
  status: string,
  copy: ReturnType<typeof copyFor>,
): string {
  if (status === "blocked") return copy.blocked;
  if (status === "warning") return copy.warning;
  return copy.ready;
}

export function focusedEffectiveValue(
  field: Pick<AgentEffectiveConfigurationField, "key" | "effectiveValue">,
  lang: "zh" | "en",
): string {
  const copy = copyFor(lang);
  const value = field.effectiveValue;
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (typeof value === "boolean") return value ? copy.enabled : copy.disabled;
  if (Array.isArray(value)) return value.length ? `${value.length} ${copy.items}` : "-";
  if (typeof value !== "object") return copy.configured;
  const record = value as Record<string, unknown>;
  if (field.key === "contextCompression") {
    const mode = String(record.mode || "-");
    const limit = Number(record.maxTokenLimit || 0);
    return limit > 0 ? `${mode} · ${limit.toLocaleString()} tokens` : mode;
  }
  if (field.key === "delegation") {
    const allowed = record.allowSubagents === true ? copy.enabled : copy.disabled;
    const concurrency = Number(record.maxConcurrent || 0);
    const depth = Number(record.maxDepth || 0);
    return `${allowed} · ${concurrency || "-"} / ${depth || "-"}`;
  }
  if (field.key === "supervision") {
    const enabled = record.supervisionEnabled === true ? copy.enabled : copy.disabled;
    return `${enabled} · ${String(record.reviewMode || "-")}`;
  }
  const conciseValue = record.modelId
    || record.modelRef
    || record.promptTemplateId
    || record.policyId
    || record.id;
  return conciseValue ? String(conciseValue) : copy.configured;
}

function formatDuration(durationMs: number | null, insufficient: string): string {
  if (durationMs === null) return "-";
  if (!Number.isFinite(durationMs) || durationMs < 0) return insufficient;
  if (durationMs < 1_000) return `${Math.round(durationMs)} ms`;
  if (durationMs < 60_000) return `${(durationMs / 1_000).toFixed(1)} s`;
  return `${(durationMs / 60_000).toFixed(1)} min`;
}

function SectionHeader({
  eyebrow,
  title,
  count,
  action,
}: {
  eyebrow: string;
  title: string;
  count?: number;
  action?: ReactNode;
}) {
  return (
    <header className={styles.sectionHeader}>
      <div className={styles.sectionTitle}>
        <p className={styles.eyebrow}>{eyebrow}</p>
        <h3 className={styles.heading}>{title}</h3>
      </div>
      {action ?? (typeof count === "number" ? <span className={styles.sectionCount}>{count}</span> : null)}
    </header>
  );
}

export function AgentFocusedOverviewPanel({
  lang,
  summary,
  effectiveFields,
  activities,
  activityState,
  activityError,
  identity,
  runs,
  pendingApprovalCount,
  attentionItems,
  onOpenConfig,
  onOpenActivity,
}: AgentFocusedOverviewPanelProps) {
  const copy = copyFor(lang);
  const runHealth = summarizeAgentRuns(runs);
  const visibleFields = effectiveFields.slice(0, 8);
  const visibleActivities = activities.slice(0, 6);
  const visibleAttention = attentionItems.slice(0, 6);

  return (
    <div className={styles.overview} data-agent-focused-overview="true">
      <VMetricStrip
        className={styles.metricStrip}
        ariaLabel={copy.summary}
        status={{
          ariaLabel: copy.status,
          label: summary.statusLabel,
          title: summary.statusDetail,
          tone: summary.statusTone,
        }}
        metrics={[
          {
            id: "model",
            label: copy.model,
            value: summary.modelLabel,
            detail: summary.modelDetail,
          },
          { id: "revision", label: copy.revision, value: summary.revisionLabel },
          { id: "latest-run", label: copy.latestRun, value: summary.latestRunLabel },
        ]}
      />

      <div className={styles.workspace}>
        <div className={styles.mainColumn}>
          <VSurface className={styles.surface} tone="panel" padding="normal" ariaLabel={copy.effective}>
            <SectionHeader
              eyebrow={copy.effectiveEyebrow}
              title={copy.effective}
              action={(
                <VButton
                  type="button"
                  variant="secondary"
                  icon={<Settings2 size={14} />}
                  onPress={onOpenConfig}
                >
                  {copy.editConfig}
                </VButton>
              )}
            />
            <span className="sr-only">{copy.effectiveHint}</span>
            {visibleFields.length ? (
              <div className={styles.effectiveTable} role="table" aria-label={copy.effective}>
                <div className={styles.effectiveHeader} role="row">
                  <span>{copy.field}</span>
                  <span>{copy.value}</span>
                  <span>{copy.source}</span>
                  <span>{copy.state}</span>
                </div>
                {visibleFields.map((field) => (
                  <div key={field.key} className={styles.effectiveRow} role="row">
                    <span className={styles.effectiveIdentity} role="cell">
                      <strong>{field.label}</strong>
                    </span>
                    <span className={styles.effectiveValue} role="cell">
                      {focusedEffectiveValue(field, lang)}
                    </span>
                    <span className={styles.effectiveSource} role="cell" title={field.source.label}>
                      {field.source.label || "-"}
                    </span>
                    <VStatusChip
                      className={styles.effectiveStatus}
                      tone={effectiveTone(field.status)}
                      role="cell"
                    >
                      {effectiveStatusLabel(field.status, copy)}
                    </VStatusChip>
                  </div>
                ))}
              </div>
            ) : (
              <p className={styles.empty}>{copy.noEffective}</p>
            )}
          </VSurface>

          <VSurface className={styles.surface} tone="panel" padding="normal" ariaLabel={copy.activity}>
            <SectionHeader
              eyebrow={copy.activityEyebrow}
              title={copy.activity}
              action={(
                <VButton
                  type="button"
                  variant="secondary"
                  icon={<Activity size={14} />}
                  onPress={onOpenActivity}
                >
                  {copy.allActivity}
                </VButton>
              )}
            />
            {activityState === "loading" ? (
              <p className={styles.loading} role="status">{copy.activityLoading}</p>
            ) : activityState === "error" ? (
              <p className={styles.error} role="status">{activityError || copy.activityError}</p>
            ) : visibleActivities.length ? (
              <div className={styles.activityList}>
                {visibleActivities.map((activity) => (
                  <article key={activity.id} className={styles.activityItem}>
                    <h4 className={styles.activityTitle}>{activity.title}</h4>
                    <p className={styles.activityBody}>{activity.body || "-"}</p>
                    <span className={styles.activityMeta} title={activity.meta}>{activity.meta || "-"}</span>
                  </article>
                ))}
              </div>
            ) : (
              <p className={styles.empty}>{copy.noActivity}</p>
            )}
          </VSurface>
        </div>

        <aside className={styles.sideColumn} aria-label={`${copy.identity} / ${copy.health} / ${copy.attention}`}>
          <VSurface className={styles.surface} tone="panel" padding="normal" ariaLabel={copy.identity}>
            <SectionHeader eyebrow={copy.identityEyebrow} title={copy.identity} />
            <div className={styles.identityGrid}>
              <div className={styles.identityItem}>
                <span className={styles.identityLabel}>{copy.role}</span>
                <strong className={styles.identityValue}>{identity.roleLabel || "-"}</strong>
              </div>
              <div className={styles.identityItem}>
                <span className={styles.identityLabel}>{copy.mode}</span>
                <strong className={styles.identityValue}>{identity.modeLabel || "-"}</strong>
              </div>
              <div className={styles.identityItem}>
                <span className={styles.identityLabel}>{copy.workspace}</span>
                <strong className={styles.identityValue}>{identity.workspaceLabel || "-"}</strong>
              </div>
              <div className={styles.identityItem}>
                <span className={styles.identityLabel}>{copy.team}</span>
                <strong className={styles.identityValue}>{identity.teamNames.length || "-"}</strong>
              </div>
              <div className={styles.teamList} aria-label={copy.team}>
                {identity.teamNames.length ? identity.teamNames.map((team) => (
                  <span key={team} className={styles.teamChip}><Users size={12} /><span>{team}</span></span>
                )) : <span className={styles.empty}>{copy.noTeam}</span>}
              </div>
            </div>
          </VSurface>

          <VSurface className={styles.surface} tone="panel" padding="normal" ariaLabel={copy.health}>
            <SectionHeader eyebrow={copy.healthEyebrow} title={copy.health} action={<Gauge size={17} />} />
            <div className={styles.healthGrid}>
              {[
                [copy.runCount, String(runHealth.runCount24h)],
                [copy.successRate, runHealth.successRate === null ? "-" : `${runHealth.successRate}%`],
                [copy.p95, formatDuration(runHealth.p95DurationMs, copy.insufficient)],
                [copy.approvals, String(pendingApprovalCount)],
              ].map(([label, value]) => (
                <div key={label} className={styles.healthMetric}>
                  <strong className={styles.healthValue}>{value}</strong>
                  <span className={styles.healthLabel}>{label}</span>
                </div>
              ))}
            </div>
          </VSurface>

          <VSurface className={styles.surface} tone="panel" padding="normal" ariaLabel={copy.attention}>
            <SectionHeader eyebrow={copy.attentionEyebrow} title={copy.attention} count={attentionItems.length} />
            {visibleAttention.length ? (
              <div className={styles.attentionList}>
                {visibleAttention.map((item) => (
                  <article key={item.id} className={styles.attentionItem}>
                    <div className={styles.attentionTitle}>
                      <VStatusChip tone={item.tone}>{item.title}</VStatusChip>
                      {item.tone !== "neutral" ? <AlertTriangle size={14} aria-hidden="true" /> : null}
                    </div>
                    <p className={styles.attentionCopy}>{item.detail || "-"}</p>
                  </article>
                ))}
              </div>
            ) : (
              <p className={styles.empty}>{copy.noAttention}</p>
            )}
          </VSurface>
        </aside>
      </div>
    </div>
  );
}
