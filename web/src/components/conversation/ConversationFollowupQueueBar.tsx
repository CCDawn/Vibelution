import { useRef, useState } from "react";
import { GripVertical, Pencil, X } from "lucide-react";

import { VButton, VNativeInput } from "../vui";
import styles from "./ConversationView.styles";
import {
  type ComposerQueueItem,
} from "./composerFollowupQueueModel";

const VISIBLE_QUEUE_ROWS = 4;

export type ConversationFollowupQueueBarProps = {
  items: readonly ComposerQueueItem[];
  lang: "zh" | "en";
  variant?: "codex" | "compact";
  editLabel: string;
  withdrawLabel: string;
  onUpdate: (id: string, text: string) => void;
  onRemove: (id: string) => void;
  onMove: (fromIndex: number, toIndex: number) => void;
};

export function ConversationFollowupQueueBar({
  items,
  lang,
  variant = "compact",
  editLabel,
  withdrawLabel,
  onUpdate,
  onRemove,
  onMove,
}: ConversationFollowupQueueBarProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState("");
  const [queueExpanded, setQueueExpanded] = useState(false);
  const dragFrom = useRef<number | null>(null);

  if (!items.length) {
    return null;
  }

  const overflowCount = Math.max(0, items.length - VISIBLE_QUEUE_ROWS);
  const visibleItems = queueExpanded || overflowCount === 0
    ? items
    : items.slice(0, VISIBLE_QUEUE_ROWS);

  return (
    <div
      className={
        variant === "codex"
          ? `${styles.followupQueueTray} ${styles.followupQueueTrayBleed}`
          : `${styles.followupQueueTray} ${styles.followupQueueTrayInset}`
      }
      aria-label={lang === "zh" ? "待发送队列" : "Queued follow-ups"}
    >
      <div className={styles.followupQueueHeader}>
        {lang === "zh" ? `排队中 · ${items.length} 条` : `Queued · ${items.length}`}
      </div>
      <div className={styles.followupQueueRows}>
        {visibleItems.map((item, index) => {
          const editing = editingId === item.id;
          return (
            <div
              key={item.id}
              className={editing ? `${styles.followupQueueRow} ${styles.followupQueueRowEditing}` : styles.followupQueueRow}
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
              <span className={styles.followupQueueDrag} aria-hidden="true">
                <GripVertical size={14} />
              </span>
              <span className={styles.followupQueueIndex} aria-hidden="true">{index + 1}</span>
              {editing ? (
                <VNativeInput
                  className={styles.followupQueueEditInput}
                  value={editDraft}
                  aria-label={`${editLabel} ${index + 1}`}
                  onChange={(event) => setEditDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      onUpdate(item.id, editDraft);
                      setEditingId(null);
                    } else if (event.key === "Escape") {
                      setEditingId(null);
                    }
                  }}
                />
              ) : (
                <span className={styles.followupQueueRowText} title={item.text}>{item.text}</span>
              )}
              <div
                className={
                  editing
                    ? `${styles.followupQueueRowActions} ${styles.followupQueueRowActionsEditing}`
                    : styles.followupQueueRowActions
                }
              >
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
      {overflowCount > 0 ? (
        <VButton
          type="button"
          density="compact"
          variant="ghost"
          contentLayout="plain"
          className={styles.followupQueueMore}
          aria-expanded={queueExpanded}
          onPress={() => setQueueExpanded((current) => !current)}
        >
          {queueExpanded
            ? (lang === "zh" ? "收起" : "Show less")
            : (lang === "zh" ? `另有 ${overflowCount} 条 · 展开` : `${overflowCount} more · Show all`)}
        </VButton>
      ) : null}
    </div>
  );
}
