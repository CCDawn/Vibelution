import { type ReactNode } from "react";

import {
  TeamSourceResultStats,
  type TeamSourceResultStat,
} from "../components/vui/product/team-management";
import styles from "./TeamSourceCollectionConversationPanel.styles";

type TeamSourceCollectionConversationPanelProps = {
  lang: "zh" | "en";
  rangeText: ReactNode;
  headerText: ReactNode;
  filterBar: ReactNode;
  stats: TeamSourceResultStat[];
  pendingCandidateImportCount: number;
  missingSourceCount: number;
  children: ReactNode;
  pagination: ReactNode;
};

export function TeamSourceCollectionConversationPanel({
  lang,
  rangeText,
  headerText,
  filterBar,
  stats,
  pendingCandidateImportCount,
  missingSourceCount,
  children,
  pagination,
}: TeamSourceCollectionConversationPanelProps) {
  return (
    <section id="source-collection-process" className={styles.sourceCollectionConversationPanel} aria-label={lang === "zh" ? "搜集对话流" : "Collection conversation"}>
      <div className={styles.sourceCollectionConversationHeader}>
        <div>
          <strong>{lang === "zh" ? "本轮资料" : "Sources in this run"}</strong>
        </div>
        <small>{rangeText}</small>
      </div>
      <section id="source-collection-results" className={styles.sourceCollectionResultsPanel} aria-label={lang === "zh" ? "本轮原始资料记录" : "Raw collected records"}>
        <div className={styles.sourceCollectionResultsHeader}>
          <strong>{lang === "zh" ? "资料列表" : "Source list"}</strong>
          <span>{headerText}</span>
        </div>
        {filterBar}
        <TeamSourceResultStats
          ariaLabel={lang === "zh" ? "资料统计" : "Source stats"}
          stats={stats}
        />
        {pendingCandidateImportCount > 0 ? (
          <div className={styles.sourceCollectionResultWarning}>
            {lang === "zh"
              ? `还有 ${pendingCandidateImportCount} 条原始记录尚未进入候选库，所以“已搜到”和“候选资料”不会相等。`
              : `${pendingCandidateImportCount} raw records are not imported into candidates yet, so raw and candidate counts will differ.`}
          </div>
        ) : null}
        {missingSourceCount > 0 ? (
          <div className={styles.sourceCollectionResultWarning}>
            {lang === "zh"
              ? `${missingSourceCount} 条原始记录缺少 DOI、链接或本地文件路径，暂时不能视为可溯源结果。`
              : `${missingSourceCount} raw records are missing DOI, link, or local file path.`}
          </div>
        ) : null}
        {children}
        {pagination}
      </section>
    </section>
  );
}
