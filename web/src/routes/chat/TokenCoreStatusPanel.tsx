import { useId, type CSSProperties } from "react";

import { VButton, VTooltip, type VButtonProps } from "../../components/vui";
import styles from "../ChatCodingRoute.styles";

export type TokenCoreStatusMetric = {
  key: "cache" | "modelInput" | "compression" | "speed";
  label: string;
  value: string;
  displayValue?: string;
  meta: string;
  title: string;
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
}: TokenCoreStatusPanelProps) {
  const panelId = useId();
  const titleId = `${panelId}-title`;

  return (
    <section className={`${styles.leftBlock} ${styles.tokenCompressionCard}`} aria-labelledby={titleId}>
      <div className={styles.sectionHeader}>
        <h3 id={titleId} className={styles.sectionTitle}>Token</h3>
      </div>
      <div className={styles.tokenStatusVisualGrid} role="list" aria-label={lang === "zh" ? "Token 核心状态" : "Token core status"}>
        {metrics.map((metric) => {
          const metricStyle = { "--token-status-value": metric.percent } as CSSProperties;
          const metricClassName = `${styles.tokenStatusMetric} ${styles[`tokenStatusMetric_${metric.tone}`]}`;
          const visibleValue = metric.displayValue ?? metric.value;
          const visibleLabel = tokenMetricShortLabel(metric, lang);
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
                  content={metric.title}
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
                content={metric.title}
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
