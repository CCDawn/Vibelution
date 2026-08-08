import { History, Save, Trash2 } from "lucide-react";

import type { AgentConfigChanges } from "../api/types";
import { VButton, VEmptyState, VPanel, VPanelHeader } from "../components/vui";
import styles from "./AgentConfigChangeHistoryPanel.styles";
import { ProgressiveRegionSkeleton } from "./shared/ProgressiveRegionSkeleton";

type AgentConfigChangeHistoryPanelProps = {
  changes: AgentConfigChanges | undefined;
  configDirty: boolean;
  loading: boolean;
  savePending: boolean;
  discardPending: boolean;
  onSaveDraft: () => void;
  onDiscardDraft: () => void;
  onOpenConfig: () => void;
  lang?: "zh" | "en";
};

const FIELD_LABELS: Record<"zh" | "en", Record<string, string>> = {
  zh: {
    displayName: "名称",
    llmBindings: "模型绑定",
    reasoningEffortBySlot: "推理强度",
    promptTemplateId: "提示词",
    toolPolicyId: "工具策略",
    memoryPolicyId: "记忆策略",
    contextCompressionPolicy: "上下文压缩",
    status: "状态",
  },
  en: {
    displayName: "Name",
    llmBindings: "Model bindings",
    reasoningEffortBySlot: "Reasoning effort",
    promptTemplateId: "Prompt",
    toolPolicyId: "Tool policy",
    memoryPolicyId: "Memory policy",
    contextCompressionPolicy: "Context compression",
    status: "Status",
  },
};

type HistoryCopy = {
  panelTitle: string;
  panelTooltip: string;
  panelTooltipLabel: string;
  savingDraft: string;
  saveDraft: string;
  loadingLabel: string;
  currentDraft: string;
  draftStale: string;
  draftReady: string;
  draftChangedFields: string;
  goPublish: string;
  discardingDraft: string;
  discardDraft: string;
  publishedRevisions: string;
  revisionCount: string;
  revisionFields: string;
  publishedFromDraft: string;
  publishedDirect: string;
  linkedSession: string;
  noLinkedSession: string;
  empty: string;
};

const COPY: Record<"zh" | "en", HistoryCopy> = {
  zh: {
    panelTitle: "草稿与版本",
    panelTooltip: "草稿不影响运行；只有配置页的保存操作才会发布，并留下关联会话的版本证据。",
    panelTooltipLabel: "草稿与版本说明",
    savingDraft: "正在保存草稿…",
    saveDraft: "保存当前草稿",
    loadingLabel: "正在读取草稿与版本记录",
    currentDraft: "当前草稿",
    draftStale: "基线已变化，需重新审阅",
    draftReady: "可前往配置发布",
    draftChangedFields: "草稿变更字段",
    goPublish: "前往配置发布",
    discardingDraft: "正在放弃草稿…",
    discardDraft: "放弃草稿",
    publishedRevisions: "已发布版本",
    revisionCount: "条",
    revisionFields: "变更字段",
    publishedFromDraft: "由草稿发布",
    publishedDirect: "直接发布",
    linkedSession: "关联会话",
    noLinkedSession: "未关联会话",
    empty: "尚无草稿或版本记录",
  },
  en: {
    panelTitle: "Draft & revisions",
    panelTooltip: "Drafts never affect the runtime; only saving from the config page publishes a revision with linked session evidence.",
    panelTooltipLabel: "Draft and revisions details",
    savingDraft: "Saving draft…",
    saveDraft: "Save current draft",
    loadingLabel: "Loading draft and revisions",
    currentDraft: "Current draft",
    draftStale: "Baseline changed — review again",
    draftReady: "Ready to publish from config",
    draftChangedFields: "Draft changed fields",
    goPublish: "Go to config publish",
    discardingDraft: "Discarding draft…",
    discardDraft: "Discard draft",
    publishedRevisions: "Published revisions",
    revisionCount: "items",
    revisionFields: "changed fields",
    publishedFromDraft: "Published from draft",
    publishedDirect: "Published directly",
    linkedSession: "Linked session",
    noLinkedSession: "No linked session",
    empty: "No drafts or revisions yet",
  },
};

