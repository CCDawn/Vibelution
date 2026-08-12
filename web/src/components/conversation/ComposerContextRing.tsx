import { useMemo, useState, type CSSProperties } from "react";

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
};
const HIT_LABEL_EN: Record<ComposerContextHitKind, string> = {
  hit: "hit",
  miss: "miss",
  never: "uncacheable",
};

export type ComposerContextRingProps = {
  model: ComposerContextRingModel;
  lang: "zh" | "en";
  sessionId?: string | null;
  onOpenDetail?: () => void;
};

function segmentTip(segment: ComposerContextSegment, lang: "zh" | "en") {
  const hitLabel = (lang === "zh" ? HIT_LABEL_ZH : HIT_LABEL_EN)[segment.hit];
  return `${segment.name} · ${hitLabel} · ${segment.tokensLabel} · ${segment.pct}%`;
}

function hitShare(segments: ComposerContextSegment[]) {
  let hit = 0;
  let miss = 0;
  let never = 0;
  for (const segment of segments) {
    if (segment.hit === "hit") hit += segment.pct;
    else if (segment.hit === "miss") miss += segment.pct;
    else never += segment.pct;
  }
  return { hit, miss, never };
}

function ContourArcs({ segments }: { segments: ComposerContextSegment[] }) {
  const gap = 0.8;
  let cursor = 0;
  return (
    <>
      {segments.map((segment) => {
        const len = Math.max(0, segment.pct - gap);
        const start = cursor;
        cursor += segment.pct;
        const stroke = segment.hit === "hit"
          ? "var(--accent-cool)"
          : segment.hit === "miss"
            ? "var(--accent-warm)"
            : "color-mix(in srgb, var(--fg-tertiary) 55%, transparent)";
        // Always keep trailing as a gap slot: `0 start len trailing`
        // (never uses muted solid here; dashed never is shown on the hit-edge bar).
        const trailing = Math.max(0, 100 - start - len);
        return (
          <circle
            key={`contour-${segment.key}-${start}`}
            cx="16"
            cy="16"
            r="12.2"
            fill="none"
            stroke={stroke}
            strokeWidth="1.8"
            pathLength={100}
            strokeDasharray={`0 ${start} ${len} ${trailing}`}
            transform="rotate(-90 16 16)"
            opacity={segment.hit === "never" ? 0.85 : 1}
          />
        );
      })}
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
  const [hint, setHint] = useState("");
  const share = useMemo(() => hitShare(model.segments), [model.segments]);

  const usageDash = model.empty ? 0 : model.usagePercent;
  const ringTitle = model.empty
    ? (lang === "zh" ? "暂无上下文数据" : "No context data yet")
    : (lang === "zh"
      ? `占用 ${model.usagePercent}% · 命中 ${model.hitPercent}% · ${model.usedLabel}`
      : `Usage ${model.usagePercent}% · hit ${model.hitPercent}% · ${model.usedLabel}`);

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
            contentLayout="plain"
            className={styles.trigger}
            title={ringTitle}
            aria-label={ringTitle}
            data-empty={model.empty ? "true" : "false"}
            data-session={sessionId || undefined}
          >
            <svg className={styles.ring} viewBox="0 0 32 32" aria-hidden="true" overflow="visible">
              <circle
                cx="16"
                cy="16"
                r="9.6"
                fill="none"
                stroke="color-mix(in srgb, var(--vui-border-subtle) 90%, transparent)"
                strokeWidth="2.8"
              />
              <circle
                cx="16"
                cy="16"
                r="9.6"
                fill="none"
                stroke="var(--accent-cool)"
                strokeWidth="2.8"
                strokeLinecap="round"
                pathLength={100}
                strokeDasharray={`${usageDash} 100`}
                transform="rotate(-90 16 16)"
                opacity={model.empty ? 0.35 : 1}
              />
              {!model.empty ? <ContourArcs segments={model.segments} /> : null}
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
        <div className={styles.head}>
          <span className={styles.title}>{lang === "zh" ? "上下文" : "Context"}</span>
          <span className={styles.nums} title={model.usedLabel}>
            {model.empty
              ? <b>--</b>
              : (
                <>
                  <b>{model.usagePercent}%</b>
                  {" · "}
                  {lang === "zh" ? "命中" : "hit"}
                  {" "}
                  <b>{model.hitPercent}%</b>
                </>
              )}
          </span>
        </div>

        <div className={styles.stack}>
          <div
            className={styles.hitEdge}
            title={model.empty
              ? undefined
              : (lang === "zh"
                ? `命中 ${share.hit}% · 未命中 ${share.miss}% · 不可缓存 ${share.never}%`
                : `hit ${share.hit}% · miss ${share.miss}% · uncacheable ${share.never}%`)}
          >
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
          <div className={styles.compBar} title={model.usedLabel}>
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
        </div>

        <div className={styles.rows}>
          {model.empty ? (
            <div className={styles.row}>
              <span />
              <span className={styles.rowName}>{lang === "zh" ? "暂无组成" : "No composition yet"}</span>
              <span className={styles.rowValue}>--</span>
            </div>
          ) : model.segments.map((segment) => (
            <div
              key={`row-${segment.key}`}
              className={styles.row}
              title={segmentTip(segment, lang)}
              onMouseEnter={() => setHint(segmentTip(segment, lang))}
              onMouseLeave={() => setHint("")}
            >
              <span className={styles.swatch} style={{ background: segment.color }} />
              <span className={styles.rowName}>{segment.name}</span>
              <span className={styles.rowValue}>{segment.tokensLabel}</span>
            </div>
          ))}
        </div>

        <div className={styles.foot}>
          <span className={styles.hint}>{hint}</span>
          {onOpenDetail && model.detailAvailable ? (
            <VButton
              type="button"
              contentLayout="plain"
              className={styles.detailLink}
              title={lang === "zh" ? "打开完整缓存命中详情" : "Open full cache hit details"}
              onClick={() => {
                setOpen(false);
                onOpenDetail();
              }}
            >
              {lang === "zh" ? "详情" : "Details"}
            </VButton>
          ) : null}
        </div>
      </VPopover>
    </div>
  );
}
