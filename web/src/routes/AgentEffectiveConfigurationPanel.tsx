import { CheckCircle2, CircleAlert, CircleX, Settings2 } from "lucide-react";

import type { AgentEffectiveConfigurationField } from "../api/types";
import { VButton, VEmptyState, VNativeButton, VPanel, VPanelHeader, VTooltip } from "../components/vui";
import styles from "./AgentEffectiveConfigurationPanel.styles";

type EffectiveConfigurationField = AgentEffectiveConfigurationField;

type AgentEffectiveConfigurationPanelProps = {
  fields: EffectiveConfigurationField[];
  selectedFieldKey: string;
  onSelectField: (key: string) => void;
  onOpenConfig: () => void;
  lang?: "zh" | "en";
};

type AgentEffectiveConfigurationInspectorPanelProps = {
  field: EffectiveConfigurationField | null;
  onOpenConfig: () => void;
  lang?: "zh" | "en";
};

type PanelCopy = {
  panelTitle: string;
  panelTooltip: string;
  panelTooltipLabel: string;
  openConfig: string;
  source: string;
  sourceSummaryLabel: string;
  sourceConfigLabel: string;
  configItem: string;
  effectiveValue: string;
  sourceColumn: string;
  statusColumn: string;
  enabled: string;
  disabled: string;
  configured: string;
  defaultMode: string;
  canDelegate: string;
  cannotDelegate: string;
  concurrent: string;
  depth: string;
  limitLabel: string;
  supervisionEnabled: string;
  supervisionDisabled: string;
  reviewMode: string;
  evidenceStandard: string;
  blocked: string;
  needsAttention: string;
  available: string;
  waitingProjection: string;
  fieldHints: Record<string, string>;
  runtimeConfig: string;
  noProjection: string;
  selectField: string;
  inspectorLabel: string;
  currentEffective: string;
  chainActive: string;
};

const COPY: Record<"zh" | "en", PanelCopy> = {
  zh: {
    panelTitle: "当前有效配置",
    panelTooltip: "展示运行时实际生效的值、来源与健康状态；不展示密钥或原始策略 JSON。",
    panelTooltipLabel: "当前有效配置说明",
    openConfig: "修改配置",
    source: "来源",
    sourceSummaryLabel: "来源",
    sourceConfigLabel: "配置来源",
    configItem: "配置项",
    effectiveValue: "有效值",
    sourceColumn: "来源",
    statusColumn: "状态",
    enabled: "已启用",
    disabled: "未启用",
    configured: "已配置",
    defaultMode: "默认",
    canDelegate: "可委派",
    cannotDelegate: "禁止委派",
    concurrent: "并发",
    depth: "深度",
    limitLabel: "上限",
    supervisionEnabled: "监督已启用",
    supervisionDisabled: "监督未启用",
    reviewMode: "复核模式",
    evidenceStandard: "标准",
    blocked: "受阻",
    needsAttention: "需关注",
    available: "可用",
    waitingProjection: "等待配置投影",
    fieldHints: {
      dialogueModel: "对话、规划与协调",
      promptTemplate: "身份、边界与工作规范",
      toolPolicy: "允许、拦截与人工审批",
      memoryPolicy: "私有记忆与共享知识",
      contextCompression: "长上下文保留方式",
      delegation: "子 Agent 并发与层级",
      supervision: "复核与证据门禁",
    },
    runtimeConfig: "运行时配置",
    noProjection: "暂无有效配置投影",
    selectField: "选择一个配置项",
    inspectorLabel: "当前生效值",
    currentEffective: "当前生效",
    chainActive: "当前生效",
  },
  en: {
    panelTitle: "Effective configuration",
    panelTooltip: "Shows the values actually in effect, their sources, and health; secrets and raw policy JSON are never shown.",
    panelTooltipLabel: "Effective configuration details",
    openConfig: "Edit config",
    source: "Source",
    sourceSummaryLabel: "Source",
    sourceConfigLabel: "Config source",
    configItem: "Field",
    effectiveValue: "Effective value",
    sourceColumn: "Source",
    statusColumn: "Status",
    enabled: "Enabled",
    disabled: "Disabled",
    configured: "Configured",
    defaultMode: "default",
    canDelegate: "Delegation allowed",
    cannotDelegate: "Delegation blocked",
    concurrent: "concurrency",
    depth: "depth",
    limitLabel: "limit",
    supervisionEnabled: "Supervision on",
    supervisionDisabled: "Supervision off",
    reviewMode: "review mode",
    evidenceStandard: "standard",
    blocked: "Blocked",
    needsAttention: "Attention",
    available: "Available",
    waitingProjection: "Waiting for config projection",
    fieldHints: {
      dialogueModel: "Dialogue, planning, and coordination",
      promptTemplate: "Identity, boundaries, and working norms",
      toolPolicy: "Allow, block, and human approval",
      memoryPolicy: "Private memory and shared knowledge",
      contextCompression: "Long-context retention",
      delegation: "Sub-agent concurrency and depth",
      supervision: "Review and evidence gates",
    },
    runtimeConfig: "Runtime config",
    noProjection: "No effective config projection yet",
    selectField: "Select a field",
    inspectorLabel: "Effective value",
    currentEffective: "currently active",
    chainActive: " · currently active",
  },
};

