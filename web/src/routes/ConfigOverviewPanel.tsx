import { Database, ExternalLink, RefreshCw, RotateCcw } from "lucide-react";

import type { ConfigWorkspace } from "../api/types";
import { VButton } from "../components/vui";
import type { ConfigCopy } from "./ConfigRoute";
import styles from "./ConfigOverviewPanel.styles";

type ConfigOverviewPanelProps = {
  copy: ConfigCopy;
  eyebrow: string;
  workspace: ConfigWorkspace;
  hasPendingApply: boolean;
  busyAction: string;
  canRestoreEditorText: boolean;
  onReloadWorkspace: () => void;
  onOpenEnvironment: () => void;
  onRestoreEditorText: () => void;
};

export function ConfigOverviewPanel({
  copy,
  eyebrow,
  workspace,
  hasPendingApply,
  busyAction,
  canRestoreEditorText,
  onReloadWorkspace,
  onOpenEnvironment,
  onRestoreEditorText,
}: ConfigOverviewPanelProps) {
  return (
    <section id="config-overview" className={styles.sectionSurface}>
      <div className={styles.sectionHeader}>
        <div>
          <p className={styles.eyebrow}>{eyebrow}</p>
          <h2 className={styles.sectionTitle}>{copy.sourceTitle}</h2>
        </div>
        <Database size={16} className={styles.sectionIcon} />
      </div>
      <p className={styles.sectionText} title={copy.sourceBody}>{copy.sourceBodyShort}</p>
      <div className={styles.hashGrid}>
        <article className={styles.detailCard}>
          <span>{copy.configPath}</span>
          <code className={styles.hashValue}>{workspace.configPath}</code>
        </article>
        <article className={styles.detailCard}>
          <span>{copy.configStatus}</span>
          <strong>{hasPendingApply ? copy.unsavedDraft : copy.syncedDraft}</strong>
        </article>
      </div>
      <div className={styles.actionsRow}>
        <VButton type="button" className={styles.actionButton} isDisabled={Boolean(busyAction)} onClick={onReloadWorkspace}>
          <RefreshCw size={14} />
          {copy.refresh}
        </VButton>
        <VButton
          type="button"
          className={styles.actionButton}
          isDisabled={Boolean(busyAction)}
          title={copy.openEnvironmentHint}
          onClick={onOpenEnvironment}
        >
          <ExternalLink size={14} />
          {busyAction === copy.openEnvironmentPending ? copy.openEnvironmentPending : copy.openEnvironment}
        </VButton>
        <VButton
          type="button"
          className={styles.actionButton}
          isDisabled={!canRestoreEditorText}
          title={copy.editorRestoreHint}
          onClick={onRestoreEditorText}
        >
          <RotateCcw size={14} />
          {copy.resetDraft}
        </VButton>
      </div>
      <details className={styles.rawConfigPanel}>
        <summary>{copy.rawToml}</summary>
        <p className={styles.helperText}>{copy.rawTomlHint}</p>
        <pre className={styles.rawToml}>{workspace.rawToml}</pre>
      </details>
    </section>
  );
}
