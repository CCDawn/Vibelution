import { CheckCircle2, Pencil, Trash2, TriangleAlert, Undo2 } from "lucide-react";

import { VButton } from "../components/vui";
import styles from "./MemorySelectedConfigPanel.styles";

export type MemorySelectedConfigItem = {
  title: string;
  summary: string;
  content?: string;
  managedState?: {
    actionHint?: string;
    disabled?: boolean;
    userManaged?: boolean;
    overridden?: boolean;
    editable?: boolean;
    restorable?: boolean;
    deletable?: boolean;
  };
};

export type MemorySelectedConfigFeedback = {
  tone: "idle" | "success" | "error";
  text: string;
};

export type MemorySelectedConfigCopy = {
  management: string;
  managementHint: string;
  userManaged: string;
  overridden: string;
  disabledByUser: string;
  canUse: string;
  noContent: string;
  editMemory: string;
  restoreMemory: string;
  deleteMemory: string;
  disableMemory: string;
};

type MemorySelectedConfigPanelProps = {
  copy: MemorySelectedConfigCopy;
  sectionTitle: string;
  item: MemorySelectedConfigItem | null;
  isEditing: boolean;
  mutationBusy: boolean;
  mutationFeedback: MemorySelectedConfigFeedback;
  onEdit: () => void;
  onRestore: () => void;
  onDisableOrDelete: () => void;
};

function selectedConfigTitle(copy: MemorySelectedConfigCopy, item: MemorySelectedConfigItem) {
  return item.managedState?.userManaged ? copy.userManaged : item.managedState?.overridden ? copy.overridden : copy.management;
}

function selectedConfigStatus(copy: MemorySelectedConfigCopy, item: MemorySelectedConfigItem) {
  if (item.managedState?.disabled) {
    return copy.disabledByUser;
  }
  if (item.managedState?.userManaged) {
    return copy.userManaged;
  }
  if (item.managedState?.overridden) {
    return copy.overridden;
  }
  return copy.canUse;
}

export function MemorySelectedConfigPanel({
  copy,
  sectionTitle,
  item,
  isEditing,
  mutationBusy,
  mutationFeedback,
  onEdit,
  onRestore,
  onDisableOrDelete,
}: MemorySelectedConfigPanelProps) {
  if (!item || !sectionTitle || isEditing) {
    return null;
  }

  return (
    <section className={styles.managementPanel} aria-label={copy.management} title={item.managedState?.actionHint || copy.managementHint}>
      <div className={styles.managementHeader}>
        <div>
          <p className={styles.panelEyebrow}>{sectionTitle}</p>
          <h2>{selectedConfigTitle(copy, item)}</h2>
        </div>
        <span className={styles.countPill}>{selectedConfigStatus(copy, item)}</span>
      </div>
      <div className={styles.selectedConfigSummary}>
        <strong>{item.title}</strong>
        <p>{item.summary || item.content || copy.noContent}</p>
      </div>
      <div className={styles.managementActions}>
        <VButton
          type="button"
          className={styles.detailActionButton}
          onClick={onEdit}
          isDisabled={!item.managedState?.editable || mutationBusy}
        >
          <Pencil size={15} />
          <span>{copy.editMemory}</span>
        </VButton>
        {item.managedState?.restorable ? (
          <VButton type="button" className={styles.detailActionButton} onClick={onRestore} isDisabled={mutationBusy}>
            <Undo2 size={15} />
            <span>{copy.restoreMemory}</span>
          </VButton>
        ) : null}
        <VButton
          type="button"
          className={styles.detailActionButton}
          onClick={onDisableOrDelete}
          isDisabled={!item.managedState?.deletable || mutationBusy}
        >
          <Trash2 size={15} />
          <span>{item.managedState?.userManaged ? copy.deleteMemory : copy.disableMemory}</span>
        </VButton>
      </div>
      {mutationFeedback.tone !== "idle" ? (
        <p className={styles.copyNotice} data-tone={mutationFeedback.tone}>
          {mutationFeedback.tone === "success" ? <CheckCircle2 size={14} /> : <TriangleAlert size={14} />}
          <span>{mutationFeedback.text}</span>
        </p>
      ) : null}
    </section>
  );
}
