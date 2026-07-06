import { useId, type CSSProperties } from "react";

import { VButton } from "../../components/vui";
import styles from "../ChatCodingRoute.styles";

export type TokenCoreStatusMetric = {
  key: "cache" | "modelInput" | "compression" | "speed";
  label: string;
  value: string;
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
        <div className={styles.sectionIdentity}>
          <p className={styles.blockEyebrow}>Token</p>
          <h3 id={titleId} className={styles.sectionTitle}>{lang === "zh" ? "核心状态" : "Core status"}</h3>
        </div>
      </div>
      <div className={styles.tokenStatusVisualGrid} role="list" aria-label={lang === "zh" ? "Token 核心状态" : "Token core status"}>
        {metrics.map((metric) => {
          const metricStyle = { "--token-status-value": metric.percent } as CSSProperties;
          const metricClassName = `${styles.tokenStatusMetric} ${styles[`tokenStatusMetric_${metric.tone}`]}`;
          const metricContent = (
            <>
              <span className={styles.tokenStatusRing} aria-hidden="true">
                <span className={styles.tokenStatusRingCore}>{metric.value}</span>
              </span>
              <span className={styles.tokenStatusCopy}>
                <span className={styles.tokenStatusLabel}>{metric.label}</span>
                <span className={styles.tokenStatusMeta}>{metric.meta}</span>
                <span className={styles.tokenStatusBar} aria-hidden="true">
                  <span />
                </span>
              </span>
            </>
          );

          if (metric.key === "cache") {
            return (
              <VButton
                key={metric.key}
                type="button"
                className={`${metricClassName} ${styles.tokenStatusMetricButton}`}
                style={metricStyle}
                isDisabled={!cacheDetailAvailable}
                onClick={cacheDetailAvailable ? onOpenCacheDetail : undefined}
                aria-disabled={!cacheDetailAvailable}
                aria-label={cacheDetailOpenLabel}
                aria-expanded={cacheDetailAvailable ? cacheDetailOpen : undefined}
                aria-controls={cacheDetailAvailable ? "cache-detail-dialog" : undefined}
                role="listitem"
                title={metric.title}
              >
                {metricContent}
              </VButton>
            );
          }

          return (
            <div
              key={metric.key}
              className={metricClassName}
              style={metricStyle}
              title={metric.title}
              role="listitem"
            >
              {metricContent}
            </div>
          );
        })}
      </div>
    </section>
  );
}
