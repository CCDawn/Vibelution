import { CheckCircle2, CircleAlert, CircleX, Settings2 } from "lucide-react";

import type { AgentEffectiveConfigurationField } from "../api/types";
import { VButton, VEmptyState, VNativeButton, VPanel } from "../components/vui";
import styles from "./AgentEffectiveConfigurationPanel.styles";

type EffectiveConfigurationField = AgentEffectiveConfigurationField;

type AgentEffectiveConfigurationPanelProps = {
  fields: EffectiveConfigurationField[];
  selectedFieldKey: string;
  onSelectField: (key: string) => void;
  onOpenConfig: () => void;
};

type AgentEffectiveConfigurationInspectorPanelProps = {
  field: EffectiveConfigurationField | null;
  onOpenConfig: () => void;
};

function valueLine(field: EffectiveConfigurationField | { key: string; effectiveValue: unknown }) {
  const value = field.effectiveValue;
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  if (typeof value === "boolean") {
    return value ? "已启用" : "未启用";
  }
  if (typeof value !== "object" || Array.isArray(value)) {
    return "已配置";
  }
  const record = value as Record<string, unknown>;
  if (field.key === "contextCompression") {
    const mode = String(record.mode || "默认");
    const limit = Number(record.maxTokenLimit || 0);
    return limit > 0 ? `${mode} · 上限 ${limit.toLocaleString()} tokens` : mode;
  }
  if (field.key === "delegation") {
    const allowed = record.allowSubagents === true ? "可委派" : "禁止委派";
    const concurrent = Number(record.maxConcurrent || 0);
    const depth = Number(record.maxDepth || 0);
    return `${allowed} · 并发 ${concurrent} · 深度 ${depth}`;
  }
  if (field.key === "supervision") {
    const enabled = record.supervisionEnabled === true ? "监督已启用" : "监督未启用";
    const reviewMode = String(record.reviewMode || "默认");
    const evidence = String(record.evidenceLevel || "standard");
    return `${enabled} · ${reviewMode} · ${evidence}`;
  }
  return "已配置";
}

function statusLabel(status: string) {
  if (status === "blocked") {
    return "受阻";
  }
  if (status === "warning") {
    return "需关注";
  }
  return "可用";
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

function sourceSummary(fields: EffectiveConfigurationField[]) {
  const labels = fields.map((field) => field.source.label).filter(Boolean);
  return Array.from(new Set(labels)).join(" → ") || "等待配置投影";
}

function fieldHint(key: string) {
  return {
    dialogueModel: "对话、规划与协调",
    promptTemplate: "身份、边界与工作规范",
    toolPolicy: "允许、拦截与人工审批",
    memoryPolicy: "私有记忆与共享知识",
    contextCompression: "长上下文保留方式",
    delegation: "子 Agent 并发与层级",
    supervision: "复核与证据门禁",
  }[key] || "运行时配置";
}

export function AgentEffectiveConfigurationPanel({
  fields,
  selectedFieldKey,
  onSelectField,
  onOpenConfig,
}: AgentEffectiveConfigurationPanelProps) {
  return (
    <VPanel ariaLabel="当前有效配置" className={styles.configurationPanel}>
      <header className={styles.panelHeader}>
        <div>
          <h3>当前有效配置</h3>
          <p>展示运行时实际生效的值、来源与健康状态；不展示密钥或原始策略 JSON。</p>
        </div>
        <VButton type="button" variant="secondary" icon={<Settings2 size={14} />} onPress={onOpenConfig}>
          修改配置
        </VButton>
      </header>
      <div className={styles.sourceSummary} aria-label="配置来源摘要">
        <strong className={styles.sourceSummaryLabel}>来源</strong>
        <span title={sourceSummary(fields)}>{sourceSummary(fields)}</span>
      </div>
      {fields.length ? (
        <div className={styles.configurationTable} role="table" aria-label="有效配置字段">
          <div className={styles.tableHeader} role="row">
            <span>配置项</span>
            <span>有效值</span>
            <span>来源</span>
            <span>状态</span>
          </div>
          {fields.map((field) => {
            const selected = field.key === selectedFieldKey;
            return (
              <VNativeButton
                key={field.key}
                type="button"
                className={`${styles.configurationRow} ${selected ? styles.configurationRowSelected : ""}`}
                role="row"
                aria-pressed={selected}
                onClick={() => onSelectField(field.key)}
              >
                <span className={styles.fieldIdentity}>
                  <strong>{field.label}</strong>
                  <small>{fieldHint(field.key)}</small>
                </span>
                <span className={styles.fieldValue}>
                  <strong title={valueLine(field)}>{valueLine(field)}</strong>
                  <small>{field.inheritanceChain.length} 层来源</small>
                </span>
                <span className={styles.sourceCell}>
                  <em className={sourceClass(field.source.kind)}>{field.source.label}</em>
                </span>
                <span className={`${styles.statusCell} ${statusClass(field.status)}`}>
                  <StatusIcon status={field.status} />
                  {statusLabel(field.status)}
                </span>
              </VNativeButton>
            );
          })}
        </div>
      ) : (
        <VEmptyState title="暂无有效配置投影">刷新 Agent 工作区后重试。</VEmptyState>
      )}
    </VPanel>
  );
}

export function AgentEffectiveConfigurationInspectorPanel({
  field,
  onOpenConfig,
}: AgentEffectiveConfigurationInspectorPanelProps) {
  if (!field) {
    return (
      <VEmptyState title="选择一个配置项">
        选择左侧有效配置字段，查看完整继承链。
      </VEmptyState>
    );
  }

  return (
    <section className={styles.inspectorSection} aria-label={`${field.label} 检查器`}>
      <h4>{field.label}</h4>
      <span className={styles.inspectorLabel}>当前生效值</span>
      <strong className={styles.inspectorValue}>{valueLine(field)}</strong>
      <span className={styles.inspectorLabel}>配置来源</span>
      <ol className={styles.inheritanceList}>
        {field.inheritanceChain.map((source, index) => (
          <li
            key={`${source.kind}:${source.id}:${index}`}
            className={`${styles.inheritanceItem} ${source.active ? styles.inheritanceCurrent : ""}`}
          >
            <span className={styles.inheritanceIndex}>{index + 1}</span>
            <span className={styles.inheritanceCopy}>
              <strong>{source.label}{source.active ? " · 当前生效" : ""}</strong>
              <small>{valueLine({ key: field.key, effectiveValue: source.value })}</small>
            </span>
          </li>
        ))}
      </ol>
      <VButton type="button" variant="secondary" className={styles.inspectorAction} onPress={onOpenConfig}>
        修改配置
      </VButton>
    </section>
  );
}
