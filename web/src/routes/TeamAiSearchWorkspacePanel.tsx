import { Search } from "lucide-react";

import type { AiSearchRun, AiSearchRunSummary, AiSearchSourceScope } from "../api/types";
import { VNativeButton, VNativeInput } from "../components/vui";
import {
  aiSearchRunCardFallbackReason,
  aiSearchRunCardModeLabel,
  aiSearchRunCardUsesFallback,
  aiSearchRunCounts,
  aiSearchRunNeedsReviewCount,
  aiSearchRunNextActionText,
  aiSearchRunPath,
  aiSearchRunPrimaryResultText,
  aiSearchRunQueryCount,
  aiSearchRunStatusLabel,
  aiSearchSourceRoleLabel,
  aiSearchSourceTierLabel,
} from "./teams/aiSearchPresentation";
import aiSearchStyles from "./TeamsRoute.aiSearch.styles";
import shellStyles from "./TeamsRoute.styles";

const styles = aiSearchStyles as Record<string, string>;

type Lang = "zh" | "en";

export type TeamAiSearchWorkspacePanelProps = {
  lang: Lang;
  scope: AiSearchSourceScope | null | undefined;
  teamDetailPending: boolean;
  runs: AiSearchRunSummary[];
  runsPending: boolean;
  runsFetching: boolean;
  visibleRunCount: number;
  totalRunCount: number;
  latestRun: AiSearchRun | AiSearchRunSummary | null;
  topic: string;
  onTopicChange: (topic: string) => void;
  canStart: boolean;
  startPending: boolean;
  startErrorMessage: string | null;
  onStart: (payload: { teamId: string; topic: string }) => void;
  teamId: string | undefined;
};

function runStatusStyle(status: string | undefined) {
  if (status === "failed") return styles.aiSearchRunStatusFailed;
  if (status === "partial") return styles.aiSearchRunStatusPartial;
  if (status === "running") return styles.aiSearchRunStatusRunning;
  return styles.aiSearchRunStatusCompleted;
}

/**
 * AI Search execution workspace (scope + start form + recent run cards).
 * Presentation-only: mutations/query state stay in TeamsRoute shell.
 */