function fieldsLabel(fields: string[], lang: "zh" | "en") {
  const labels = FIELD_LABELS[lang];
  return fields.map((field) => labels[field] || field).filter(Boolean);
}

function timestampLabel(value: string, lang: "zh" | "en") {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "-"
    : date.toLocaleString(lang === "zh" ? "zh-CN" : "en-US", { hour12: false });
}

export function AgentConfigChangeHistoryPanel({
  changes,
  configDirty,
  loading,
  savePending,
  discardPending,
  onSaveDraft,
  onDiscardDraft,
  onOpenConfig,
  lang = "zh",
}: AgentConfigChangeHistoryPanelProps) {
  const copy = COPY[lang];
  const draft = changes?.activeDraft ?? null;
  const revisions = changes?.revisions ?? [];

  return (
    <VPanel ariaLabel={copy.panelTitle} className={styles.historyPanel}>
      <VPanelHeader
        className={styles.panelHeader}
        headingLevel={3}
        title={copy.panelTitle}
        tooltip={copy.panelTooltip}
        tooltipLabel={copy.panelTooltipLabel}
        actions={(
          <div className={styles.actions}>
            {configDirty ? (
              <VButton
                type="button"
                variant="secondary"
                icon={<Save size={14} />}
                isDisabled={savePending}
                onPress={onSaveDraft}
              >
                {savePending ? copy.savingDraft : copy.saveDraft}
              </VButton>
            ) : null}
          </div>
        )}
      />

      {loading ? (
        <ProgressiveRegionSkeleton variant="list" label={copy.loadingLabel} />
      ) : null}

      {draft ? (
        <section className={styles.draftCard} aria-label={copy.currentDraft}>
          <VPanelHeader
            className={styles.draftHeader}
            headingLevel={4}
            title={copy.currentDraft}
            actions={(
              <span className={`${styles.draftStatus} ${draft.stale ? styles.draftStale : ""}`}>
                {draft.stale ? copy.draftStale : copy.draftReady}
              </span>
            )}
          />
          {draft.summary ? <p className={styles.draftSummary}>{draft.summary}</p> : null}
          <ul className={styles.changedFields} aria-label={copy.draftChangedFields}>
            {fieldsLabel(draft.changedFields, lang).map((field) => <li key={field} className={styles.changedField}>{field}</li>)}
          </ul>
          <div className={styles.draftActions}>
            <VButton type="button" variant="secondary" onPress={onOpenConfig}>
              {copy.goPublish}
            </VButton>
            <VButton
              type="button"
              variant="ghost"
              icon={<Trash2 size={14} />}
              isDisabled={discardPending}
              onPress={onDiscardDraft}
            >
              {discardPending ? copy.discardingDraft : copy.discardDraft}
            </VButton>
          </div>
        </section>
      ) : null}

      {revisions.length ? (
        <section className={styles.revisionList} aria-label={copy.publishedRevisions}>
          <VPanelHeader
            className={styles.revisionHeader}
            headingLevel={4}
            title={copy.publishedRevisions}
            actions={<span>{revisions.length} {copy.revisionCount}</span>}
          />
          {revisions.map((revision) => (
            <article key={revision.revisionId} className={styles.revisionRow}>
              <VPanelHeader
                className={styles.revisionHeader}
                headingLevel={4}
                title={`v${revision.revisionNumber}`}
                actions={<span>{timestampLabel(revision.publishedAt, lang)}</span>}
              />
              <ul className={styles.changedFields} aria-label={`v${revision.revisionNumber} ${copy.revisionFields}`}>
                {fieldsLabel(revision.changedFields, lang).map((field) => <li key={field} className={styles.changedField}>{field}</li>)}
              </ul>
              <div className={styles.revisionMeta}>
                <span>{revision.sourceDraftId ? copy.publishedFromDraft : copy.publishedDirect}</span>
                {revision.runtimeBinding.directSessionId ? <span>{copy.linkedSession}：{revision.runtimeBinding.directSessionId}</span> : <span>{copy.noLinkedSession}</span>}
              </div>
            </article>
          ))}
        </section>
      ) : null}

      {!loading && !draft && !revisions.length ? (
        <VEmptyState title={copy.empty} icon={<History size={16} />} />
      ) : null}
    </VPanel>
  );
}
