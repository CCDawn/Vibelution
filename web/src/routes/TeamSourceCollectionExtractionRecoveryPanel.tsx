import { AlertTriangle } from "lucide-react";
import { type ReactNode } from "react";

import styles from "./TeamsRoute.styles";

type TeamSourceCollectionExtractionRecoveryPanelProps = {
  lang: "zh" | "en";
  statusLabel: ReactNode;
  summary: ReactNode;
  failedText: ReactNode;
  salvageText: ReactNode;
  recoverText: ReactNode;
  pendingReviewText: ReactNode;
  actions: ReactNode;
};

export function TeamSourceCollectionExtractionRecoveryPanel({
  lang,
  statusLabel,
  summary,
  failedText,
  salvageText,
  recoverText,
  pendingReviewText,
  actions,
}: TeamSourceCollectionExtractionRecoveryPanelProps) {
  return (
    <section
      className={styles.sourceCollectionExtractionRecoveryPanel}
      aria-label={lang === "zh" ? "资料提炼失败恢复工作台" : "Source extraction recovery panel"}
    >
      <div className={styles.sourceCollectionExtractionRecoveryBody}>
        <div className={styles.sourceCollectionResultsHeader}>
          <AlertTriangle size={14} />
          <strong>{lang === "zh" ? "提炼失败恢复" : "Extraction recovery"}</strong>
          <span className={styles.sourceCollectionRunBadge}>{statusLabel}</span>
        </div>
        <p>{summary}</p>
        <div className={styles.sourceCollectionExtractionRecoveryStats}>
          <span>
            {lang === "zh" ? "提炼失败" : "failed extraction"}
            <strong>{failedText}</strong>
          </span>
          <span>
            {lang === "zh" ? "可保留" : "salvageable"}
            <strong>{salvageText}</strong>
          </span>
          <span>
            {lang === "zh" ? "待补提炼" : "to recover"}
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
