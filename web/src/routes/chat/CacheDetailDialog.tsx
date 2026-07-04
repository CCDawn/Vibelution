import { X } from "lucide-react";
import type { CSSProperties } from "react";

import type { SessionCacheCompositionSegment } from "../../api/types";
import { VButton } from "../../components/vui";
import styles from "../ChatCodingRoute.styles";

export type CacheDonutSegment = SessionCacheCompositionSegment & {
  actualPercent: number;
  visualPercent: number;
  startPercent: number;
  visuallyAmplified: boolean;
};

type CacheBoundaryWidthVariable =
  | "--cache-boundary-hit-width"
  | "--cache-boundary-miss-width"
  | "--cache-boundary-unknown-width";

type CacheBoundaryFillStyle = CSSProperties & Partial<Record<CacheBoundaryWidthVariable, string>>;

type CacheDetailDialogProps = {
  averageCacheObservedTurnCount: number;
  cacheCompositionAverageLabel: string;
  cacheCompositionAverageValue: string;
  cacheCompositionPercent: number;
  cacheCompositionTitle: string;
  cacheCompositionUpperBoundLabel: string;
  cacheComputedOverestimatedInputTokens: number;
  cacheDetailDialogTitle: string;
  cachePromptCompositionTotalTokens: number;
  cachePromptDonutSegments: CacheDonutSegment[];
  cacheProviderExtraCachedInputTokens: number;
  cacheCalibrationReason: string;
  cacheCalibrationSummaryText: string;
  closeLabel: string;
  lang: "zh" | "en";
  missingSegmentLabel: string;
  numberFormatter: Intl.NumberFormat;
  onClose: () => void;
  previousCacheHitLabel: string;
  providerCachedInputTokens: number;
  providerCacheInputTokens: number;
  trueCacheDonutSegments: CacheDonutSegment[];
  upperBoundCachedInputTokens: number;
  upperBoundCacheCompositionPercent: number;
  upperBoundCacheInputTokens: number;
};

function promptSegmentCategory(segment: Pick<SessionCacheCompositionSegment, "key" | "promptCategory">) {
  const category = (segment.promptCategory || "").trim();
  if (category) {
    return category;
  }
  switch ((segment.key || "").trim()) {
    case "system_prompt":
    case "system_prompt_overhead":
      return "system_prompt";
    case "agent_protocol":
    case "agent_runtime":
    case "prompt_template":
      return "agent_spec";
    case "project_rules":
      return "developer_instructions";
    case "tool_descriptions":
      return "tool_descriptions";
    case "tool_schema":
      return "tool_schema";
    case "provider_unmapped":
      return "provider_unmapped";
    case "current_user":
      return "current_user";
    case "history":
      return "history";
    case "active_task":
      return "task_state";
    case "guidance":
      return "operator_guidance";
    case "skill":
    case "active_skill":
      return "skill_context";
    case "attachments":
      return "attachments";
    default:
      return segment.key || "context";
  }
}

function cacheDonutSegmentClass(keyOrStatus: string) {
  switch (keyOrStatus) {
    case "cached":
    case "hit":
    case "computed_hit":
      return styles.cacheDonutSegmentCached;
    case "cache_write":
    case "write":
    case "computed_write":
      return styles.cacheDonutSegmentCacheWrite;
    case "uncached":
    case "miss":
    case "computed_miss":
      return styles.cacheDonutSegmentUncached;
    case "missing":
    case "computed_unknown":
      return styles.cacheDonutSegmentMissing;
    default:
      return styles.cacheDonutSegmentOther;
  }
}

function cachePromptSegmentClass(segment: Pick<SessionCacheCompositionSegment, "key" | "promptCategory">) {
  switch (promptSegmentCategory(segment)) {
    case "system_prompt":
      return styles.cacheDonutSegmentSystem;
    case "agent_spec":
    case "agent_context":
      return styles.cacheDonutSegmentAgent;
    case "developer_instructions":
    case "project_context":
      return styles.cacheDonutSegmentProjectRules;
    case "tool_descriptions":
      return styles.cacheDonutSegmentToolDescriptions;
    case "tool_schema":
      return styles.cacheDonutSegmentToolSchema;
    case "provider_unmapped":
      return styles.cacheDonutSegmentProviderUnmapped;
    case "current_user":
      return styles.cacheDonutSegmentUser;
    case "history":
      return styles.cacheDonutSegmentHistory;
    case "task_state":
      return styles.cacheDonutSegmentTask;
    case "operator_guidance":
      return styles.cacheDonutSegmentGuidance;
    case "skill_context":
      return styles.cacheDonutSegmentSkill;
    case "attachments":
      return styles.cacheDonutSegmentAttachments;
    default:
      return styles.cacheDonutSegmentOther;
  }
}

