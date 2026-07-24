import { Plus, Search, X } from "lucide-react";
import { type KeyboardEvent, type ReactNode, useMemo, useState } from "react";

import { VNativeButton, VNativeInput, VNativeTextarea } from "../components/vui";
import {
  splitDraftList,
  type SourceCollectionDraft,
} from "./teams/source-collection/presentationModel";
import styles from "./TeamSourceCollectionSearchBriefPanel.styles";

type TeamSourceCollectionSearchBriefPanelProps = {
  lang: "zh" | "en";
  draft: SourceCollectionDraft;
  modeFields: ReactNode;
  hasExistingRun: boolean;
  canStart: boolean;
  startPending: boolean;
  onDraftChange: (patch: Partial<SourceCollectionDraft>) => void;
  onSubmit: () => void;
};

function joinQuerySeeds(items: string[]) {
  return items.map((item) => item.trim()).filter(Boolean).join("\n");
}

export function TeamSourceCollectionSearchBriefPanel({
  lang,
  draft,
  modeFields,
  hasExistingRun,
  canStart,
  startPending,
  onDraftChange,
  onSubmit,
}: TeamSourceCollectionSearchBriefPanelProps) {
  const isZh = lang === "zh";
  const [newQuery, setNewQuery] = useState("");
  const querySeeds = useMemo(() => splitDraftList(draft.querySeeds, 12), [draft.querySeeds]);

  const updateQuery = (index: number, value: string) => {
    const next = [...querySeeds];
    next[index] = value;
    onDraftChange({ querySeeds: next.join("\n") });
  };

  const removeQuery = (index: number) => {
    onDraftChange({ querySeeds: joinQuerySeeds(querySeeds.filter((_, itemIndex) => itemIndex !== index)) });
  };

  const addQuery = () => {
    const value = newQuery.trim();
    if (!value || querySeeds.length >= 12) {
      return;
    }
    onDraftChange({ querySeeds: joinQuerySeeds([...querySeeds, value]) });
    setNewQuery("");
  };

  const handleNewQueryKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Enter") {
      return;
    }
    event.preventDefault();
    addQuery();
  };

  return (
    <section
      className={styles.panel}
      data-vui-product="source-collection-search-brief"
      aria-label={isZh ? "搜索任务设置" : "Search brief"}
    >
      <div className={styles.header}>
        <div>
          <span className={styles.eyebrow}>{isZh ? "搜索任务" : "Search brief"}</span>
          <h2 className={styles.title}>{isZh ? "先决定要研究什么" : "Decide what to research"}</h2>
        </div>
        <span className={styles.badge}>{isZh ? "本轮配置" : "Current setup"}</span>
      </div>

      <label className={styles.field}>
        <span>
          {isZh ? "研究主题" : "Research topic"}
          <em className={styles.required}>{isZh ? "必填" : "Required"}</em>
        </span>
        <VNativeTextarea
          className={styles.topicTextarea}
          value={draft.topic}
          maxLength={120}
          rows={3}
          placeholder={isZh ? "用一句话说明本轮真正要解决的问题" : "State the question this run should resolve"}
          onChange={(event) => onDraftChange({ topic: event.target.value })}
        />
        <small className={styles.fieldHint}>
          <span>{isZh ? "主题和搜索问题会直接决定下一批结果" : "The topic and queries determine the next batch"}</span>
          <span>{draft.topic.length}/120</span>
        </small>
      </label>

      <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <div>
            <strong>{isZh ? "搜索问题" : "Search queries"}</strong>
            <span>
              {isZh
                ? `逐条修改或删除，最多 12 个 · 当前 ${querySeeds.length} 个`
                : `Edit or remove each query · ${querySeeds.length}/12`}
            </span>
          </div>
        </div>

        <div className={styles.queryList}>
          {querySeeds.length ? querySeeds.map((query, index) => (
            <label className={styles.queryRow} key={`${index}-${query}`}>
              <span className={styles.queryIndex}>{index + 1}</span>
              <VNativeInput
                className={styles.queryInput}
                aria-label={isZh ? `搜索问题 ${index + 1}` : `Search query ${index + 1}`}
                value={query}
                onChange={(event) => updateQuery(index, event.target.value)}
              />
              <VNativeButton
                type="button"
                className={styles.removeButton}
                aria-label={isZh ? `删除搜索问题 ${index + 1}` : `Remove search query ${index + 1}`}
                title={isZh ? "删除" : "Remove"}
                onClick={() => removeQuery(index)}
              >
                <X size={13} aria-hidden />
              </VNativeButton>
            </label>
          )) : (
            <div className={styles.emptyQueries}>
              {isZh ? "尚未添加搜索问题；至少补充一个问题后再开始搜索。" : "Add at least one query before searching."}
            </div>
          )}
        </div>

        <div className={styles.addQuery}>
          <VNativeInput
            value={newQuery}
            maxLength={240}
            disabled={querySeeds.length >= 12}
            placeholder={isZh ? "补充一个搜索问题" : "Add a search query"}
            aria-label={isZh ? "补充搜索问题" : "Add search query"}
            onChange={(event) => setNewQuery(event.target.value)}
            onKeyDown={handleNewQueryKeyDown}
          />
          <VNativeButton
            type="button"
            className={styles.addButton}
            disabled={!newQuery.trim() || querySeeds.length >= 12}
            aria-label={isZh ? "添加搜索问题" : "Add search query"}
            title={isZh ? "添加搜索问题" : "Add search query"}
            onClick={addQuery}
          >
            <Plus size={14} aria-hidden />
          </VNativeButton>
        </div>
      </div>

      <details className={styles.advanced}>
        <summary>{isZh ? "搜索范围与来源偏好" : "Search scope and source preferences"}</summary>
        <div className={styles.advancedBody}>
          <label className={`${styles.field} ${styles.wide}`}>
            <span>{isZh ? "研究目标" : "Research goal"}</span>
            <VNativeTextarea
              value={draft.goal}
              rows={2}
              placeholder={isZh ? "可选：说明需要什么结论或证据" : "Optional: describe the evidence or conclusion needed"}
              onChange={(event) => onDraftChange({ goal: event.target.value })}
            />
          </label>
          <div className={styles.settingsGrid}>
            <label className={styles.field}>
              <span>{isZh ? "批次标题" : "Run title"}</span>
              <VNativeInput value={draft.title} onChange={(event) => onDraftChange({ title: event.target.value })} />
            </label>
            <label className={styles.field}>
              <span>{isZh ? "语言" : "Languages"}</span>
              <VNativeInput
                value={draft.searchLanguages}
                onChange={(event) => onDraftChange({ searchLanguages: event.target.value })}
              />
            </label>
            <label className={styles.field}>
              <span>{isZh ? "来源类型" : "Source types"}</span>
              <VNativeInput value={draft.sourceTypes} onChange={(event) => onDraftChange({ sourceTypes: event.target.value })} />
            </label>
            <label className={styles.field}>
              <span>{isZh ? "每个问题最多结果" : "Max results per query"}</span>
              <VNativeInput
                type="number"
                min={1}
                max={100}
                value={draft.maxResultsPerQuery}
                onChange={(event) =>
                  onDraftChange({
                    maxResultsPerQuery: Math.max(1, Math.min(100, Number(event.target.value) || 1)),
                  })
                }
              />
            </label>
          </div>
          <label className={styles.field}>
            <span>{isZh ? "已有资料或引用" : "Existing sources or references"}</span>
            <VNativeTextarea
              value={draft.inputRefs}
              rows={2}
              placeholder={isZh ? "可选：本地文件、URL 或 seed-query:..." : "Optional: local file, URL, or seed-query:..."}
              onChange={(event) => onDraftChange({ inputRefs: event.target.value })}
            />
          </label>
          {modeFields}
        </div>
      </details>

      <div className={styles.actionRow}>
        <span className={styles.actionHint}>
          {isZh
            ? (hasExistingRun ? "会新建批次，不覆盖当前资料" : "开始后会创建可追踪的资料批次")
            : (hasExistingRun ? "Creates a new run without overwriting current sources" : "Creates a traceable source run")}
        </span>
        <VNativeButton
          type="button"
          className={styles.primaryAction}
          disabled={!canStart || startPending}
          onClick={onSubmit}
        >
          <Search size={13} aria-hidden />
          {startPending
            ? (isZh ? "正在启动" : "Starting")
            : hasExistingRun
              ? (isZh ? "按当前方案搜索下一批" : "Search next batch")
              : (isZh ? "开始搜索" : "Start search")}
        </VNativeButton>
      </div>
    </section>
  );
}
