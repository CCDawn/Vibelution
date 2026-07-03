import { CheckCircle2, TriangleAlert, XCircle } from "lucide-react";

import { VButton, VNativeInput, VNativeTextarea } from "../components/vui";
import styles from "./MemoryRoute.styles";

export type MemoryManagementEditorDraft = {
  mode: "create" | "edit";
  sectionId: string;
  itemId: string;
  title: string;
  summary: string;
  content: string;
};

export type MemoryManagementEditorPreviewItem = {
  title: string;
  summary: string;
  content?: string;
};

export type MemoryManagementEditorFeedback = {
  tone: "idle" | "success" | "error";
  text: string;
};

export type MemoryManagementEditorCopy = {
  management: string;
  managementHint: string;
  addMemory: string;
  editMemory: string;
  cancelEdit: string;
  titleField: string;
  titlePlaceholder: string;
  summaryField: string;
  summaryPlaceholder: string;
  contentField: string;
  contentPlaceholder: string;
  saveMemory: string;
  editPreview: string;
  currentValue: string;
  draftValue: string;
  noDraftChanges: string;
};

type MemoryManagementEditorProps = {
  copy: MemoryManagementEditorCopy;
  draft: MemoryManagementEditorDraft | null;
  previewItem: MemoryManagementEditorPreviewItem | null;
  mutationBusy: boolean;
  mutationFeedback: MemoryManagementEditorFeedback;
  onCancel: () => void;
  onDraftChange: (draft: MemoryManagementEditorDraft) => void;
  onSave: () => void;
};

export function MemoryManagementEditor({
  copy,
  draft,
  previewItem,
  mutationBusy,
  mutationFeedback,
  onCancel,
  onDraftChange,
  onSave,
}: MemoryManagementEditorProps) {
  if (!draft) {
    return null;
  }

  return (
    <section className={styles.managementPanel} aria-label={copy.management} title={copy.managementHint}>
      <div className={styles.managementHeader}>
        <div>
          <p className={styles.panelEyebrow}>{copy.management}</p>
          <h2>{draft.mode === "create" ? copy.addMemory : copy.editMemory}</h2>
        </div>
        <VButton type="button" className={styles.iconButton} onClick={onCancel} isDisabled={mutationBusy}>
          <XCircle size={16} />
          <span>{copy.cancelEdit}</span>
        </VButton>
      </div>
      <label className={styles.fieldStack}>
        <span>{copy.titleField}</span>
        <VNativeInput
          value={draft.title}
          placeholder={copy.titlePlaceholder}
          onChange={(event) => onDraftChange({ ...draft, title: event.target.value })}
        />
      </label>
      <label className={styles.fieldStack}>
        <span>{copy.summaryField}</span>
        <VNativeInput
          value={draft.summary}
          placeholder={copy.summaryPlaceholder}
          onChange={(event) => onDraftChange({ ...draft, summary: event.target.value })}
        />
      </label>
      <label className={styles.fieldStack}>
        <span>{copy.contentField}</span>
        <VNativeTextarea
          value={draft.content}
          placeholder={copy.contentPlaceholder}
          onChange={(event) => onDraftChange({ ...draft, content: event.target.value })}
        />
      </label>
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
    </section>
  );
}
