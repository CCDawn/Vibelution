import { KeyRound, ShieldAlert } from "lucide-react";

import type { ConfigDiagnosis } from "../api/types";
import { VButton, VSection } from "../components/vui";
import { groupConfigDiagnosisIssues } from "./configDiagnosisPresentation";
import styles from "./ConfigDiagnosisPanel.styles";

export type ConfigDiagnosisPanelCopy = {
  diagnosticsTitle: string;
  diagnosticsBody: string;
  blockingIssues: string;
  warningSignals: string;
  suggestedActions: string;
  noBlocking: string;
  noWarnings: string;
  noSuggestions: string;
  rootCauseMetric: string;
  affectedReferenceMetric: string;
  warningMetric: string;
  affectedReferences: string;
  showAffectedReferences: string;
  repairProviderCredential: string;
};

type ConfigDiagnosisPanelProps = {
  diagnosis: ConfigDiagnosis;
  copy: ConfigDiagnosisPanelCopy;
  repairableProviderIds: readonly string[];
  onRepairProvider: (providerId: string) => void;
};

export default function ConfigDiagnosisPanel({
  diagnosis,
  copy,
  repairableProviderIds,
  onRepairProvider,
}: ConfigDiagnosisPanelProps) {
  const blockerGroups = groupConfigDiagnosisIssues(diagnosis.blocking_issues);
  const repairableProviders = new Set(repairableProviderIds);
  const affectedReferenceCount = blockerGroups.reduce((total, group) => total + group.references.length, 0);

  return (
    <VSection
      id="config-diagnostics"
      className={styles.sectionSurface}
      headerClassName={styles.sectionHeader}
      eyebrow={copy.diagnosticsTitle}
      title={copy.diagnosticsTitle}
      actions={<ShieldAlert size={16} className={styles.sectionIcon} />}
    >
      <div className={styles.content}>
        <p className={styles.sectionText}>{copy.diagnosticsBody}</p>
        <div className={styles.summaryGrid} aria-label={copy.diagnosticsTitle}>
          <span className={styles.metricCard}><strong>{blockerGroups.length}</strong><span>{copy.rootCauseMetric}</span></span>
          <span className={styles.metricCard}><strong>{affectedReferenceCount}</strong><span>{copy.affectedReferenceMetric}</span></span>
          <span className={styles.metricCard}><strong>{diagnosis.warnings.length}</strong><span>{copy.warningMetric}</span></span>
        </div>

        <div className={styles.blockerList}>
          {blockerGroups.length ? blockerGroups.map((group) => {
            const repairProviderId = group.repair?.kind === "provider-api-key" ? group.repair.providerId : "";
            const canRepairProvider = Boolean(repairProviderId && repairableProviders.has(repairProviderId));
            return (
              <article key={group.id} className={styles.blockerCard}>
                <div className={styles.blockerHeader}>
                  <div>
                    <p className={styles.eyebrow}>{copy.blockingIssues}</p>
                    <h3>{group.message}</h3>
                  </div>
                  {canRepairProvider ? (
                    <VButton
                      className={styles.actionButton}
                      variant="primary"
                      icon={<KeyRound size={15} />}
                      data-provider-repair={repairProviderId}
                      onPress={() => onRepairProvider(repairProviderId)}
                    >
                      {copy.repairProviderCredential}
                    </VButton>
                  ) : null}
                </div>
                {group.references.length ? (
                  <details className={styles.affectedDetails}>
                    <summary>{copy.showAffectedReferences} · {group.references.length}</summary>
                    <ul className={styles.affectedList} aria-label={copy.affectedReferences}>
                      {group.references.map((reference) => <li key={reference} className={styles.affectedPill}>{reference}</li>)}
                    </ul>
                  </details>
                ) : null}
              </article>
            );
          }) : <p className={styles.helperText}>{copy.noBlocking}</p>}
        </div>

        <div className={styles.supportGrid}>
          <article className={styles.supportCard}>
            <h3 className={styles.supportTitle}>{copy.warningSignals}</h3>
            {diagnosis.warnings.length ? (
              <ul className={styles.issueList}>{diagnosis.warnings.map((item) => <li key={item}>{item}</li>)}</ul>
            ) : <p className={styles.helperText}>{copy.noWarnings}</p>}
          </article>
          <article className={styles.supportCard}>
            <h3 className={styles.supportTitle}>{copy.suggestedActions}</h3>
            {diagnosis.suggested_actions.length ? (
              <ul className={styles.issueList}>{diagnosis.suggested_actions.map((item) => <li key={item}>{item}</li>)}</ul>
            ) : <p className={styles.helperText}>{copy.noSuggestions}</p>}
          </article>
        </div>
      </div>
    </VSection>
  );
}