function cachePromptLegendSegmentClass(segment: Pick<SessionCacheCompositionSegment, "key" | "promptCategory">) {
  switch (promptSegmentCategory(segment)) {
    case "system_prompt":
      return styles.contextCompositionSegmentSystem;
    case "agent_spec":
    case "agent_context":
      return styles.contextCompositionSegmentAgent;
    case "developer_instructions":
    case "project_context":
      return styles.contextCompositionSegmentProjectRules;
    case "tool_descriptions":
      return styles.contextCompositionSegmentToolDescriptions;
    case "tool_schema":
      return styles.contextCompositionSegmentToolSchema;
    case "provider_unmapped":
      return styles.contextCompositionSegmentProviderUnmapped;
    case "current_user":
      return styles.contextCompositionSegmentUser;
    case "history":
      return styles.contextCompositionSegmentHistory;
    case "task_state":
      return styles.contextCompositionSegmentTask;
    case "operator_guidance":
      return styles.contextCompositionSegmentGuidance;
    case "skill_context":
      return styles.contextCompositionSegmentSkill;
    case "attachments":
      return styles.contextCompositionSegmentAttachments;
    default:
      return styles.contextCompositionSegmentOther;
  }
}

function promptSegmentCategoryLabel(segment: Pick<SessionCacheCompositionSegment, "key" | "promptCategory">, lang: "zh" | "en") {
  switch (promptSegmentCategory(segment)) {
    case "system_prompt":
      return lang === "zh" ? "系统" : "system";
    case "agent_spec":
    case "agent_context":
      return lang === "zh" ? "Agent 规范" : "agent spec";
    case "developer_instructions":
      return lang === "zh" ? "项目/开发规范" : "developer rules";
    case "project_context":
      return lang === "zh" ? "项目上下文" : "project context";
    case "tool_descriptions":
      return lang === "zh" ? "工具描述" : "tool descriptions";
    case "tool_schema":
      return lang === "zh" ? "工具 schema" : "tool schema";
    case "provider_unmapped":
      return lang === "zh" ? "未映射" : "unmapped";
    case "history":
      return lang === "zh" ? "历史" : "history";
    case "current_user":
      return lang === "zh" ? "本轮输入" : "current input";
    case "operator_guidance":
      return lang === "zh" ? "操作指导" : "guidance";
    case "skill_context":
      return lang === "zh" ? "技能上下文" : "skill context";
    case "attachments":
      return lang === "zh" ? "附件" : "attachments";
    default:
      return lang === "zh" ? "上下文" : "context";
  }
}

function promptSegmentAccuracyLabel(segment: Pick<SessionCacheCompositionSegment, "accuracy" | "estimated">, lang: "zh" | "en") {
  if (segment.estimated || segment.accuracy === "estimated") {
    return lang === "zh" ? "估算" : "estimated";
  }
  if (segment.accuracy === "manifest") {
    return "manifest";
  }
  return "";
}

function cacheObservedStatusLabel(status: string | undefined, lang: "zh" | "en") {
  switch ((status || "").trim()) {
    case "observed_hit":
      return lang === "zh" ? "厂商命中" : "provider hit";
    case "observed_partial":
      return lang === "zh" ? "部分命中" : "partial hit";
    case "observed_miss":
      return lang === "zh" ? "厂商未命中" : "provider miss";
    case "computed_write":
      return lang === "zh" ? "上界写入" : "upper-bound write";
    case "computed_miss":
      return lang === "zh" ? "上界未命中" : "upper-bound miss";
    case "not_observed":
      return lang === "zh" ? "未观测" : "not observed";
    default:
      return lang === "zh" ? "未标记" : "unmarked";
  }
}

