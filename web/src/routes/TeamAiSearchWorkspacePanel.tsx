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
          <strong>{lang === "zh" ? "AI 鎼滅储鎵ц鍙? : "AI search workspace"}</strong>
          <span>
            {scope
              ? lang === "zh"
                ? `鎸?${scope.summary.enabledByDefaultCount} 涓粯璁ゅ彲淇℃簮鎼滅储锛岀粨鏋滀繚鐣欒瘉鎹摼鎺ュ拰瀛樻斁浣嶇疆`
                : `Searches ${scope.summary.enabledByDefaultCount} trusted default sources and keeps evidence links plus storage`
              : (lang === "zh" ? "绛夊緟鍥㈤槦璇︽儏杞藉叆" : "Waiting for team detail")}
          </span>
        </div>
        <span className={styles.aiSearchScopeBadge}>
          {scope?.policy.requiresPrimaryEvidenceForConclusion
            ? (lang === "zh" ? "缁撹闇€涓€鎵嬭瘉鎹? : "Primary proof required")
            : (lang === "zh" ? "璇佹嵁瑙勫垯鏈惎鐢? : "Proof rule off")}
        </span>
      </div>
      {scope ? (
        <>
          <div className={styles.aiSearchWorkflowSummary}>
            <div>
              <strong>{lang === "zh" ? "鎼滅储杩囩▼" : "Search process"}</strong>
              <span>
                {lang === "zh"
                  ? "涓婚杈撳叆鍚庝緷娆＄敓鎴愭悳绱€佽鍙栧彲淇℃潵婧愩€佹彁鍙栨憳瑕佷笌寮曠敤銆佷繚瀛樿繍琛岃褰曘€?
                  : "A topic becomes queries, trusted sources are scanned, summaries and references are extracted, and the run is stored."}
              </span>
            </div>
            <small>
              {lang === "zh"
                ? "涓昏鍥惧彧鏄剧ず鍙垽鏂粨鏋滐紱鎶€鏈粏鑺傚湪涓嬫柟灞曞紑銆?
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
                <strong>{lang === "zh" ? "鍚姩涓€杞悳绱? : "Start a search round"}</strong>
                <span>{lang === "zh" ? "涓婚 -> 鍙俊鏉ユ簮 -> 鎽樿/寮曠敤 -> 杩愯璁板綍" : "Topic -> trusted sources -> summary/refs -> run record"}</span>
              </div>
              <VNativeButton type="submit" disabled={!canStart}>
                <Search size={13} />
                {startPending
                  ? (lang === "zh" ? "鎼滅储涓? : "Searching")
                  : (lang === "zh" ? "鍚姩涓€閿悳绱? : "Start search")}
              </VNativeButton>
            </div>
            <label className={styles.aiSearchRunTopic}>
              <span>{lang === "zh" ? "涓婚" : "Topic"}</span>
              <VNativeInput
                value={topic}
                onChange={(event) => onTopicChange(event.target.value)}
                placeholder={lang === "zh" ? "AI 鏈€鏂板姩鎬? : "Latest AI updates"}
              />
            </label>
            {startErrorMessage ? (
              <div className={shellStyles.messageError}>{startErrorMessage}</div>
            ) : null}
            <div className={styles.aiSearchRunResultHeader}>
              <strong>{lang === "zh" ? "鏈€杩戞悳绱㈢粨鏋? : "Recent search results"}</strong>
              <span>
                {runsFetching
                  ? (lang === "zh" ? "鍒锋柊涓? : "refreshing")
                  : `${visibleRunCount}/${totalRunCount}`}
              </span>
            </div>
            {latestRun && latestRunCounts ? (
              <div className={styles.aiSearchRunLatest}>
                <div className={styles.aiSearchRunSummary}>
                  <div>
                    <strong>{latestRun.title}</strong>
                    <span>{latestRun.runId} 路 {latestRun.topic}</span>
                  </div>
                  <span className={`${styles.aiSearchRunStatus} ${latestRunStatusStyle}`}>
                    {aiSearchRunStatusLabel(latestRun.status, lang)}
                  </span>
                </div>
                <div className={styles.aiSearchRunInsight}>
                  <div>
                    <strong>{lang === "zh" ? "鏈疆鍒ゆ柇" : "Run readout"}</strong>
                    <span>{aiSearchRunPrimaryResultText(latestRun, latestRunCounts, lang)}</span>
                  </div>
                  <small>{aiSearchRunNextActionText(latestRun, latestRunCounts, lang)}</small>
                </div>
                <div className={styles.aiSearchRunStats}>
                  <span>{lang === "zh" ? "鏌ヨ" : "queries"} <strong>{aiSearchRunQueryCount(latestRun)}</strong></span>
                  <span>{lang === "zh" ? "鍙敤缁撴灉" : "usable"} <strong>{latestRunCounts.succeededCount}</strong></span>
                  <span>{lang === "zh" ? "闇€澶嶆牳" : "review"} <strong>{aiSearchRunNeedsReviewCount(latestRun)}</strong></span>
                  <span>{lang === "zh" ? "澶辫触" : "failed"} <strong>{latestRunCounts.failedCount}</strong></span>
                  {latestRunCounts.degradedCount ? (
                    <span>{lang === "zh" ? "闄嶇骇" : "fallback"} <strong>{latestRunCounts.degradedCount}</strong></span>
                  ) : null}
                  <span>{lang === "zh" ? "寮曠敤" : "refs"} <strong>{latestRunCounts.referenceCount}</strong></span>
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
                              {card.groupLabel} 路 {aiSearchSourceTierLabel(card.tier, lang)} 路 {card.sourceType}
                              {cardModeLabel ? ` 路 ${cardModeLabel}` : ""}
                            </span>
                          </div>
                          <span>
                            {card.status === "failed" ? (lang === "zh" ? "澶辫触" : "failed") : cardNeedsReview ? (lang === "zh" ? "闇€澶嶆牳" : "review") : (lang === "zh" ? "鍙敤" : "usable")}
                          </span>
                        </div>
                        <div className={styles.aiSearchRunQuery}>
                          <span>{lang === "zh" ? "鎼滅储璇? : "Query"}</span>
                          <strong>{card.query}</strong>
                          {cardModeLabel ? <em>{cardModeLabel}</em> : null}
                        </div>
                        {card.degraded && fallbackReason ? (
                          <small className={styles.aiSearchRunFallbackReason}>
                            {lang === "zh" ? "涓绘悳绱㈤檷绾? : "Primary search fallback"}: {fallbackReason}
                          </small>
                        ) : null}
                        <p>{card.summary || (card.status === "failed" ? (lang === "zh" ? "鎼滅储鎵ц澶辫触锛屽凡淇濈暀澶辫触鍗＄墖銆? : "Search failed; the failed card was retained.") : card.query)}</p>
                        <div className={styles.aiSearchRunRefs}>
                          <small>{lang === "zh" ? "璇佹嵁閾炬帴" : "Evidence links"}</small>
                          {card.references.length ? (
                            card.references.slice(0, 3).map((reference) => (
                              <a key={`${card.cardId}-${reference.url}`} href={reference.url} target="_blank" rel="noreferrer">
                                {reference.title || reference.url}
                              </a>
                            ))
                          ) : (
                            <span>{lang === "zh" ? "鏆傛棤鍙偣寮€鐨勫弬鑰冩潵婧? : "No clickable references yet"}</span>
                          )}
                        </div>
                        {fallbackReason || card.resultText ? (
                          <details className={styles.aiSearchRunCardDetails}>
                            <summary>{lang === "zh" ? "鎵ц缁嗚妭" : "Execution detail"}</summary>
                            {fallbackReason ? <span>{fallbackReason}</span> : null}
                            {card.resultText ? <p>{card.resultText}</p> : null}
                          </details>
                        ) : null}
                      </article>
                    );
                  })}
                </div>
                <div className={styles.aiSearchRunStorage}>
                  <strong>{lang === "zh" ? "瀛樻斁浣嶇疆" : "Stored at"}</strong>
                  <span>{aiSearchRunPath(latestRun)}</span>
                </div>
              </div>
            ) : (
              <div className={shellStyles.empty}>
                {runsPending
                  ? (lang === "zh" ? "姝ｅ湪璇诲彇鏈€杩戞悳绱㈢粨鏋?.." : "Loading recent search results...")
                  : (lang === "zh" ? "杩樻病鏈夋悳绱㈣褰曘€傝緭鍏ヤ富棰樺悗鍚姩涓€杞悳绱紝缁撴灉浼氭寜鈥滄湰杞垽鏂€佽瘉鎹摼鎺ャ€佸瓨鏀句綅缃€濆睍绀恒€? : "No search records yet. Enter a topic and start a search round; results will show readout, evidence links, and storage.")}
              </div>
            )}
          </form>
          <details className={styles.aiSearchScopeDetails}>
            <summary>
              <span>{lang === "zh" ? "鏉ユ簮涓庢妧鏈竟鐣? : "Sources and technical boundary"}</span>
              <small>{lang === "zh" ? "鐧藉悕鍗曘€佸幓閲嶃€佸瓨鍌ㄨ矾寰? : "Allowlist, dedupe, storage path"}</small>
            </summary>
            <p className={styles.aiSearchScopeDescription}>{scope.description}</p>
            <div className={styles.aiSearchScopeStats}>
              <span>{lang === "zh" ? "鏉ユ簮鍒嗙粍" : "Groups"} <strong>{scope.summary.groupCount}</strong></span>
              <span>{lang === "zh" ? "榛樿鍚敤" : "Default on"} <strong>{scope.summary.enabledByDefaultCount}</strong></span>
              <span>{lang === "zh" ? "浠呯嚎绱? : "Signals"} <strong>{scope.summary.signalOnlyCount}</strong></span>
            </div>
            <div className={styles.aiSearchScopePolicy}>
              <span>{lang === "zh" ? "榛樿 Tier" : "Default tiers"}: {scope.policy.defaultEnabledTiers.join(", ")}</span>
              <span>{lang === "zh" ? "鍘婚噸" : "Dedupe"}: {scope.policy.dedupeBy.join(" / ")}</span>
              <span>{lang === "zh" ? "姝ｅ紡鐭ヨ瘑鍐欏叆" : "Formal write"}: {scope.policy.writesFormalKnowledge ? "on" : "off"}</span>
              <span>{scope.storage.path}</span>
            </div>
            <div className={styles.aiSearchSourceGroups}>
              {scope.groups.map((group) => (
                <article key={group.groupId} className={styles.aiSearchSourceGroup}>
                  <div className={styles.aiSearchSourceGroupHeader}>
                    <div>
                      <strong>{group.label}</strong>
                      <span>{aiSearchSourceTierLabel(group.tier, lang)} 路 {aiSearchSourceRoleLabel(group.evidenceRole, lang)}</span>
                    </div>
                    <span className={group.enabledByDefault ? styles.aiSearchScopeEnabled : styles.aiSearchScopeSignal}>
                      {group.enabledByDefault ? (lang === "zh" ? "榛樿鍚敤" : "enabled") : (lang === "zh" ? "绾跨储" : "signal")}
                    </span>
                  </div>
                  <p>{group.description}</p>
                  <div className={styles.aiSearchSourceList}>
                    {group.sources.map((source) => (
                      <a key={source.sourceId} href={source.url} target="_blank" rel="noreferrer" className={styles.aiSearchSourceItem}>
                        <strong>{source.name}</strong>
                        <span>{source.sourceType} 路 {source.region} 路 {source.language}</span>
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
            ? (lang === "zh" ? "姝ｅ湪璇诲彇 AI 鎼滅储鑼冨洿鍚嶅崟..." : "Loading AI search source scope...")
            : (lang === "zh" ? "褰撳墠鍥㈤槦璇︽儏娌℃湁杩斿洖 sourceScope銆? : "This Team detail did not return sourceScope.")}
        </div>
      )}
    </section>
  );
}
