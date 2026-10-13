import { BrainCircuit, ChevronDown, ChevronRight, LoaderCircle } from "lucide-react";

import { VButton } from "../vui";
import type { TranslationKey } from "../../i18n/dictionaryTypes";
import type { AgentMentalPart } from "../../agent-thread/types";
import {
  buildMentalBodyRows,
  buildMentalMetaRows,
  mentalSnapshotPreview,
  type MentalStateFormatters,
  type MentalStateLabels,
} from "./conversationMentalState";
import { compactConversationPreview } from "./conversationOperationPresentation";
import styles from "./ConversationView.styles";

export type ConversationAuxiliaryPanelsDeps = {
  t: (key: TranslationKey) => string;
  showMentalSnapshots: boolean;
  getExpansionState: (messageId: string, section: string, defaultExpanded: boolean) => boolean;
  toggleSection: (messageId: string, section: string, defaultExpanded: boolean) => void;
  formatTimestamp: (timestamp: string) => string;
};

/**
 * Legacy agent mental-state panel (opt-in snapshot surface). Extracted from
 * ConversationView with identical output.
 */
export function createConversationAuxiliaryPanels({
  t,
  showMentalSnapshots,
  getExpansionState,
  toggleSection,
  formatTimestamp,
}: ConversationAuxiliaryPanelsDeps) {
  function renderAgentMentalPanel(
    messageId: string,
    part: AgentMentalPart | undefined,
    defaultExpandedOverride: boolean | undefined,
    isRunning: boolean,
  ) {
    if (!showMentalSnapshots || !part || !part.snapshot) {
      return null;
    }
    const snapshot = part.snapshot;
    const expanded = getExpansionState(messageId, "mental", defaultExpandedOverride ?? true);
    const toggleTitle = expanded ? t("mentalProcessVisible") : t("mentalProcessHidden");
    const mentalLabels: MentalStateLabels = {
      feeling: t("mentalFeeling"),
      summary: t("mentalSummary"),
      feelingSummary: `${t("mentalFeeling")} / ${t("mentalSummary")}`,
      mood: t("mentalMood"),
      cognitiveState: t("mentalCognitiveState"),
      source: t("mentalSource"),
      confidence: t("mentalConfidence"),
      samples: t("mentalSamples"),
      lastUpdated: t("mentalLastUpdated"),
      whisper: t("mentalWhisper"),
      intervention: t("mentalIntervention"),
      cognitiveStateUnknown: t("mentalCognitiveState_unknown"),
      cognitiveStateNormal: t("mentalCognitiveState_normal"),
      cognitiveStateProductive: t("mentalCognitiveState_productive"),
      cognitiveStateLooping: t("mentalCognitiveState_looping"),
      cognitiveStateThrashing: t("mentalCognitiveState_thrashing"),
      cognitiveStateTunnelVision: t("mentalCognitiveState_tunnel_vision"),
      cognitiveStateDisoriented: t("mentalCognitiveState_disoriented"),
      sourceState: t("mentalSourceState"),
      sourceDiagnosis: t("mentalSourceDiagnosis"),
      sourceRuntime: t("runtime"),
    };
    const mentalFormatters: MentalStateFormatters = {
      compactPreview: compactConversationPreview,
      formatTimestamp,
    };
    const metaRows = buildMentalMetaRows(snapshot, mentalLabels, mentalFormatters);
    const bodyRows = buildMentalBodyRows(snapshot, mentalLabels);
    const preview = mentalSnapshotPreview(snapshot, mentalLabels, mentalFormatters);
    return (
      <section className={`${styles.auxiliaryBlock} ${styles.auxiliaryBlock_mental}`}>
        <VButton
          type="button"
          className={styles.operationSummary}
          aria-expanded={expanded}
          onClick={() => toggleSection(messageId, "mental", defaultExpandedOverride ?? true)}
          title={toggleTitle}
          icon={<BrainCircuit size={17} />}
          trailingIcon={
            <>
              {isRunning ? <LoaderCircle className={styles.statusSpinner} size={14} /> : null}
              {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
            </>
          }
        >
          <span>{t("mentalProcess")}</span>
          {!expanded && preview ? (
            <span className={styles.operationSummaryPreview}>{preview}</span>
          ) : null}
        </VButton>
        {expanded ? (
          <div className={`${styles.auxiliaryPanel} ${styles.auxiliaryPanel_mental}`}>
            {metaRows.length ? (
              <div className={styles.mentalMetaGrid}>
                {metaRows.map((row) => (
                  <span key={row.label} className={styles.mentalMetaItem}>
                    <small>{row.label}</small>
                    <strong>{row.value}</strong>
                  </span>
                ))}
              </div>
            ) : null}
            {bodyRows.length ? (
              <div className={styles.mentalBodyList}>
                {bodyRows.map((row) => (
                  <p key={row.label} className={styles.mentalBodyRow}>
                    <span>{row.label}</span>
                    {row.value}
                  </p>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </section>
    );
  }

  return { renderAgentMentalPanel };
}