function cacheComputedStatusLabel(status: string | undefined, lang: "zh" | "en") {
  switch ((status || "").trim()) {
    case "computed_hit":
      return lang === "zh" ? "上界命中" : "upper-bound hit";
    case "computed_write":
      return lang === "zh" ? "上界写入" : "upper-bound write";
    case "computed_miss":
      return lang === "zh" ? "上界未命中" : "upper-bound miss";
    case "computed_unknown":
      return lang === "zh" ? "上界未知" : "upper-bound unknown";
    case "provider_extra_hit":
      return lang === "zh" ? "厂商额外命中" : "provider extra hit";
    default:
      return status || (lang === "zh" ? "未知" : "unknown");
  }
}

function cacheDonutSegmentTitle(
  segment: CacheDonutSegment,
  totalTokens: number,
  numberFormatter: Intl.NumberFormat,
  lang: "zh" | "en",
) {
  const percent = Math.round(segment.actualPercent);
  const parts = [
    `${segment.label || segment.key}: ${numberFormatter.format(segment.tokens)} / ${numberFormatter.format(totalTokens)} · ${percent}%`,
    segment.observedStatus ? `${lang === "zh" ? "真实状态" : "observed"} ${cacheObservedStatusLabel(segment.observedStatus, lang)}` : "",
    segment.observedCachedInputTokens ? `${lang === "zh" ? "真实命中" : "observed hit"} ${numberFormatter.format(segment.observedCachedInputTokens)}` : "",
    segment.observedMissedInputTokens ? `${lang === "zh" ? "真实未命中" : "observed miss"} ${numberFormatter.format(segment.observedMissedInputTokens)}` : "",
    segment.computedOverestimatedInputTokens ? `${lang === "zh" ? "上界未兑现" : "upper bound not observed"} ${numberFormatter.format(segment.computedOverestimatedInputTokens)}` : "",
    segment.cachePolicy ? `${lang === "zh" ? "缓存策略" : "cache policy"} ${segment.cachePolicy}` : "",
    segment.source ? `${lang === "zh" ? "来源" : "source"} ${segment.source}` : "",
    segment.contentPreview ? `${lang === "zh" ? "内容" : "content"} ${segment.contentPreview}` : "",
    segment.calibrationReason || "",
    segment.description || "",
    segment.visuallyAmplified ? (lang === "zh" ? "视觉段已放大，便于鼠标锁定。" : "Visual arc is amplified for hover targeting.") : "",
  ];
  return parts.filter(Boolean).join(" · ");
}

function cachePromptSegmentHoverTitle(
  segment: CacheDonutSegment,
  totalTokens: number,
  numberFormatter: Intl.NumberFormat,
  lang: "zh" | "en",
  missingSegmentLabel: string,
) {
  const label = segment.key === "computed_missing"
    ? missingSegmentLabel
    : segment.label || segment.key;
  const percent = Math.round(segment.actualPercent);
  const amplifiedLabel = segment.visuallyAmplified
    ? lang === "zh" ? "小段已放大便于定位" : "small segment enlarged"
    : "";
  return [
    `${label} · ${numberFormatter.format(segment.tokens)} tokens · ${percent}%`,
    totalTokens > 0 ? `${numberFormatter.format(segment.tokens)} / ${numberFormatter.format(totalTokens)}` : "",
    amplifiedLabel,
  ].filter(Boolean).join(" · ");
}

function cacheDonutSegmentStyle(segment: CacheDonutSegment, gapPercent = 0): CSSProperties {
  const gap = Math.max(0, Math.min(1, gapPercent));
  const visiblePercent = segment.visualPercent > gap
    ? Math.max(0.45, segment.visualPercent - gap)
    : segment.visualPercent;
  const offset = -(segment.startPercent + (segment.visualPercent > gap ? gap / 2 : 0));
  return {
    strokeDasharray: `${visiblePercent} ${Math.max(0, 100 - visiblePercent)}`,
    strokeDashoffset: offset,
  };
}

function cacheBoundaryFillStyle(variable: CacheBoundaryWidthVariable, percent: number): CacheBoundaryFillStyle {
  return { [variable]: `${percent}%` } as CacheBoundaryFillStyle;
}

