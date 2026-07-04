import { ExternalLink, Search } from "lucide-react";

import { VButton } from "../components/vui";
import styles from "./AgentRuntimeFocusPanel.styles";

export type AgentRuntimeFocusPanelCopy = {
  runtimeFocus: string;
  runtimeLatestRun: string;
  runtimeReason: string;
  runtimeUpdated: string;
  runtimeNextStep: string;
  runtimeEvidence: string;
  openSession: string;
  openLogs: string;
};

export type AgentRuntimeFocusPanelProps = {
  copy: AgentRuntimeFocusPanelCopy;
  statusLabel: string;
  statusReason: string;
  tone: string;
  summary: string;
  latestRunId: string;
  runReason: string;
  updatedAt: string;
  nextStep: string;
  evidenceReason: string;
  evidenceSceneId: string;
  logsTargetLabel?: string;
  onOpenLogs: () => void;
  onOpenSession?: () => void;
};

export function AgentRuntimeFocusPanel({
  copy,
  statusLabel,
  statusReason,
  tone,
  summary,
  latestRunId,
  runReason,
  updatedAt,
  nextStep,
  evidenceReason,
  evidenceSceneId,
  logsTargetLabel,
  onOpenLogs,
  onOpenSession,
}: AgentRuntimeFocusPanelProps) {
  const runtimeToneStyle = styles[`runtime_${tone}` as keyof typeof styles] || styles.runtime_unknown;
  const logsLabel = logsTargetLabel ? `${copy.openLogs} · ${logsTargetLabel}` : copy.openLogs;

  return (
    <section className={styles.runtimeFocusPanel}>
      <div className={styles.runtimeFocusHeader}>
        <div>
          <p className={styles.panelEyebrow}>{copy.runtimeFocus}</p>
          <h3>{statusLabel}</h3>
        </div>
        <span className={`${styles.runtimePill} ${runtimeToneStyle}`}>
          {statusReason}
        </span>
      </div>
      <p>{summary}</p>
      <div className={styles.runtimeFocusMeta}>
        <span>
          <strong>{copy.runtimeLatestRun}</strong>
          <code>{latestRunId}</code>
        </span>
        <span>
          <strong>{copy.runtimeReason}</strong>
          <code>{runReason}</code>
        </span>
        <span>
          <strong>{copy.runtimeUpdated}</strong>
          <code>{updatedAt}</code>
        </span>
      </div>
      <div className={styles.runtimeNextStep}>
        <strong>{copy.runtimeNextStep}</strong>
        <span>{nextStep}</span>
      </div>
      <div className={styles.runtimeEvidenceHint}>
        <strong>{copy.runtimeEvidence}</strong>
        <span>{evidenceReason}</span>
        <code>{evidenceSceneId}</code>
      </div>
      <div className={styles.timelineActions}>
        {onOpenSession ? (
          <VButton type="button" variant="ghost" icon={<ExternalLink size={13} />} onPress={onOpenSession}>
            {copy.openSession}
          </VButton>
        ) : null}
        <VButton type="button" variant="ghost" icon={<Search size={13} />} onPress={onOpenLogs}>
          {logsLabel}
        </VButton>
      </div>
    </section>
  );
}
