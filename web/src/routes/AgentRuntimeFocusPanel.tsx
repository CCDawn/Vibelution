import { ExternalLink, Search } from "lucide-react";

import { VButton, VTooltip } from "../components/vui";
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
  const runtimeMetaLabel = `${copy.runtimeLatestRun} ${latestRunId}；${copy.runtimeReason} ${runReason}；${copy.runtimeUpdated} ${updatedAt}；${copy.runtimeEvidence} ${evidenceReason} ${evidenceSceneId}`;

  return (
    <section className={styles.runtimeFocusPanel}>
      <div className={styles.runtimeFocusHeader}>
        <div>
          <p className={styles.panelEyebrow}>{copy.runtimeFocus}</p>
          <h3>
            <VTooltip
              width="wide"
              content={(
                <span className={styles.runtimeMetaTooltip}>
                  <span>{copy.runtimeLatestRun}: {latestRunId}</span>
                  <span>{copy.runtimeReason}: {runReason}</span>
                  <span>{copy.runtimeUpdated}: {updatedAt}</span>
                  <span>{copy.runtimeEvidence}: {evidenceReason} · {evidenceSceneId}</span>
                </span>
              )}
            >
              <span className={styles.runtimeMetaTrigger} tabIndex={0} aria-label={runtimeMetaLabel}>
                {statusLabel}
              </span>
            </VTooltip>
          </h3>
        </div>
        <span className={`${styles.runtimePill} ${runtimeToneStyle}`}>
          {statusReason}
        </span>
      </div>
      <div className={styles.runtimeNextStep}>
        <VTooltip content={summary} width="wide">
          <span className={styles.runtimeNextStepTrigger} tabIndex={0} aria-label={`${copy.runtimeNextStep}：${nextStep}`}>
            {nextStep}
          </span>
        </VTooltip>
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
