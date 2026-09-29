import { createContext, useContext, useRef, useState, type DragEvent, type KeyboardEvent, type ReactNode } from "react";
import { ArrowRight, GripVertical, Paperclip, Pause, Pencil, Play, X } from "lucide-react";

import { VButton, VNativeInput, VTooltip } from "../vui";
import styles from "./ConversationView.styles";
import barStyles from "./ConversationFollowupQueueBar.styles";
import {
  type ComposerQueueItem,
} from "./composerFollowupQueueModel";

const VISIBLE_QUEUE_ROWS = 4;

/** ZCode-style two-part tooltip: strong title line + muted description line. */
function tooltipTitleDescription(title: string, description: string): ReactNode {
  return (
    <span className={barStyles.tooltipContent}>
      <span className={barStyles.tooltipTitle}>{title}</span>
      <span className={barStyles.tooltipDescription}>{description}</span>
    </span>
  );
}

/**
 * Pause/resume reaches the bar without prop drilling through ConversationView
 * (whose props surface is owned by the timeline task): the workbench provides
 * the handler around the conversation surface and the bar consumes it here.
 * A direct `onTogglePause` prop always wins when present.
 */
export type FollowupQueueTogglePauseAction = (id: string, paused: boolean) => void;

export const FollowupQueueTogglePauseContext = createContext<FollowupQueueTogglePauseAction | null>(null);

export type ConversationFollowupQueueBarProps = {
  items: readonly ComposerQueueItem[];
  lang: "zh" | "en";
  variant?: "codex" | "compact";
  editLabel: string;
  withdrawLabel: string;
  steerLabel?: string;
  /** Dictionary-backed editing copy; falls back to the zh/en literals. */
  saveEditLabel?: string;
  cancelEditLabel?: string;
  dragHandleLabel?: string;
  onUpdate: (id: string, text: string) => void;
  onRemove: (id: string) => void;
  onMove: (fromIndex: number, toIndex: number) => void;
  onSteer?: (id: string) => void;
  onTogglePause?: FollowupQueueTogglePauseAction;
};

