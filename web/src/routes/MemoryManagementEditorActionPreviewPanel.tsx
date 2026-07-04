import { CheckCircle2, TriangleAlert, XCircle } from "lucide-react";

import { VButton } from "../components/vui";
import type {
  MemoryManagementEditorDraft,
  MemoryManagementEditorFeedback,
  MemoryManagementEditorPreviewItem,
} from "./MemoryManagementEditor";
import styles from "./MemoryManagementEditorActionPreviewPanel.styles";

export type MemoryManagementEditorActionPreviewCopy = {
  saveMemory: string;
  cancelEdit: string;
  editPreview: string;
  titleField: string;
  summaryField: string;
  contentField: string;
  currentValue: string;
  draftValue: string;
  noDraftChanges: string;
};

type MemoryManagementEditorActionPreviewPanelProps = {
  copy: MemoryManagementEditorActionPreviewCopy;
  draft: MemoryManagementEditorDraft;
  previewItem: MemoryManagementEditorPreviewItem | null;
  mutationBusy: boolean;
  mutationFeedback: MemoryManagementEditorFeedback;
  onCancel: () => void;
  onSave: () => void;
};

export function MemoryManagementEditorActionPreviewPanel({
  copy,
  draft,
  previewItem,
  mutationBusy,
  mutationFeedback,
  onCancel,
  onSave,
}: MemoryManagementEditorActionPreviewPanelProps) {
  return (
    <>
      <div className={styles.managementActions}>
        <VButton type="button" className={styles.primaryActionButton} onClick={onSave} isDisabled={mutationBusy}>
          <CheckCircle2 size={15} />
          <span>{copy.saveMemory}</span>
        </VButton>
        <VButton type="button" className={styles.detailActionButton} onClick={onCancel} isDisabled={mutationBusy}>
          <XCircle size={15} />
          <span>{copy.cancelEdit}</span>
        </VButton>
      </div>
      <section className={styles.editPreviewPanel} aria-label={copy.editPreview}>
        <div className={styles.panelHeader}>
          <div>
            <p className={styles.panelEyebrow}>{copy.editPreview}</p>
            <h3>{draft.title.trim() || copy.titleField}</h3>
          </div>
        </div>
        {previewItem && draft.mode === "edit" ? (
          <div className={styles.editPreviewGrid}>
            {[
              { label: copy.titleField, current: previewItem.title, draft: draft.title },
              { label: copy.summaryField, current: previewItem.summary, draft: draft.summary },
              { label: copy.contentField, current: previewItem.content, draft: draft.content },
            ].map((field) => (
              <section key={field.label}>
                <strong>{field.label}</strong>
                <div>
                  <span>{copy.currentValue}</span>
                  <p>{field.current || "-"}</p>
                </div>
                <div>
                  <span>{copy.draftValue}</span>
                  <p>{field.draft || "-"}</p>
                </div>
              </section>
            ))}
          </div>
        ) : (
          <p>{draft.content.trim() || draft.summary.trim() || draft.title.trim() ? draft.summary || draft.content : copy.noDraftChanges}</p>
        )}
      </section>
      {mutationFeedback.tone !== "idle" ? (
        <p className={styles.copyNotice} data-tone={mutationFeedback.tone}>
          {mutationFeedback.tone === "success" ? <CheckCircle2 size={14} /> : <TriangleAlert size={14} />}
          <span>{mutationFeedback.text}</span>
        </p>
      ) : null}
    </>
  );
}