export function TeamAiSearchWorkspacePanel({
  lang,
  scope,
  teamDetailPending,
  runs,
  runsPending,
  runsFetching,
  visibleRunCount,
  totalRunCount,
  latestRun,
  topic,
  onTopicChange,
  canStart,
  startPending,
  startErrorMessage,
  onStart,
  teamId,
}: TeamAiSearchWorkspacePanelProps) {
  const latestRunCounts = latestRun ? aiSearchRunCounts(latestRun) : null;
  const latestRunStatusStyle = runStatusStyle(latestRun?.status);

  return (
    <section className={styles.aiSearchScopePanel}>
      <div className={styles.aiSearchScopeHeader}>
        <div>
          <strong>{lang === "zh" ? "AI 搜索执行台" : "AI search workspace"}</strong>
          <span>
            {scope
              ? lang === "zh"
                ? `按 ${scope.summary.enabledByDefaultCount} 个默认可信源搜索，结果保留证据链接和存放位置`
                : `Searches ${scope.summary.enabledByDefaultCount} trusted default sources and keeps evidence links plus storage`
              : (lang === "zh" ? "等待团队详情载入" : "Waiting for team detail")}
          </span>
        </div>
        <span className={styles.aiSearchScopeBadge}>
          {scope?.policy.requiresPrimaryEvidenceForConclusion
            ? (lang === "zh" ? "结论需一手证据" : "Primary proof required")
            : (lang === "zh" ? "证据规则未启用" : "Proof rule off")}
        </span>
      </div>
      {scope ? (
        <>
          <div className={styles.aiSearchWorkflowSummary}>
            <div>
              <strong>{lang === "zh" ? "搜索过程" : "Search process"}</strong>
              <span>
                {lang === "zh"
                  ? "主题输入后依次生成搜索、读取可信来源、提取摘要与引用、保存运行记录。"
                  : "A topic becomes queries, trusted sources are scanned, summaries and references are extracted, and the run is stored."}
              </span>
            </div>
            <small>
              {lang === "zh"
                ? "主视图只显示可判断结果；技术细节在下方展开。"
                : "Main view shows decision-ready results; technical details stay collapsed below."}
            </small>
          </div>
          <form
            className={styles.aiSearchRunPanel}
            onSubmit={(event) => {
              event.preventDefault();
              if (!teamId || !canStart) {
                return;
              }
              onStart({ teamId, topic });
            }}
          >
            <div className={styles.aiSearchRunHeader}>
              <div>
                <strong>{lang === "zh" ? "启动一轮搜索" : "Start a search round"}</strong>
                <span>{lang === "zh" ? "主题 -> 可信来源 -> 摘要/引用 -> 运行记录" : "Topic -> trusted sources -> summary/refs -> run record"}</span>
              </div>
              <VNativeButton type="submit" disabled={!canStart}>
                <Search size={13} />
                {startPending
                  ? (lang === "zh" ? "搜索中" : "Searching")
                  : (lang === "zh" ? "启动一键搜索" : "Start search")}
              </VNativeButton>
            </div>
            <label className={styles.aiSearchRunTopic}>
              <span>{lang === "zh" ? "主题" : "Topic"}</span>
              <VNativeInput
                value={topic}
                onChange={(event) => onTopicChange(event.target.value)}
                placeholder={lang === "zh" ? "AI 最新动态" : "Latest AI updates"}
              />
            </label>
            {startErrorMessage ? (
              <div className={shellStyles.messageError}>{startErrorMessage}</div>
            ) : null}
            <div className={styles.aiSearchRunResultHeader}>
              <strong>{lang === "zh" ? "最近搜索结果" : "Recent search results"}</strong>
              <span>
                {runsFetching
                  ? (lang === "zh" ? "刷新中" : "refreshing")
                  : `${visibleRunCount}/${totalRunCount}`}
              </span>
            </div>
            {latestRun && latestRunCounts ? (
              <div className={styles.aiSearchRunLatest}>
                <div className={styles.aiSearchRunSummary}>
                  <div>
                    <strong>{latestRun.title}</strong>
                    <span>{latestRun.runId} · {latestRun.topic}</span>
                  </div>
                  <span className={`${styles.aiSearchRunStatus} ${latestRunStatusStyle}`}>
                    {aiSearchRunStatusLabel(latestRun.status, lang)}
                  </span>
                </div>
                <div className={styles.aiSearchRunInsight}>
                  <div>
                    <strong>{lang === "zh" ? "本轮判断" : "Run readout"}</strong>
                    <span>{aiSearchRunPrimaryResultText(latestRun, latestRunCounts, lang)}</span>
                  </div>
                  <small>{aiSearchRunNextActionText(latestRun, latestRunCounts, lang)}</small>
                </div>
                <div className={styles.aiSearchRunStats}>
                  <span>{lang === "zh" ? "查询" : "queries"} <strong>{aiSearchRunQueryCount(latestRun)}</strong></span>
                  <span>{lang === "zh" ? "可用结果" : "usable"} <strong>{latestRunCounts.succeededCount}</strong></span>
                  <span>{lang === "zh" ? "需复核" : "review"} <strong>{aiSearchRunNeedsReviewCount(latestRun)}</strong></span>
                  <span>{lang === "zh" ? "失败" : "failed"} <strong>{latestRunCounts.failedCount}</strong></span>
                  {latestRunCounts.degradedCount ? (
                    <span>{lang === "zh" ? "降级" : "fallback"} <strong>{latestRunCounts.degradedCount}</strong></span>
                  ) : null}
                  <span>{lang === "zh" ? "引用" : "refs"} <strong>{latestRunCounts.referenceCount}</strong></span>
                </div>
                <div className={styles.aiSearchRunCards}>
                  {latestRun.cards.slice(0, 6).map((card) => {
                    const cardNeedsReview = card.status === "failed" || aiSearchRunCardUsesFallback(card);
                    const cardModeLabel = aiSearchRunCardModeLabel(card, lang);
                    const fallbackReason = aiSearchRunCardFallbackReason(card);
                    const cardClasses = [styles.aiSearchRunCard];
                    if (card.status === "failed") {
                      cardClasses.push(styles.aiSearchRunCardFailed);
                    } else if (cardNeedsReview) {
                      cardClasses.push(styles.aiSearchRunCardReview);
                    }
                    if (card.degraded) {
                      cardClasses.push(styles.aiSearchRunCardDegraded);
                    }
                    return (
                      <article key={card.cardId} className={cardClasses.filter(Boolean).join(" ")}>
                        <div className={styles.aiSearchRunCardHeader}>
                          <div>
                            <strong>{card.sourceName || card.sourceId}</strong>
                            <span>
                              {card.groupLabel} · {aiSearchSourceTierLabel(card.tier, lang)} · {card.sourceType}
                              {cardModeLabel ? ` · ${cardModeLabel}` : ""}
                            </span>
                          </div>
                          <span>
                            {card.status === "failed" ? (lang === "zh" ? "失败" : "failed") : cardNeedsReview ? (lang === "zh" ? "需复核" : "review") : (lang === "zh" ? "可用" : "usable")}
                          </span>
                        </div>
                        <div className={styles.aiSearchRunQuery}>
                          <span>{lang === "zh" ? "搜索词" : "Query"}</span>
                          <strong>{card.query}</strong>
                          {cardModeLabel ? <em>{cardModeLabel}</em> : null}
                        </div>
                        {card.degraded && fallbackReason ? (
                          <small className={styles.aiSearchRunFallbackReason}>
                            {lang === "zh" ? "主搜索降级" : "Primary search fallback"}: {fallbackReason}
                          </small>
                        ) : null}
                        <p>{card.summary || (card.status === "failed" ? (lang === "zh" ? "搜索执行失败，已保留失败卡片。" : "Search failed; the failed card was retained.") : card.query)}</p>
                        <div className={styles.aiSearchRunRefs}>
                          <small>{lang === "zh" ? "证据链接" : "Evidence links"}</small>
                          {card.references.length ? (
                            card.references.slice(0, 3).map((reference) => (
                              <a key={`${card.cardId}-${reference.url}`} href={reference.url} target="_blank" rel="noreferrer">
                                {reference.title || reference.url}
                              </a>
                            ))
                          ) : (
                            <span>{lang === "zh" ? "暂无可点开的参考来源" : "No clickable references yet"}</span>
                          )}
                        </div>
                        {fallbackReason || card.resultText ? (
                          <details className={styles.aiSearchRunCardDetails}>
                            <summary>{lang === "zh" ? "执行细节" : "Execution detail"}</summary>
                            {fallbackReason ? <span>{fallbackReason}</span> : null}
                            {card.resultText ? <p>{card.resultText}</p> : null}
                          </details>
                        ) : null}
                      </article>
                    );
                  })}
                </div>
                <div className={styles.aiSearchRunStorage}>
                  <strong>{lang === "zh" ? "存放位置" : "Stored at"}</strong>
                  <span>{aiSearchRunPath(latestRun)}</span>
                </div>
              </div>
            ) : (
              <div className={shellStyles.empty}>
                {runsPending
                  ? (lang === "zh" ? "正在读取最近搜索结果..." : "Loading recent search results...")
                  : (lang === "zh" ? "还没有搜索记录。输入主题后启动一轮搜索，结果会按“本轮判断、证据链接、存放位置”展示。" : "No search records yet. Enter a topic and start a search round; results will show readout, evidence links, and storage.")}
              </div>
            )}
          </form>
          <details className={styles.aiSearchScopeDetails}>
            <summary>
              <span>{lang === "zh" ? "来源与技术边界" : "Sources and technical boundary"}</span>
              <small>{lang === "zh" ? "白名单、去重、存储路径" : "Allowlist, dedupe, storage path"}</small>
            </summary>
            <p className={styles.aiSearchScopeDescription}>{scope.description}</p>
            <div className={styles.aiSearchScopeStats}>
              <span>{lang === "zh" ? "来源分组" : "Groups"} <strong>{scope.summary.groupCount}</strong></span>
              <span>{lang === "zh" ? "默认启用" : "Default on"} <strong>{scope.summary.enabledByDefaultCount}</strong></span>
              <span>{lang === "zh" ? "仅线索" : "Signals"} <strong>{scope.summary.signalOnlyCount}</strong></span>
            </div>
            <div className={styles.aiSearchScopePolicy}>
              <span>{lang === "zh" ? "默认 Tier" : "Default tiers"}: {scope.policy.defaultEnabledTiers.join(", ")}</span>
              <span>{lang === "zh" ? "去重" : "Dedupe"}: {scope.policy.dedupeBy.join(" / ")}</span>
              <span>{lang === "zh" ? "正式知识写入" : "Formal write"}: {scope.policy.writesFormalKnowledge ? "on" : "off"}</span>
              <span>{scope.storage.path}</span>
            </div>
            <div className={styles.aiSearchSourceGroups}>
              {scope.groups.map((group) => (
                <article key={group.groupId} className={styles.aiSearchSourceGroup}>
                  <div className={styles.aiSearchSourceGroupHeader}>
                    <div>
                      <strong>{group.label}</strong>
                      <span>{aiSearchSourceTierLabel(group.tier, lang)} · {aiSearchSourceRoleLabel(group.evidenceRole, lang)}</span>
                    </div>
                    <span className={group.enabledByDefault ? styles.aiSearchScopeEnabled : styles.aiSearchScopeSignal}>
                      {group.enabledByDefault ? (lang === "zh" ? "默认启用" : "enabled") : (lang === "zh" ? "线索" : "signal")}
                    </span>
                  </div>
                  <p>{group.description}</p>
                  <div className={styles.aiSearchSourceList}>
                    {group.sources.map((source) => (
                      <a key={source.sourceId} href={source.url} target="_blank" rel="noreferrer" className={styles.aiSearchSourceItem}>
                        <strong>{source.name}</strong>
                        <span>{source.sourceType} · {source.region} · {source.language}</span>
                        <small>{source.tags.slice(0, 4).join(" / ")}</small>
                      </a>
                    ))}
                  </div>
                </article>
              ))}
            </div>
          </details>
        </>
      ) : (
        <div className={shellStyles.empty}>
          {teamDetailPending
            ? (lang === "zh" ? "正在读取 AI 搜索范围名单..." : "Loading AI search source scope...")
            : (lang === "zh" ? "当前团队详情没有返回 sourceScope。" : "This Team detail did not return sourceScope.")}
        </div>
      )}
    </section>
  );
}
