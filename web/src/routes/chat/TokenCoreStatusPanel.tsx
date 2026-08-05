import { useId, type CSSProperties } from "react";

import { VButton, VTooltip, type VButtonProps } from "../../components/vui";
import routeStyles from "../ChatCodingRoute.styles";
import styles from "./TokenCoreStatusPanel.styles";

export type TokenCoreStatusMetric = {
  key: "cache" | "modelInput" | "compression" | "speed";
  label: string;
  value: string;
  displayValue?: string;
  meta: string;
  /** Flat title for a11y / legacy; prefer titleLines for hover layout. */
  title: string;
  /** High-value hover rows (max ~3); rendered as stacked lines, not · soup. */
  titleLines?: string[];
  percent: number;
  tone: "cache" | "modelInput" | "compression" | "speed";
};

type TokenCoreStatusPanelProps = {
  cacheDetailAvailable: boolean;
  cacheDetailOpen: boolean;
  cacheDetailOpenLabel: string;
  lang: "zh" | "en";
  metrics: TokenCoreStatusMetric[];
  onOpenCacheDetail: () => void;
  /** Short scope chip, e.g. last-turn telemetry. */
  scopeLabel?: string;
  scopeTitle?: string;
};

function tokenMetricShortLabel(metric: TokenCoreStatusMetric, lang: "zh" | "en") {
  if (lang === "zh") {
    switch (metric.key) {
      case "cache":
        return "缓存";
      case "modelInput":
        return "输入";
      case "compression":
        return "压缩";
      case "speed":
        return "速度";
      default:
        return metric.label;
    }
  }
  switch (metric.key) {
    case "cache":
      return "Cache";
    case "modelInput":
      return "Input";
    case "compression":
      return "Zip";
    case "speed":
      return "Speed";
    default:
      return metric.label;
  }
}

export function TokenCoreStatusPanel({
  cacheDetailAvailable,
  cacheDetailOpen,
  cacheDetailOpenLabel,
  lang,
  metrics,
  onOpenCacheDetail,
  scopeLabel,
  scopeTitle,
}: TokenCoreStatusPanelProps) {
  const panelId = useId();
  const titleId = `${panelId}-title`;
  const resolvedScopeLabel = scopeLabel
    ?? (lang === "zh" ? "上轮" : "Last turn");
  const resolvedScopeTitle = scopeTitle
    ?? (lang === "zh"
      ? "缓存与输入来自上一轮落库；压缩看当前会话；速度仅在流式时估算。"
      : "Cache and input come from the last persisted turn; compression is active-session only; speed is estimated while streaming.");

  return (
    <section className={`${routeStyles.leftBlock} ${styles.tokenCompressionCard}`} aria-labelledby={titleId}>
      <div className={routeStyles.sectionHeader}>
        <h3 id={titleId} className={routeStyles.railSectionHeading}>Token</h3>
        <span className={styles.tokenStatusScope} title={resolvedScopeTitle}>
          {resolvedScopeLabel}
        </span>
      </div>
      <div className={styles.tokenStatusVisualGrid} role="list" aria-label={lang === "zh" ? "Token 核心状态" : "Token core status"}>
        {metrics.map((metric) => {
          const metricStyle = { "--token-status-value": metric.percent } as CSSProperties;
          const metricClassName = `${styles.tokenStatusMetric} ${styles[`tokenStatusMetric_${metric.tone}`]}`;
          const visibleValue = metric.displayValue ?? metric.value;
          const visibleLabel = tokenMetricShortLabel(metric, lang);
          const hoverLines = (metric.titleLines?.length ? metric.titleLines : metric.title.split("\n"))
            .map((line) => line.trim())
            .filter(Boolean)
            .slice(0, 4);
          const tooltipContent = (
            <div className={styles.tokenStatusTooltip} role="presentation">
              <div className={styles.tokenStatusTooltipHead}>{visibleLabel}</div>
              {hoverLines.map((line, index) => (
                <div key={`${metric.key}-${index}`} className={styles.tokenStatusTooltipLine}>
                  {line}
                </div>
              ))}
            </div>
          );
          const metricContent = (
            <>
              <span className={styles.tokenStatusRing} aria-hidden="true">
                <span className={styles.tokenStatusRingCore}>{visibleValue}</span>
              </span>
              <span className={styles.tokenStatusCopy}>
                <span className={styles.tokenStatusLabel}>{visibleLabel}</span>
                <span className={styles.tokenStatusMeta}>{metric.label}: {metric.value}. {metric.meta}</span>
                <span className={styles.tokenStatusBar} aria-hidden="true">
                  <span />
                </span>
              </span>
            </>
          );

          if (metric.key === "cache") {
            return (
              <div key={metric.key} className={metricClassName} style={metricStyle} role="listitem">
                <VTooltip
                  content={tooltipContent}
                  width="compact"
                  className={styles.tokenStatusTooltipSurface}
                  renderTrigger={(tooltipTriggerProps) => {
                    const {
                      children: _triggerChildren,
                      className: triggerClassName,
                      role: _triggerRole,
                      tabIndex: _triggerTabIndex,
                      ...triggerProps
                    } = tooltipTriggerProps;

                    return (
                      <VButton
                        {...(triggerProps as unknown as VButtonProps)}
                        type="button"
                        contentLayout="plain"
                        className={[triggerClassName, styles.tokenStatusMetricButton].filter(Boolean).join(" ")}
                        isDisabled={!cacheDetailAvailable}
                        onClick={cacheDetailAvailable ? onOpenCacheDetail : undefined}
                        aria-disabled={!cacheDetailAvailable}
                        aria-label={cacheDetailOpenLabel}
                        aria-expanded={cacheDetailAvailable ? cacheDetailOpen : undefined}
                        aria-controls={cacheDetailAvailable ? "cache-detail-dialog" : undefined}
                      >
                        {metricContent}
                      </VButton>
                    );
                  }}
                >
                  {metricContent}
                </VTooltip>
              </div>
            );
          }

          return (
            <div key={metric.key} className={metricClassName} style={metricStyle} role="listitem">
              <VTooltip
                content={tooltipContent}
                width="compact"
                className={styles.tokenStatusTooltipSurface}
                renderTrigger={(tooltipTriggerProps) => {
                  const {
                    children: _triggerChildren,
                    className: triggerClassName,
                    role: _triggerRole,
                    tabIndex: _triggerTabIndex,
                    ...triggerProps
                  } = tooltipTriggerProps;

                  return (
                    <VButton
                      {...(triggerProps as unknown as VButtonProps)}
                      type="button"
                      contentLayout="plain"
                      className={[triggerClassName, styles.tokenStatusMetricButton].filter(Boolean).join(" ")}
                      aria-label={`${metric.label} ${metric.value}. ${metric.meta}`}
                    >
                      {metricContent}
                    </VButton>
                  );
                }}
              >
                {metricContent}
              </VTooltip>
            </div>
          );
        })}
      </div>
    </section>
  );
}
