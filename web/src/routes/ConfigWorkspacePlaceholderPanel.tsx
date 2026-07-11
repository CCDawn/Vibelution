import { VRouteHeader, VSurface } from "../components/vui";
import styles from "./ConfigWorkspacePlaceholderPanel.styles";

type ConfigWorkspacePlaceholderPanelProps = {
  title: string;
  subtitle?: string;
  tone?: "loading" | "error";
};

export function ConfigWorkspacePlaceholderPanel({
  title,
  subtitle,
  tone = "loading",
}: ConfigWorkspacePlaceholderPanelProps) {
  const navLabels = ["Source", "Runtime", "Models", "Diagnostics", "Tools"];
  const matrixLabels = ["operator config", "providers", "models", "runtime"];
  return (
    <VSurface as="div" className={`${styles.loadingShell} ${tone === "error" ? styles.loadingShellError : ""}`} padding="none">
      <VSurface as="aside" className={styles.loadingNavPanel} tone="rail">
        <VRouteHeader eyebrow="Config" title={title} />
        {subtitle ? <p className={styles.subtitle}>{subtitle}</p> : null}
        <div className={styles.loadingNavList} aria-hidden="true">
          {navLabels.map((label, index) => (
            <span key={label} className={index === 0 ? styles.loadingNavActive : undefined}>
              {label}
            </span>
          ))}
        </div>
      </VSurface>
      <VSurface as="section" className={styles.loadingBoard} aria-hidden="true" padding="none">
        <div className={styles.loadingBoardHeader}>
          <span />
          <span />
          <span />
        </div>
        <div className={styles.loadingMetricGrid}>
          {matrixLabels.map((label) => (
            <span key={label}>
              <small>{label}</small>
              <strong />
            </span>
          ))}
        </div>
        <div className={styles.loadingSpecGrid}>
          <span />
          <span />
          <span />
          <span />
          <span />
          <span />
        </div>
      </VSurface>
    </VSurface>
  );
}