export function CacheDetailDialog({
  averageCacheObservedTurnCount,
  cacheCompositionAverageLabel,
  cacheCompositionAverageValue,
  cacheCompositionPercent,
  cacheCompositionTitle,
  cacheCompositionUpperBoundLabel,
  cacheComputedOverestimatedInputTokens,
  cacheDetailDialogTitle,
  cachePromptCompositionTotalTokens,
  cachePromptDonutSegments,
  cacheProviderExtraCachedInputTokens,
  cacheCalibrationReason,
  cacheCalibrationSummaryText,
  closeLabel,
  lang,
  missingSegmentLabel,
  numberFormatter,
  onClose,
  previousCacheHitLabel,
  providerCachedInputTokens,
  providerCacheInputTokens,
  trueCacheDonutSegments,
  upperBoundCachedInputTokens,
  upperBoundCacheCompositionPercent,
  upperBoundCacheInputTokens,
}: CacheDetailDialogProps) {
  return (
    <div className={styles.cacheDetailOverlay} role="presentation" onClick={onClose}>
      <section
        id="cache-detail-dialog"
        className={styles.cacheDetailDialog}
        role="dialog"
        aria-modal="true"
        aria-label={cacheDetailDialogTitle}
        onClick={(event) => event.stopPropagation()}
      >
        <header className={styles.cacheDetailHeader}>
          <div>
            <p>{previousCacheHitLabel}</p>
            <h3>{cacheDetailDialogTitle}</h3>
          </div>
          <VButton
            type="button"
            className={styles.cacheDetailCloseButton}
            onClick={onClose}
            aria-label={closeLabel}
          >
            <X size={16} />
          </VButton>
        </header>

        <div className={styles.cacheDetailSummaryGrid}>
          <div>
            <span>{lang === "zh" ? "真实命中" : "True hit"}</span>
            <strong>{cacheCompositionPercent}%</strong>
            <small>{numberFormatter.format(providerCachedInputTokens)} / {numberFormatter.format(providerCacheInputTokens)}</small>
          </div>
          <div>
            <span>{lang === "zh" ? "计算命中" : "Computed hit"}</span>
            <strong>{upperBoundCacheCompositionPercent}%</strong>
            <small>{numberFormatter.format(upperBoundCachedInputTokens)} / {numberFormatter.format(upperBoundCacheInputTokens)}</small>
          </div>
          <div>
            <span>{lang === "zh" ? "总平均命中" : "Average hit"}</span>
            <strong>{cacheCompositionAverageValue}</strong>
            <small>{lang === "zh" ? "轮次" : "turns"} {numberFormatter.format(averageCacheObservedTurnCount)}</small>
          </div>
        </div>

        {cacheCalibrationReason || cacheComputedOverestimatedInputTokens > 0 || cacheProviderExtraCachedInputTokens > 0 ? (
          <div className={styles.cacheDetailCalibrationNote} title={cacheCalibrationReason || cacheCalibrationSummaryText}>
            <strong>{lang === "zh" ? "厂商校准" : "Provider calibration"}</strong>
            <span>{cacheCalibrationSummaryText}</span>
            <em>
              {cacheComputedOverestimatedInputTokens > 0 ? `${lang === "zh" ? "上界未兑现" : "upper bound not observed"} ${numberFormatter.format(cacheComputedOverestimatedInputTokens)}` : ""}
              {cacheComputedOverestimatedInputTokens > 0 && cacheProviderExtraCachedInputTokens > 0 ? " · " : ""}
              {cacheProviderExtraCachedInputTokens > 0 ? `${lang === "zh" ? "厂商额外命中" : "provider extra hit"} ${numberFormatter.format(cacheProviderExtraCachedInputTokens)}` : ""}
            </em>
          </div>
        ) : null}

        <div className={styles.cacheDetailBody}>
          <div className={styles.cacheDetailDonutPanel}>
            <div className={styles.cacheDetailDonutShell}>
              <svg
                className={`${styles.cacheDonutSvg} ${styles.cacheDetailDonutSvg}`}
                viewBox="0 0 100 100"
                role="img"
                aria-label={cacheCompositionTitle}
              >
                <circle className={`${styles.cacheDonutTrack} ${styles.cacheDonutOuterTrack}`} cx="50" cy="50" r="42" pathLength={100} />
                {cachePromptDonutSegments.map((segment, index) => (
                  <circle
                    key={`detail-computed-${segment.key}-${segment.status}-${index}`}
                    className={`${styles.cacheDonutSegment} ${styles.cacheDonutOuterSegment} ${cachePromptSegmentClass(segment)}`}
                    cx="50"
                    cy="50"
                    r="42"
                    pathLength={100}
                    style={cacheDonutSegmentStyle(segment, cachePromptDonutSegments.length > 1 ? 0.55 : 0)}
                  >
                    <title>{cachePromptSegmentHoverTitle(segment, cachePromptCompositionTotalTokens, numberFormatter, lang, missingSegmentLabel)}</title>
                  </circle>
                ))}
                <circle className={`${styles.cacheDonutTrack} ${styles.cacheDonutInnerTrack}`} cx="50" cy="50" r="31" pathLength={100} />
                {trueCacheDonutSegments.map((segment, index) => (
                  <circle
                    key={`detail-true-${segment.key}-${segment.status}-${index}`}
                    className={`${styles.cacheDonutSegment} ${styles.cacheDonutInnerSegment} ${cacheDonutSegmentClass(segment.status || segment.key)}`}
                    cx="50"
                    cy="50"
                    r="31"
                    pathLength={100}
                    style={cacheDonutSegmentStyle(segment, trueCacheDonutSegments.length > 1 ? 0.4 : 0)}
                  >
                    <title>{cacheDonutSegmentTitle(segment, providerCacheInputTokens, numberFormatter, lang)}</title>
                  </circle>
                ))}
              </svg>
              <div className={`${styles.cacheDonutCenter} ${styles.cacheDetailDonutCenter}`} title={cacheCompositionTitle}>
                <strong>{cacheCompositionPercent}%</strong>
                <span>{cacheCompositionUpperBoundLabel} {upperBoundCacheCompositionPercent}%</span>
                <small>{cacheCompositionAverageLabel} {cacheCompositionAverageValue}</small>
              </div>
            </div>
            <div className={styles.cacheDetailDonutLegend}>
              <span><b>{lang === "zh" ? "外环" : "outer"}</b>{lang === "zh" ? "提示词来源 / 上界分段" : "prompt sources / upper bound"}</span>
              <span><b>{lang === "zh" ? "内环" : "inner"}</b>{lang === "zh" ? "厂商真实命中" : "provider hits"}</span>
            </div>
          </div>

          <div className={styles.cacheDetailSegmentList}>
            <section className={styles.cacheDetailSegmentGroup}>
              <div className={styles.cacheDetailSegmentHeader}>
                <strong>{lang === "zh" ? "提示词分段命中边界" : "Prompt segment hit boundary"}</strong>
                <span>{numberFormatter.format(cachePromptCompositionTotalTokens)} tokens</span>
              </div>
              {cachePromptDonutSegments.length ? (
                cachePromptDonutSegments.map((segment, index) => {
                  const segmentDisplayLabel = segment.key === "computed_missing"
                    ? missingSegmentLabel
                    : segment.label || segment.key;
                  const observedCachedTokens = Math.max(0, segment.observedCachedInputTokens ?? 0);
                  const observedMissedTokens = Math.max(0, segment.observedMissedInputTokens ?? 0);
                  const observedMeasuredTokens = observedCachedTokens + observedMissedTokens;
                  const observedBoundaryTotal = Math.max(observedMeasuredTokens, segment.tokens ?? 0, 1);
                  const observedUnknownTokens = Math.max(0, observedBoundaryTotal - observedMeasuredTokens);
                  const observedCachedPercent = Math.round((observedCachedTokens / observedBoundaryTotal) * 1000) / 10;
                  const observedMissedPercent = Math.round((observedMissedTokens / observedBoundaryTotal) * 1000) / 10;
                  const observedUnknownPercent = Math.max(
                    0,
                    Math.round((100 - observedCachedPercent - observedMissedPercent) * 10) / 10,
                  );
                  const observedBoundaryTitle = [
                    `${lang === "zh" ? "命中" : "hit"} ${numberFormatter.format(observedCachedTokens)}`,
                    `${lang === "zh" ? "未命中" : "miss"} ${numberFormatter.format(observedMissedTokens)}`,
                    observedUnknownTokens > 0 ? `${lang === "zh" ? "未观测" : "unobserved"} ${numberFormatter.format(observedUnknownTokens)}` : "",
                  ].filter(Boolean).join(" · ");
                  return (
                    <div
                      key={`detail-computed-row-${segment.key}-${segment.status}-${index}`}
                      className={styles.cacheDetailSegmentRow}
                      title={cacheDonutSegmentTitle(segment, cachePromptCompositionTotalTokens, numberFormatter, lang)}
                    >
                      <i className={`${styles.cacheDetailSwatch} ${cachePromptLegendSegmentClass(segment)}`} />
                      <div className={styles.cacheDetailSegmentText}>
                        <strong>{segmentDisplayLabel}</strong>
                        <span className={styles.cacheDetailSegmentSource}>
                          {promptSegmentCategoryLabel(segment, lang)}
                          {promptSegmentAccuracyLabel(segment, lang) ? ` · ${promptSegmentAccuracyLabel(segment, lang)}` : ""}
                          {segment.cachePolicy ? ` · ${segment.cachePolicy}` : ""}
                        </span>
                        <span className={styles.cacheDetailSegmentMeta}>
                          <b>{cacheComputedStatusLabel(segment.status, lang)}</b>
                          <b data-status={segment.observedStatus || "not_observed"}>
                            {cacheObservedStatusLabel(segment.observedStatus, lang)}
                          </b>
                          {(segment.computedOverestimatedInputTokens ?? 0) > 0 ? (
                            <b data-status="observed_miss">
                              {lang === "zh" ? "上界未兑现" : "upper bound gap"} {numberFormatter.format(segment.computedOverestimatedInputTokens ?? 0)}
                            </b>
                          ) : null}
                          {(segment.providerExtraCachedInputTokens ?? 0) > 0 ? (
                            <b data-status="observed_hit">
                              {lang === "zh" ? "厂商额外" : "provider extra"} {numberFormatter.format(segment.providerExtraCachedInputTokens ?? 0)}
                            </b>
                          ) : null}
                        </span>
                        <div className={styles.cacheDetailBoundary} title={observedBoundaryTitle}>
                          <div className={styles.cacheDetailBoundaryLabels}>
                            <span data-kind="hit">
                              {lang === "zh" ? "命中" : "hit"} {numberFormatter.format(observedCachedTokens)}
                            </span>
                            <span data-kind="miss">
                              {lang === "zh" ? "未命中" : "miss"} {numberFormatter.format(observedMissedTokens)}
                            </span>
                            {observedUnknownTokens > 0 ? (
                              <span data-kind="unknown">
                                {lang === "zh" ? "未观测" : "unobserved"} {numberFormatter.format(observedUnknownTokens)}
                              </span>
                            ) : null}
                          </div>
                          <div
                            className={styles.cacheDetailBoundaryTrack}
                            role="img"
                            aria-label={observedBoundaryTitle}
                          >
                            <span
                              className={styles.cacheDetailBoundaryHit}
                              style={cacheBoundaryFillStyle("--cache-boundary-hit-width", observedCachedPercent)}
                            />
                            <span
                              className={styles.cacheDetailBoundaryMiss}
                              style={cacheBoundaryFillStyle("--cache-boundary-miss-width", observedMissedPercent)}
                            />
                            {observedUnknownTokens > 0 ? (
                              <span
                                className={styles.cacheDetailBoundaryUnknown}
                                style={cacheBoundaryFillStyle("--cache-boundary-unknown-width", observedUnknownPercent)}
                              />
                            ) : null}
                          </div>
                        </div>
                        {segment.contentPreview ? <small>{segment.contentPreview}</small> : null}
                      </div>
                      <em>
                        {numberFormatter.format(segment.tokens ?? 0)} · {Math.round(segment.actualPercent)}%
                        {(segment.observedCachedInputTokens ?? 0) > 0 || (segment.observedMissedInputTokens ?? 0) > 0 ? (
                          <small>
                            {lang === "zh" ? "真" : "obs"} {numberFormatter.format(segment.observedCachedInputTokens ?? 0)}
                            {" / "}
                            {numberFormatter.format(segment.observedMissedInputTokens ?? 0)}
                          </small>
                        ) : null}
                      </em>
                    </div>
                  );
                })
              ) : (
                <div className={styles.cacheDetailEmpty}>{lang === "zh" ? "暂无上界分段数据" : "No upper-bound segment data"}</div>
              )}
            </section>
          </div>
        </div>
      </section>
    </div>
  );
}