function evidenceLevelLabel(value: string, copy: PanelCopy) {
  if (value === "standard") {
    return copy.evidenceStandard;
  }
  return value;
}

function valueLine(field: EffectiveConfigurationField | { key: string; effectiveValue: unknown }, copy: PanelCopy) {
  const value = field.effectiveValue;
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  if (typeof value === "boolean") {
    return value ? copy.enabled : copy.disabled;
  }
  if (typeof value !== "object" || Array.isArray(value)) {
    return copy.configured;
  }
  const record = value as Record<string, unknown>;
  if (field.key === "contextCompression") {
    const mode = String(record.mode || copy.defaultMode);
    const limit = Number(record.maxTokenLimit || 0);
    return limit > 0 ? `${mode} · ${copy.limitLabel} ${limit.toLocaleString()} tokens` : mode;
  }
  if (field.key === "delegation") {
    const allowed = record.allowSubagents === true ? copy.canDelegate : copy.cannotDelegate;
    const concurrent = Number(record.maxConcurrent || 0);
    const depth = Number(record.maxDepth || 0);
    return `${allowed} · ${copy.concurrent} ${concurrent} · ${copy.depth} ${depth}`;
  }
  if (field.key === "supervision") {
    const enabled = record.supervisionEnabled === true ? copy.supervisionEnabled : copy.supervisionDisabled;
    const reviewMode = String(record.reviewMode || copy.defaultMode);
    const evidence = evidenceLevelLabel(String(record.evidenceLevel || "standard"), copy);
    return `${enabled} · ${copy.reviewMode}: ${reviewMode} · ${evidence}`;
  }
  return copy.configured;
}

function statusLabel(status: string, copy: PanelCopy) {
  if (status === "blocked") {
    return copy.blocked;
  }
  if (status === "warning") {
    return copy.needsAttention;
  }
  return copy.available;
}

function statusClass(status: string) {
  if (status === "blocked") {
    return styles.statusBlocked;
  }
  if (status === "warning") {
    return styles.statusWarning;
  }
  return styles.statusReady;
}

function StatusIcon({ status }: { status: string }) {
  if (status === "blocked") {
    return <CircleX size={14} aria-hidden="true" />;
  }
  if (status === "warning") {
    return <CircleAlert size={14} aria-hidden="true" />;
  }
  return <CheckCircle2 size={14} aria-hidden="true" />;
}

function sourceClass(kind: string) {
  if (kind === "agent") {
    return `${styles.sourceChip} ${styles.sourceChipAgent}`;
  }
  if (kind === "global" || kind === "mode_default") {
    return `${styles.sourceChip} ${styles.sourceChipGlobal}`;
  }
  if (kind === "system") {
    return `${styles.sourceChip} ${styles.sourceChipSystem}`;
  }
  return styles.sourceChip;
}

function sourceSummary(fields: EffectiveConfigurationField[], copy: PanelCopy) {
  const labels = fields.map((field) => field.source.label).filter(Boolean);
  return Array.from(new Set(labels)).join(" → ") || copy.waitingProjection;
}

function fieldHint(key: string, copy: PanelCopy) {
  return copy.fieldHints[key] || copy.runtimeConfig;
}

