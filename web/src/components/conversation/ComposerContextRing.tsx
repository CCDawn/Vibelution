import { useState, type CSSProperties } from "react";
import { ChevronDown } from "lucide-react";

import { VButton, VPopover } from "../vui";
import type {
  ComposerContextHitKind,
  ComposerContextRingModel,
  ComposerContextSegment,
} from "../../routes/chat/composerContextModel";
import styles from "./ComposerContextRing.styles";

const HIT_LABEL_ZH: Record<ComposerContextHitKind, string> = {
  hit: "命中",
  miss: "未命中",
  never: "不可缓存",
  unknown: "未观测",
};
const HIT_LABEL_EN: Record<ComposerContextHitKind, string> = {
  hit: "hit",
  miss: "miss",
  never: "uncacheable",
  unknown: "unobserved",
};
const CACHE_STATE_LABEL_ZH = {
  missing: "上游未返回缓存命中",
  not_called: "本轮未调用模型",
} as const;
const CACHE_STATE_LABEL_EN = {
  missing: "upstream cache usage missing",
  not_called: "model not called this turn",
} as const;
const HIT_ORDER: ComposerContextHitKind[] = ["hit", "miss", "never", "unknown"];

export type ComposerContextRingProps = {
  model: ComposerContextRingModel;
  lang: "zh" | "en";
  sessionId?: string | null;
  onOpenDetail?: () => void;
};

export type ComposerContextRingPanelProps = {
  model: ComposerContextRingModel;
  lang: "zh" | "en";
  onOpenDetail?: () => void;
};

function segmentTip(segment: ComposerContextSegment, lang: "zh" | "en") {
  const hitLabel = (lang === "zh" ? HIT_LABEL_ZH : HIT_LABEL_EN)[segment.hit];
  return `${segment.name} · ${hitLabel} · ${segment.tokensLabel} · ${segment.pctLabel}`;
}

function cacheHeadline(model: ComposerContextRingModel, lang: "zh" | "en") {
  if (model.cacheState === "observed") {
    return lang === "zh"
      ? `上轮真实命中 ${model.hitPercent}%`
      : `Last-turn true hit ${model.hitPercent}%`;
  }
  return (lang === "zh" ? CACHE_STATE_LABEL_ZH : CACHE_STATE_LABEL_EN)[model.cacheState];
}

