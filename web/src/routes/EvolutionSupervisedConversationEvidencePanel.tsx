import type { ReactNode } from "react";

import type { SupervisedCaseTraceItem } from "./supervisedCaseTrace";
import type { SupervisedPreflightIssue } from "./evolution/evolutionRouteModel";
import { EvolutionSupervisedCaseTracePanel } from "./EvolutionSupervisedCaseTracePanel";
import styles from "./EvolutionRoute.styles";

export type EvolutionSupervisedConversationEvidencePanelProps = {
  showCasePrompt: boolean;
  casePromptTitle: string;
  casePrompt?: string | null;
  preflightIssue?: SupervisedPreflightIssue | null;
  caseTraceItems: SupervisedCaseTraceItem[];
  statusLabel: (status: string) => string;
  formatTimestamp: (value: string) => string;
  showLatestOutput: boolean;
  latestOutputTitle: string;
  latestOutput?: string | null;
};

/**
 * Live conversation supplemental evidence: prompt, preflight, case-trace, latest output.
 */
export function EvolutionSupervisedConversationEvidencePanel({
  showCasePrompt,
  casePromptTitle,
  casePrompt,
  preflightIssue,
  caseTraceItems,
  statusLabel,
  formatTimestamp,
  showLatestOutput,
  latestOutputTitle,
  latestOutput,
}: EvolutionSupervisedConversationEvidencePanelProps): ReactNode {
  return (
    <div className={styles.supervisedConversationEvidence} data-vui-region="evolution-supervised-conversation-evidence">
      {showCasePrompt && casePrompt ? (
        <details className={`${styles.rawBlock} ${styles.collapsibleEvidence}`}>
          <summary>{casePromptTitle}</summary>
          <pre className={styles.ioContent}>{casePrompt}</pre>
        </details>
      ) : null}
      {showCasePrompt && preflightIssue ? (
        <div className={styles.casePreflightIssue}>
          <strong>{preflightIssue.title}</strong>
          <span>{preflightIssue.detail}</span>
          {preflightIssue.reason ? <small>{preflightIssue.reason}</small> : null}
        </div>
      ) : null}
      {showCasePrompt && caseTraceItems.length > 0 ? (
        <EvolutionSupervisedCaseTracePanel
          items={caseTraceItems}
          statusLabel={statusLabel}
          formatTimestamp={formatTimestamp}
        />
      ) : null}
      {showLatestOutput && latestOutput ? (
        <details className={`${styles.rawBlock} ${styles.collapsibleEvidence} ${styles.caseRawEvidence}`}>
          <summary>{latestOutputTitle}</summary>
          <pre className={styles.ioContent}>{latestOutput}</pre>
        </details>
      ) : null}
    </div>
  );
}
