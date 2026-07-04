import { XCircle } from "lucide-react";

import { VButton, VNativeInput, VNativeTextarea } from "../components/vui";
import {
  MemoryManagementEditorActionPreviewPanel,
  type MemoryManagementEditorActionPreviewCopy,
} from "./MemoryManagementEditorActionPreviewPanel";
import styles from "./MemoryManagementEditor.styles";

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

export type MemoryManagementEditorCopy = MemoryManagementEditorActionPreviewCopy & {
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
      <MemoryManagementEditorActionPreviewPanel
        copy={copy}
        draft={draft}
        previewItem={previewItem}
        mutationBusy={mutationBusy}
        mutationFeedback={mutationFeedback}
        onCancel={onCancel}
        onSave={onSave}
      />
    </section>
  );
}
