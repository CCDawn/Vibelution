import { History, Save, Trash2 } from "lucide-react";

import type { AgentConfigChanges } from "../api/types";
import { VButton, VEmptyState, VPanel } from "../components/vui";
import styles from "./AgentConfigChangeHistoryPanel.styles";

type AgentConfigChangeHistoryPanelProps = {
  changes: AgentConfigChanges | undefined;
  configDirty: boolean;
  loading: boolean;
  savePending: boolean;
  discardPending: boolean;
  onSaveDraft: () => void;
  onDiscardDraft: () => void;
  onOpenConfig: () => void;
};

const fieldLabels: Record<string, string> = {
  displayName: "名称",
  llmBindings: "模型绑定",
  reasoningEffortBySlot: "推理强度",
  promptTemplateId: "提示词",
  toolPolicyId: "工具策略",
  memoryPolicyId: "记忆策略",
  contextCompressionPolicy: "上下文压缩",
  status: "状态",
};

function fieldsLabel(fields: string[]) {
  return fields.map((field) => fieldLabels[field] || field).filter(Boolean);
}

function timestampLabel(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "-" : date.toLocaleString("zh-CN", { hour12: false });
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
}: AgentConfigChangeHistoryPanelProps) {
  const draft = changes?.activeDraft ?? null;
  const revisions = changes?.revisions ?? [];

  return (
    <VPanel ariaLabel="草稿与版本" className={styles.historyPanel}>
      <header className={styles.panelHeader}>
        <div>
          <h3>草稿与版本</h3>
          <p>草稿不影响运行；只有配置页的保存操作才会发布，并留下关联会话的版本证据。</p>
        </div>
        <div className={styles.actions}>
          {configDirty ? (
            <VButton
              type="button"
              variant="secondary"
              icon={<Save size={14} />}
              isDisabled={savePending}
              onPress={onSaveDraft}
            >
              {savePending ? "正在保存草稿…" : "保存当前草稿"}
            </VButton>
          ) : null}
        </div>
      </header>

      {loading ? <p className={styles.emptyText}>正在读取草稿与版本记录…</p> : null}

      {draft ? (
        <section className={styles.draftCard} aria-label="当前草稿">
          <header className={styles.draftHeader}>
            <h4>当前草稿</h4>
            <span className={`${styles.draftStatus} ${draft.stale ? styles.draftStale : ""}`}>
              {draft.stale ? "基线已变化，需重新审阅" : "可前往配置发布"}
            </span>
          </header>
          {draft.summary ? <p className={styles.draftSummary}>{draft.summary}</p> : null}
          <ul className={styles.changedFields} aria-label="草稿变更字段">
            {fieldsLabel(draft.changedFields).map((field) => <li key={field} className={styles.changedField}>{field}</li>)}
          </ul>
          <div className={styles.draftActions}>
            <VButton type="button" variant="secondary" onPress={onOpenConfig}>
              前往配置发布
            </VButton>
            <VButton
              type="button"
              variant="ghost"
              icon={<Trash2 size={14} />}
              isDisabled={discardPending}
              onPress={onDiscardDraft}
            >
              {discardPending ? "正在放弃草稿…" : "放弃草稿"}
            </VButton>
          </div>
        </section>
      ) : null}

      {revisions.length ? (
        <section className={styles.revisionList} aria-label="已发布版本">
          <header className={styles.revisionHeader}>
            <h4>已发布版本</h4>
            <span>{revisions.length} 条</span>
          </header>
          {revisions.map((revision) => (
            <article key={revision.revisionId} className={styles.revisionRow}>
              <div className={styles.revisionHeader}>
                <h4>v{revision.revisionNumber}</h4>
                <span>{timestampLabel(revision.publishedAt)}</span>
              </div>
              <ul className={styles.changedFields} aria-label={`v${revision.revisionNumber} 变更字段`}>
                {fieldsLabel(revision.changedFields).map((field) => <li key={field} className={styles.changedField}>{field}</li>)}
              </ul>
              <div className={styles.revisionMeta}>
                <span>{revision.sourceDraftId ? "由草稿发布" : "直接发布"}</span>
                {revision.runtimeBinding.directSessionId ? <span>关联会话：{revision.runtimeBinding.directSessionId}</span> : <span>未关联会话</span>}
              </div>
            </article>
          ))}
        </section>
      ) : null}

      {!loading && !draft && !revisions.length ? (
        <VEmptyState title="尚无草稿或版本记录" icon={<History size={16} />}>
          在配置页修改后可保存草稿；发布后的变更会在这里保留简要证据。
        </VEmptyState>
      ) : null}
    </VPanel>
  );
}
