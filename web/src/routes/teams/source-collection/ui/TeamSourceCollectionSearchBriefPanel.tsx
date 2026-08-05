import { Plus, X } from "lucide-react";
import { type KeyboardEvent, type ReactNode, useMemo, useState } from "react";

import { VNativeButton, VNativeInput, VNativeTextarea } from "../../../../components/vui";
import {
  splitDraftList,
  type SourceCollectionDraft,
} from "../presentationModel";
import styles from "./TeamSourceCollectionSearchBriefPanel.styles";

type TeamSourceCollectionSearchBriefPanelProps = {
  lang: "zh" | "en";
  draft: SourceCollectionDraft;
  modeFields: ReactNode;
  hasExistingRun: boolean;
  onDraftChange: (patch: Partial<SourceCollectionDraft>) => void;
};

function joinQuerySeeds(items: string[]) {
  return items.map((item) => item.trim()).filter(Boolean).join("\n");
}

export function TeamSourceCollectionSearchBriefPanel({
  lang,
  draft,
  modeFields,
  hasExistingRun,
  onDraftChange,
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
        <h2 className={styles.title}>{isZh ? "先决定要研究什么" : "Decide what to research"}</h2>
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
          rows={5}
          placeholder={
            isZh
              ? "完整写出本轮研究焦点或假说（会驱动检索；尽量一句话说清问题）"
              : "Write the full research focus or hypothesis for this run"
          }
          onChange={(event) => onDraftChange({ topic: event.target.value })}
        />
        <small className={styles.fieldHint}>
          <span>
            {isZh
              ? "主题是主编辑区；下方检索式可选，勿把同一假说拆成多条碎句"
              : "Topic is the primary field; queries below are optional retrieval lines"}
          </span>
          <span>{draft.topic.length}/120</span>
        </small>
      </label>

      <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <strong>{isZh ? "检索式（可选）" : "Queries (optional)"}</strong>
          <span>
            {isZh
              ? `${querySeeds.length}/12 · 一行一条，宜短宜可搜`
              : `${querySeeds.length}/12 · one short, searchable line each`}
          </span>
        </div>

        <div className={styles.queryList} role="list" aria-label={isZh ? "检索式列表" : "Query list"}>
          {querySeeds.length ? (
            querySeeds.map((query, index) => (
              <div className={styles.queryRow} key={`query-seed-${index}`} role="listitem">
                <span className={styles.queryIndex} aria-hidden>
                  {index + 1}
                </span>
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
                  <X size={14} aria-hidden />
                </VNativeButton>
              </div>
            ))
          ) : (
            <div className={styles.emptyQueries}>
              {isZh
                ? "未添加检索式时，将直接用研究主题搜索。需要更具体的关键词时可在此补充。"
                : "Without queries, search uses the research topic. Add short keywords when needed."}
            </div>
          )}
        </div>

        <div className={styles.addQuery}>
          <VNativeInput
            className={styles.addInput}
            value={newQuery}
            maxLength={240}
            disabled={querySeeds.length >= 12}
            placeholder={isZh ? "补充一条检索式，回车添加" : "Add a query, press Enter"}
            aria-label={isZh ? "补充搜索问题" : "Add search query"}
            onChange={(event) => setNewQuery(event.target.value)}
            onKeyDown={handleNewQueryKeyDown}
          />
          <VNativeButton
            type="button"
            className={styles.addButton}
            disabled={!newQuery.trim() || querySeeds.length >= 12}
            aria-label={isZh ? "添加搜索问题" : "Add search query"}
            title={isZh ? "添加" : "Add"}
            onClick={addQuery}
          >
            <Plus size={15} aria-hidden />
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
            ? (hasExistingRun
              ? "方案会用于右侧「推荐下一步」推进搜索；不会在这里重复开搜。"
              : "填好主题与问题后，请只在右侧「推荐下一步」开始搜集。")
            : (hasExistingRun
              ? "This brief feeds the single right-rail next-step action; search is not started here."
              : "After editing the brief, start collection only from the right-rail next step.")}
        </span>
      </div>
    </section>
  );
}