export function ConversationFollowupQueueBar({
  items,
  lang,
  variant = "compact",
  editLabel,
  withdrawLabel,
  steerLabel,
  saveEditLabel,
  cancelEditLabel,
  dragHandleLabel,
  onUpdate,
  onRemove,
  onMove,
  onSteer,
  onTogglePause,
}: ConversationFollowupQueueBarProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState("");
  const [queueExpanded, setQueueExpanded] = useState(false);
  // Drag bookkeeping lives in state (not a ref) so the source row, the
  // insertion indicator and the hover lock re-render while dragging. The ref
  // mirrors the source index for the event handlers: dragover/drop can fire
  // before React re-renders after dragstart, so the state closure is stale.
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);
  const dragIndexRef = useRef<number | null>(null);
  const contextTogglePause = useContext(FollowupQueueTogglePauseContext);
  const togglePause = onTogglePause ?? contextTogglePause ?? undefined;

  const resolvedSaveEditLabel = saveEditLabel ?? (lang === "zh" ? "保存" : "Save");
  const resolvedCancelEditLabel = cancelEditLabel ?? (lang === "zh" ? "取消" : "Cancel");
  const resolvedDragHandleLabel = dragHandleLabel
    ?? (lang === "zh"
      ? "拖动调整顺序；聚焦后按上下方向键移动"
      : "Drag to reorder; focus and use ArrowUp/ArrowDown to move");

  const clearDragState = () => {
    dragIndexRef.current = null;
    setDragIndex(null);
    setDragOverIndex(null);
  };

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
      data-queue-drag-active={dragIndex != null ? "true" : undefined}
    >
      <div className={styles.followupQueueHeader}>
        {lang === "zh" ? `排队中 · ${items.length} 条` : `Queued · ${items.length}`}
      </div>
      <div className={styles.followupQueueRows}>
        {visibleItems.map((item, index) => {
          const editing = editingId === item.id;
          const paused = item.status === "paused";
          const systemReturn = item.kind === "task_notification" || item.kind === "subagent_message";
          const canTogglePause = !systemReturn && Boolean(togglePause) && (item.status === "queued" || paused);
          // Only the explicit grip handle drags: system returns and the row
          // being edited never reorder, and a single row has nothing to swap.
          const canDrag = !editing && !systemReturn && items.length > 1;
          const rowClassName = [
            editing
              ? `${styles.followupQueueRow} ${styles.followupQueueRowEditing}`
              : paused
                ? `${styles.followupQueueRow} ${styles.followupQueueRowPaused}`
                : styles.followupQueueRow,
            dragIndex === index ? barStyles.followupQueueRowDragSource : "",
            dragOverIndex === index && dragIndex != null && dragIndex < index
              ? barStyles.followupQueueRowDropAfter
              : "",
            dragOverIndex === index && dragIndex != null && dragIndex > index
              ? barStyles.followupQueueRowDropBefore
              : "",
            dragIndex != null ? barStyles.followupQueueRowDragLock : "",
          ].filter(Boolean).join(" ");
          const handleDragStart = canDrag
            ? (event: DragEvent<HTMLElement>) => {
                const dataTransfer = event.dataTransfer;
                dataTransfer?.setData?.("text/plain", item.id);
                if (dataTransfer) {
                  dataTransfer.effectAllowed = "move";
                }
                dragIndexRef.current = index;
                setDragIndex(index);
                setDragOverIndex(null);
              }
            : undefined;
          const handleKeyDown = canDrag
            ? (event: KeyboardEvent<HTMLElement>) => {
                // Keyboard reorder path on the focused handle: no drag needed.
                if (event.key === "ArrowUp" && index > 0) {
                  event.preventDefault();
                  onMove(index, index - 1);
                } else if (event.key === "ArrowDown" && index < items.length - 1) {
                  event.preventDefault();
                  onMove(index, index + 1);
                }
              }
            : undefined;
          return (
            <div
              key={item.id}
              className={rowClassName}
              onDragOver={(event) => {
                if (dragIndexRef.current == null) {
                  return;
                }
                event.preventDefault();
                if (event.dataTransfer) {
                  event.dataTransfer.dropEffect = "move";
                }
                setDragOverIndex(index);
              }}
              onDragLeave={(event) => {
                if (dragOverIndex !== index) {
                  return;
                }
                const nextTarget = event.relatedTarget as Node | null;
                if (nextTarget && event.currentTarget.contains(nextTarget)) {
                  return;
                }
                setDragOverIndex(null);
              }}
              onDrop={(event) => {
                event.preventDefault();
                const fromIndex = dragIndexRef.current;
                if (fromIndex != null && fromIndex !== index) {
                  onMove(fromIndex, index);
                }
                clearDragState();
              }}
            >
              {canDrag ? (
                <VButton
                  type="button"
                  density="compact"
                  variant="ghost"
                  isIconOnly
                  className={barStyles.followupQueueDragHandle}
                  aria-label={resolvedDragHandleLabel}
                  icon={<GripVertical size={12} />}
                  draggable
                  onDragStart={handleDragStart}
                  onDragEnd={clearDragState}
                  onKeyDown={handleKeyDown}
                />
              ) : (
                <span className={styles.followupQueueDrag} aria-hidden="true">
                  <GripVertical size={14} />
                </span>
              )}
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
                <span className={styles.followupQueueRowMain}>
                  {systemReturn ? (
                    <span className={styles.followupQueueChip}>
                      {item.kind === "subagent_message"
                        ? (lang === "zh" ? "子对话" : "Child")
                        : (lang === "zh" ? "后台" : "Background")}
                    </span>
                  ) : null}
                  <span className={styles.followupQueueRowText} title={item.text}>{item.text}</span>
                  {item.attachmentCount ? (
                    <VTooltip
                      width="compact"
                      content={
                        lang === "zh"
                          ? `${item.attachmentCount} 个附件`
                          : `${item.attachmentCount} attachment(s)`
                      }
                    >
                      <span className={styles.followupQueueChip}>
                        <Paperclip size={11} />
                        {item.attachmentCount}
                      </span>
                    </VTooltip>
                  ) : null}
                  {item.status === "blocked" ? (
                    <VTooltip
                      width="compact"
                      content={tooltipTitleDescription(
                        lang === "zh" ? "发送失败" : "Send failed",
                        item.lastError
                          || (lang === "zh" ? "上一条发送失败，编辑后可重试" : "The last attempt failed; edit to retry."),
                      )}
                    >
                      <span className={styles.followupQueueChipBlocked}>
                        {lang === "zh" ? "发送失败" : "Failed"}
                      </span>
                    </VTooltip>
                  ) : null}
                  {paused ? (
                    <span className={`${styles.followupQueueChip} ${styles.followupQueueChipPaused}`}>
                      {lang === "zh" ? "已暂停" : "Paused"}
                    </span>
                  ) : null}
                </span>
              )}
              <div
                className={[
                  editing
                    ? `${styles.followupQueueRowActions} ${styles.followupQueueRowActionsEditing}`
                    : styles.followupQueueRowActions,
                  dragIndex != null ? barStyles.followupQueueRowActionsDragLock : "",
                ].filter(Boolean).join(" ")}
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
                      {resolvedSaveEditLabel}
                    </VButton>
                    <VButton density="compact" variant="ghost" onPress={() => setEditingId(null)}>
                      {resolvedCancelEditLabel}
                    </VButton>
                  </>
                ) : (
                  <>
                    {canTogglePause ? (
                      <VButton
                        density="compact"
                        variant="ghost"
                        isIconOnly
                        aria-label={
                          paused
                            ? (lang === "zh" ? "恢复发送，排到队尾" : "Resume sending; moves to the end of the queue")
                            : (lang === "zh" ? "暂停发送" : "Pause sending")
                        }
                        icon={paused ? <Play size={13} /> : <Pause size={13} />}
                        onPress={() => {
                          if (togglePause) {
                            togglePause(item.id, !paused);
                          }
                        }}
                      />
                    ) : null}
                    {onSteer && !systemReturn ? (
                      <VButton
                        density="compact"
                        variant="ghost"
                        isIconOnly
                        isDisabled={item.canSteer === false}
                        aria-label={steerLabel ?? (lang === "zh" ? "立即引导" : "Steer now")}
                        icon={<ArrowRight size={13} />}
                        onPress={() => onSteer(item.id)}
                      />
                    ) : null}
                    {systemReturn ? null : (
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
                    )}
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
