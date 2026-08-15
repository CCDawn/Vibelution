import { useRef, useState } from "react";
import { GripVertical, Pencil, X } from "lucide-react";

import { VButton, VNativeTextarea } from "../vui";
import styles from "./ConversationView.styles";
import {
  type ComposerQueueItem,
} from "./composerFollowupQueueModel";

export type ConversationFollowupQueueBarProps = {
  items: readonly ComposerQueueItem[];
  lang: "zh" | "en";
  queueLabel: string;
  editLabel: string;
  withdrawLabel: string;
  onUpdate: (id: string, text: string) => void;
  onRemove: (id: string) => void;
  onMove: (fromIndex: number, toIndex: number) => void;
};

export function ConversationFollowupQueueBar({
  items,
  lang,
  queueLabel,
  editLabel,
  withdrawLabel,
  onUpdate,
  onRemove,
  onMove,
}: ConversationFollowupQueueBarProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState("");
  const dragFrom = useRef<number | null>(null);

  if (!items.length) {
    return null;
  }

  return (
    <div className={styles.followupQueueStack} aria-label={lang === "zh" ? "待发送队列" : "Queued follow-ups"}>
      {items.map((item, index) => {
        const editing = editingId === item.id;
        return (
          <div
            key={item.id}
            className={editing ? `${styles.followupQueueBar} ${styles.followupQueueBarEditing}` : styles.followupQueueBar}
            draggable={!editing}
            onDragStart={() => {
              dragFrom.current = index;
            }}
            onDragOver={(event) => event.preventDefault()}
            onDrop={() => {
              if (dragFrom.current == null) {
                return;
              }
              onMove(dragFrom.current, index);
              dragFrom.current = null;
            }}
          >
            <span className={styles.followupQueueHandle} aria-hidden="true">
              <GripVertical size={14} />
            </span>
            <div className={styles.followupQueueCopy}>
              <span className={styles.followupQueueLabel}>{queueLabel} {index + 1}</span>
              {editing ? (
                <VNativeTextarea
                  className={styles.followupQueueEditor}
                  value={editDraft}
                  minRows={2}
                  aria-label={`${editLabel} ${index + 1}`}
                  onChange={(event) => setEditDraft(event.target.value)}
                />
              ) : (
                <span className={styles.followupQueueText} title={item.text}>{item.text}</span>
              )}
            </div>
            <div className={styles.followupQueueActions}>
              {editing ? (
                <>
                  <VButton
                    density="compact"
                    variant="secondary"
                    onPress={() => {
                      onUpdate(item.id, editDraft);
                      setEditingId(null);
                    }}
                  >
                    {lang === "zh" ? "保存" : "Save"}
                  </VButton>
                  <VButton density="compact" variant="ghost" onPress={() => setEditingId(null)}>
                    {lang === "zh" ? "取消" : "Cancel"}
                  </VButton>
                </>
              ) : (
                <>
                  <VButton
                    density="compact"
                    variant="ghost"
                    isIconOnly
                    aria-label={editLabel}
                    icon={<Pencil size={13} />}
                    onPress={() => {
                      setEditingId(item.id);
                      setEditDraft(item.text);
                    }}
                  />
                  <VButton
                    density="compact"
                    variant="ghost"
                    isIconOnly
                    aria-label={withdrawLabel}
                    icon={<X size={13} />}
                    onPress={() => onRemove(item.id)}
                  />
                </>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
