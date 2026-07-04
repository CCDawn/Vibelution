import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { type ReactNode } from "react";

import styles from "./TeamSourceCollectionExtractionRecoveryPanel.styles";

type TeamSourceCollectionExtractionRecoveryTone = "danger" | "progressable";

type TeamSourceCollectionExtractionRecoveryPanelProps = {
  lang: "zh" | "en";
  tone?: TeamSourceCollectionExtractionRecoveryTone;
  ariaLabel?: string;
  titleLabel?: ReactNode;
  statusLabel: ReactNode;
  summary: ReactNode;
  failedLabel?: ReactNode;
  failedText: ReactNode;
  salvageText: ReactNode;
  recoverLabel?: ReactNode;
  recoverText: ReactNode;
  pendingReviewText: ReactNode;
  actions: ReactNode;
};

export function TeamSourceCollectionExtractionRecoveryPanel({
  lang,
  tone = "danger",
  ariaLabel,
  titleLabel,
  statusLabel,
  summary,
  failedLabel,
  failedText,
  salvageText,
  recoverLabel,
  recoverText,
  pendingReviewText,
  actions,
}: TeamSourceCollectionExtractionRecoveryPanelProps) {
  const StatusIcon = tone === "progressable" ? CheckCircle2 : AlertTriangle;
  const panelClassName = `${styles.sourceCollectionExtractionRecoveryPanel} ${
    tone === "progressable"
      ? styles.sourceCollectionExtractionRecoveryPanelProgressable
      : styles.sourceCollectionExtractionRecoveryPanelDanger
  }`;
  return (
    <section
      className={panelClassName}
      aria-label={ariaLabel ?? (lang === "zh" ? "资料提炼失败恢复工作台" : "Source extraction recovery panel")}
    >
      <div className={styles.sourceCollectionExtractionRecoveryBody}>
        <div className={styles.sourceCollectionResultsHeader}>
          <StatusIcon size={14} />
          <strong>{titleLabel ?? (lang === "zh" ? "提炼失败恢复" : "Extraction recovery")}</strong>
          <span className={styles.sourceCollectionRunBadge}>{statusLabel}</span>
        </div>
        <p>{summary}</p>
        <div className={styles.sourceCollectionExtractionRecoveryStats}>
          <span>
            {failedLabel ?? (lang === "zh" ? "提炼失败" : "failed extraction")}
            <strong>{failedText}</strong>
          </span>
          <span>
            {lang === "zh" ? "可保留" : "salvageable"}
            <strong>{salvageText}</strong>
          </span>
          <span>
            {recoverLabel ?? (lang === "zh" ? "待补提炼" : "to recover")}
            <strong>{recoverText}</strong>
          </span>
          <span>
            {lang === "zh" ? "待 Agent 复核" : "pending agent review"}
            <strong>{pendingReviewText}</strong>
          </span>
        </div>
      </div>
      <div className={styles.sourceCollectionExtractionRecoveryActions}>{actions}</div>
    </section>
  );
}