export function ComposerContextRingPanel({
  model,
  lang,
  onOpenDetail,
}: ComposerContextRingPanelProps) {
  const [hint, setHint] = useState("");
  const [expandedKey, setExpandedKey] = useState("");
  const hitLabels = lang === "zh" ? HIT_LABEL_ZH : HIT_LABEL_EN;

  return (
    <>
      <div className={styles.head}>
        <span className={styles.title}>{lang === "zh" ? "上下文" : "Context"}</span>
        <span className={styles.nums} title={model.usedLabel}>
          {model.empty
            ? <b>--</b>
            : (
              <>
                <b>{model.usagePercent}%</b>
                {" · "}
                {model.usedLabel}
              </>
            )}
        </span>
      </div>

      <div className={styles.compositionSection} data-composer-context-composition="true">
        <span className={styles.sectionTitle}>{lang === "zh" ? "上下文构成" : "Composition"}</span>
        <div
          className={styles.compBar}
          title={model.empty ? undefined : model.usedLabel}
        >
          {model.segments.map((segment) => (
            <i
              key={`comp-${segment.key}`}
              className={styles.compSeg}
              style={{
                flex: `${Math.max(segment.pct, 0.1)} 0 0`,
                background: segment.color,
              } as CSSProperties}
              title={segmentTip(segment, lang)}
              onMouseEnter={() => setHint(segmentTip(segment, lang))}
              onMouseLeave={() => setHint("")}
            />
          ))}
        </div>

        <div className={styles.rows}>
          {model.empty ? (
            <div className={styles.rowEmpty}>
              <span />
              <span className={styles.rowName}>{lang === "zh" ? "暂无组成" : "No composition yet"}</span>
              <span className={styles.rowValue}>--</span>
            </div>
          ) : model.segments.map((segment) => {
            const expandable = Boolean(segment.contentPreview);
            const expanded = expandable && expandedKey === segment.key;
            const content = (
              <>
                <span className={styles.swatch} style={{ background: segment.color }} />
                <span className={styles.rowName}>{segment.name}</span>
                <span className={styles.rowPct} data-context-pct="true">{segment.pctLabel}</span>
                <span className={styles.rowValue}>{segment.tokensLabel}</span>
                <span
                  className={`${styles.rowBadge} ${styles[`rowBadge_${segment.hit}`]}`}
                  data-context-badge={segment.hit}
                >
                  {hitLabels[segment.hit]}
                </span>
                {expandable ? (
                  <ChevronDown
                    className={`${styles.rowChevron} ${expanded ? styles.rowChevronOpen : ""}`}
                    aria-hidden="true"
                  />
                ) : null}
              </>
            );
            return (
              <div key={`row-${segment.key}`} className={styles.rowGroup}>
                {expandable ? (
                  <VButton
                    type="button"
                    variant="ghost"
                    contentLayout="plain"
                    className={styles.rowButton}
                    data-context-row={segment.key}
                    data-context-hit={segment.hit}
                    aria-expanded={expanded}
                    title={segmentTip(segment, lang)}
                    onMouseEnter={() => setHint(segmentTip(segment, lang))}
                    onMouseLeave={() => setHint("")}
                    onClick={() => setExpandedKey(expanded ? "" : segment.key)}
                  >
                    {content}
                  </VButton>
                ) : (
                  <div
                    className={styles.row}
                    data-context-row={segment.key}
                    data-context-hit={segment.hit}
                    title={segmentTip(segment, lang)}
                    onMouseEnter={() => setHint(segmentTip(segment, lang))}
                    onMouseLeave={() => setHint("")}
                  >
                    {content}
                  </div>
                )}
                {expanded ? (
                  <div className={styles.rowPreview} data-context-preview={segment.key}>
                    {segment.contentPreview}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>

      <div
        className={styles.cacheSection}
        data-composer-context-cache="true"
        data-cache-state={model.cacheState}
      >
        <div className={styles.cacheHead}>
          <span className={styles.sectionTitle}>{lang === "zh" ? "缓存" : "Cache"}</span>
          <span className={styles.cacheHeadline}>{cacheHeadline(model, lang)}</span>
        </div>
        <div className={styles.hitEdge}>
          {model.segments.map((segment) => (
            <i
              key={`hit-${segment.key}`}
              className={`${styles.hitSeg} ${styles[`hitSeg_${segment.hit}`]}`}
              style={{ flex: `${Math.max(segment.pct, 0.1)} 0 0` }}
              title={segmentTip(segment, lang)}
              onMouseEnter={() => setHint(segmentTip(segment, lang))}
              onMouseLeave={() => setHint("")}
            />
          ))}
        </div>
        <div className={styles.cacheLegend}>
          {HIT_ORDER.map((kind) => {
            const share = Math.round(model.hitShares[kind] * 10) / 10;
            if (share <= 0) {
              return null;
            }
            return (
              <span key={kind} className={styles.cacheLegendItem} data-cache-kind={kind}>
                <i className={`${styles.legendDot} ${styles[`legendDot_${kind}`]}`} aria-hidden="true" />
                {hitLabels[kind]} {share}%
              </span>
            );
          })}
        </div>
      </div>

      <div className={styles.foot}>
        <span className={styles.hint}>{hint}</span>
        {onOpenDetail && model.detailAvailable ? (
          <VButton
            type="button"
            contentLayout="plain"
            className={styles.detailLink}
            title={lang === "zh" ? "打开完整缓存命中详情" : "Open full cache hit details"}
            onClick={onOpenDetail}
          >
            {lang === "zh" ? "详情" : "Details"}
          </VButton>
        ) : null}
      </div>
    </>
  );
}

export function ComposerContextRing({
  model,
  lang,
  sessionId = "",
  onOpenDetail,
}: ComposerContextRingProps) {
  const [open, setOpen] = useState(false);

  const usageDash = model.empty ? 0 : model.usagePercent;
  const ringTitle = model.empty
    ? (lang === "zh" ? "暂无上下文数据" : "No context data yet")
    : (lang === "zh"
      ? `占用 ${model.usagePercent}% · ${model.usedLabel}`
      : `Usage ${model.usagePercent}% · ${model.usedLabel}`);

  return (
    <div className={styles.root} data-testid="composer-context-ring">
      <VPopover
        open={open}
        onOpenChange={setOpen}
        side="top"
        align="end"
        sideOffset={10}
        aria-label={lang === "zh" ? "上下文组成" : "Context composition"}
        contentClassName={styles.popover}
        trigger={(
          <VButton
            type="button"
            variant="ghost"
            isIconOnly
            contentLayout="plain"
            className={styles.trigger}
            title={ringTitle}
            aria-label={ringTitle}
            data-chrome="bare"
            data-empty={model.empty ? "true" : "false"}
            data-session={sessionId || undefined}
          >
            <svg className={styles.ring} viewBox="0 0 32 32" aria-hidden="true">
              <circle
                cx="16"
                cy="16"
                r="10.4"
                fill="none"
                stroke="color-mix(in srgb, var(--accent-cool) 18%, transparent)"
                strokeWidth="2.4"
              />
              <circle
                cx="16"
                cy="16"
                r="10.4"
                fill="none"
                stroke="var(--accent-cool)"
                strokeWidth="2.4"
                strokeLinecap="round"
                pathLength={100}
                strokeDasharray={`${usageDash} 100`}
                transform="rotate(-90 16 16)"
                opacity={model.empty ? 0.35 : 1}
              />
              <text
                x="16"
                y="16.5"
                textAnchor="middle"
                dominantBaseline="central"
                fontSize={model.empty ? 9 : 8}
                fontWeight={750}
                fill={model.empty ? "var(--fg-tertiary)" : "var(--fg-primary)"}
              >
                {model.empty ? "--" : String(Math.round(model.usagePercent))}
              </text>
            </svg>
          </VButton>
        )}
      >
        <ComposerContextRingPanel
          model={model}
          lang={lang}
          onOpenDetail={onOpenDetail
            ? () => {
              setOpen(false);
              onOpenDetail();
            }
            : undefined}
        />
      </VPopover>
    </div>
  );
}
