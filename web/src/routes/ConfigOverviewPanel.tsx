import { Database } from "lucide-react";

import type { ConfigWorkspace } from "../api/types";
import { VSection } from "../components/vui";
import type { ConfigCopy } from "./ConfigRoute";
import styles from "./ConfigOverviewPanel.styles";

type ConfigOverviewPanelProps = {
  copy: ConfigCopy;
  eyebrow: string;
  workspace: ConfigWorkspace;
};

export function ConfigOverviewPanel({
  copy,
  eyebrow,
  workspace,
}: ConfigOverviewPanelProps) {
  return (
    <VSection
      id="config-overview"
      className={styles.sectionSurface}
      headerClassName={styles.sectionHeader}
      eyebrow={eyebrow}
      title={copy.sourceTitle}
      actions={<Database size={16} className={styles.sectionIcon} />}
    >
      <p className={styles.sectionText} title={copy.sourceBody}>{copy.sourceBodyShort}</p>
      <div className={styles.summaryGrid}>
        <article className={styles.detailCard}>
          <span>{copy.modelCenterModels}</span>
          <strong>{workspace.modelLibraryCount}</strong>
        </article>
        <article className={styles.detailCard} data-summary-tone={workspace.blockingCount ? "error" : "success"}>
          <span>{copy.blockingIssues}</span>
          <strong>{workspace.blockingCount}</strong>
        </article>
        <article className={styles.detailCard} data-summary-tone={workspace.warningCount ? "warning" : "neutral"}>
          <span>{copy.warningSignals}</span>
          <strong>{workspace.warningCount}</strong>
        </article>
      </div>
    </VSection>
  );
}