export function AgentEffectiveConfigurationPanel({
  fields,
  selectedFieldKey,
  onSelectField,
  onOpenConfig,
  lang = "zh",
}: AgentEffectiveConfigurationPanelProps) {
  const copy = COPY[lang];
  return (
    <VPanel ariaLabel={copy.panelTitle} className={styles.configurationPanel}>
      <VPanelHeader
        className={styles.panelHeader}
        headingLevel={3}
        title={copy.panelTitle}
        tooltip={copy.panelTooltip}
        tooltipLabel={copy.panelTooltipLabel}
        actions={(
          <VButton type="button" variant="secondary" icon={<Settings2 size={14} />} onPress={onOpenConfig}>
            {copy.openConfig}
          </VButton>
        )}
      />
      <div className={styles.sourceSummary} aria-label={copy.sourceSummaryLabel}>
        <strong className={styles.sourceSummaryLabel}>{copy.source}</strong>
        <span title={sourceSummary(fields, copy)}>{sourceSummary(fields, copy)}</span>
      </div>
      {fields.length ? (
        <div className={styles.configurationTable} role="table" aria-label={copy.panelTitle}>
          <div className={styles.tableHeader} role="row">
            <span>{copy.configItem}</span>
            <span>{copy.effectiveValue}</span>
            <span>{copy.sourceColumn}</span>
            <span>{copy.statusColumn}</span>
          </div>
          {fields.map((field) => {
            const selected = field.key === selectedFieldKey;
            return (
              <VTooltip
                key={field.key}
                width="wide"
                content={(
                  <span className="grid gap-1">
                    <span>{fieldHint(field.key, copy)}</span>
                    <span>{field.inheritanceChain.length} {lang === "zh" ? "层来源" : "source layers"}</span>
                  </span>
                )}
              >
                <VNativeButton
                  type="button"
                  className={`${styles.configurationRow} ${selected ? styles.configurationRowSelected : ""}`}
                  role="row"
                  aria-pressed={selected}
                  onClick={() => onSelectField(field.key)}
                >
                  <span className={styles.fieldIdentity}>
                    <strong>{field.label}</strong>
                  </span>
                  <span className={styles.fieldValue}>
                    <strong title={valueLine(field, copy)}>{valueLine(field, copy)}</strong>
                  </span>
                  <span className={styles.sourceCell}>
                    <em className={sourceClass(field.source.kind)}>{field.source.label}</em>
                  </span>
                  <span className={`${styles.statusCell} ${statusClass(field.status)}`}>
                    <StatusIcon status={field.status} />
                    {statusLabel(field.status, copy)}
                  </span>
                </VNativeButton>
              </VTooltip>
            );
          })}
        </div>
      ) : (
        <VEmptyState title={copy.noProjection} />
      )}
    </VPanel>
  );
}

export function AgentEffectiveConfigurationInspectorPanel({
  field,
  onOpenConfig,
  lang = "zh",
}: AgentEffectiveConfigurationInspectorPanelProps) {
  const copy = COPY[lang];
  if (!field) {
    return <VEmptyState title={copy.selectField} />;
  }

  return (
    <section className={styles.inspectorSection} aria-label={`${field.label} ${lang === "zh" ? "检查器" : "inspector"}`}>
      <h4>{field.label}</h4>
      <span className={styles.inspectorLabel}>{copy.inspectorLabel}</span>
      <strong className={styles.inspectorValue}>{valueLine(field, copy)}</strong>
      <span className={styles.inspectorLabel}>{copy.sourceConfigLabel}</span>
      <ol className={styles.inheritanceList}>
        {field.inheritanceChain.map((source, index) => (
          <li
            key={`${source.kind}:${source.id}:${index}`}
            className={`${styles.inheritanceItem} ${source.active ? styles.inheritanceCurrent : ""}`}
          >
            <span className={styles.inheritanceIndex}>{index + 1}</span>
            <span className={styles.inheritanceCopy}>
              <VTooltip
                width="wide"
                content={valueLine({ key: field.key, effectiveValue: source.value }, copy)}
              >
                <strong
                  className={styles.inheritanceTrigger}
                  tabIndex={0}
                  aria-label={`${source.label}：${valueLine({ key: field.key, effectiveValue: source.value }, copy)}`}
                >
                  {source.label}{source.active ? copy.chainActive : ""}
                </strong>
              </VTooltip>
            </span>
          </li>
        ))}
      </ol>
      <VButton type="button" variant="secondary" className={styles.inspectorAction} onPress={onOpenConfig}>
        {copy.openConfig}
      </VButton>
    </section>
  );
}
