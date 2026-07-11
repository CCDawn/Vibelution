import { Database, RefreshCw, RotateCcw } from "lucide-react";

import { LazyJsonCodeMirror } from "../components/editor/LazyJsonCodeMirror";
import { VButton, VSection } from "../components/vui";
import type { ConfigCopy } from "./ConfigRoute";
import styles from "./ConfigDraftPanel.styles";

type ConfigDraftPanelProps = {
  copy: ConfigCopy;
  eyebrow: string;
  jsonText: string;
  hasEditorChanges: boolean;
  canCheckCurrentChanges: boolean;
  canRestoreEditorText: boolean;
  onValidateEditorDraft: () => void;
  onRestoreEditorText: () => void;
  onJsonTextChange: (value: string) => void;
};

export function ConfigDraftPanel({
  copy,
  eyebrow,
  jsonText,
  hasEditorChanges,
  canCheckCurrentChanges,
  canRestoreEditorText,
  onValidateEditorDraft,
  onRestoreEditorText,
  onJsonTextChange,
}: ConfigDraftPanelProps) {
  return (
    <VSection
      id="config-draft"
      className={styles.sectionSurface}
      headerClassName={styles.sectionHeader}
      eyebrow={eyebrow}
      title={copy.draftTitle}
      actions={<Database size={16} className={styles.sectionIcon} />}
    >
        <p className={styles.sectionText}>{copy.draftBody}</p>
        <div className={styles.draftWorkbench}>
        <div className={styles.draftActionRail}>
          <VButton type="button" className={styles.actionButton} isDisabled={!canCheckCurrentChanges} onClick={onValidateEditorDraft}>
            <RefreshCw size={14} />
            {copy.validateDraft}
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
          <span className={styles.helperText}>{hasEditorChanges ? copy.editorDirtyHint : copy.editorCleanHint}</span>
        </div>
        <div className={styles.editorWrap}>
          <LazyJsonCodeMirror value={jsonText} onChange={onJsonTextChange} />
        </div>
        </div>
    </VSection>
  );
}
