import { BookPlus, Eraser, Pencil, Settings2, Trash2 } from "lucide-react";
import type { CSSProperties, PointerEvent } from "react";

import type { SessionSummary } from "../api/types";
import { VButton } from "../components/vui";
import type { TranslationKey } from "../i18n/dictionary";
import styles from "./SessionContextMenu.styles";

const MENU_WIDTH = 188;
const MENU_HEIGHT = 204;
const MENU_MARGIN = 12;

export type SessionContextMenuPosition = {
  x: number;
  y: number;
};

export function sessionContextMenuStyle(
  position: SessionContextMenuPosition,
  viewport: { width: number; height: number } | undefined,
): CSSProperties {
  if (!viewport) {
    return {
      left: position.x,
      top: position.y,
    };
  }
  return {
    left: Math.min(position.x, Math.max(MENU_MARGIN, viewport.width - MENU_WIDTH)),
    top: Math.min(position.y, Math.max(MENU_MARGIN, viewport.height - MENU_HEIGHT)),
  };
}

type SessionContextMenuProps = {
  addToReviewDisabled: boolean;
  addToReviewPending: boolean;
  clearHistoryDisabled: boolean;
  clearHistoryPending: boolean;
  clearHistoryVisible: boolean;
  deleteDisabled: boolean;
  lang: "zh" | "en";
  position: SessionContextMenuPosition;
  session: SessionSummary;
  t: (key: TranslationKey) => string;
  onAddToReview: (session: SessionSummary) => void;
  onClearHistory: (session: SessionSummary) => void;
  onDelete: (session: SessionSummary) => void;
  onOpenAgentConfig?: (session: SessionSummary) => void;
  onRename: (session: SessionSummary) => void;
};

function sessionContextMenuIdPart(value: string): string {
  return value.trim().replace(/[^a-zA-Z0-9_-]+/g, "-") || "session";
}

export function SessionContextMenu({
  addToReviewDisabled,
  addToReviewPending,
  clearHistoryDisabled,
  clearHistoryPending,
  clearHistoryVisible,
  deleteDisabled,
  lang,
  position,
  session,
  t,
  onAddToReview,
  onClearHistory,
  onDelete,
  onOpenAgentConfig,
  onRename,
}: SessionContextMenuProps) {
  const viewport = typeof window === "undefined"
    ? undefined
    : { width: window.innerWidth, height: window.innerHeight };
  const style = sessionContextMenuStyle(position, viewport);
  const idPart = sessionContextMenuIdPart(session.id);
  const addToReviewTitle = addToReviewPending
    ? t("addingSessionToReview")
    : addToReviewDisabled
      ? t("addSessionToReviewBusy")
      : t("addSessionToReview");
  const addToReviewDescriptionId = addToReviewDisabled
    ? `session-context-menu-${idPart}-add-to-review-reason`
    : undefined;
  const deleteTitle = deleteDisabled ? t("deleteSessionBusy") : t("deleteSession");
  const deleteDescriptionId = deleteDisabled
    ? `session-context-menu-${idPart}-delete-reason`
    : undefined;
  const clearHistoryTitle = clearHistoryPending
    ? t("clearingSessionHistory")
    : clearHistoryDisabled
      ? t("clearSessionHistoryBusy")
      : t("clearSessionHistory");
  const clearHistoryDescriptionId = clearHistoryDisabled
    ? `session-context-menu-${idPart}-clear-history-reason`
    : undefined;

  function stopPointerPropagation(event: PointerEvent<HTMLDivElement>) {
    event.stopPropagation();
  }

  return (
    <div
      className={styles.sessionContextMenu}
      style={style}
      role="menu"
      aria-label={lang === "zh" ? "会话操作" : "Session actions"}
      aria-busy={addToReviewPending || clearHistoryPending ? true : undefined}
      aria-orientation="vertical"
      onPointerDown={stopPointerPropagation}
    >
      {addToReviewDescriptionId ? (
        <span id={addToReviewDescriptionId} className="sr-only">
          {addToReviewTitle}
        </span>
      ) : null}
      {deleteDescriptionId ? (
        <span id={deleteDescriptionId} className="sr-only">
          {deleteTitle}
        </span>
      ) : null}
      {clearHistoryDescriptionId ? (
        <span id={clearHistoryDescriptionId} className="sr-only">
          {clearHistoryTitle}
        </span>
      ) : null}
      <VButton
        type="button"
        role="menuitem"
        className={styles.sessionContextMenuItem}
        onPress={() => onAddToReview(session)}
        isDisabled={addToReviewDisabled}
        aria-describedby={addToReviewDescriptionId}
        aria-disabled={addToReviewDisabled ? true : undefined}
        icon={<BookPlus size={14} />}
        title={addToReviewTitle}
      >
        {addToReviewPending ? t("addingSessionToReview") : t("addSessionToReview")}
      </VButton>
      <VButton
        type="button"
        role="menuitem"
        className={styles.sessionContextMenuItem}
        onPress={() => onRename(session)}
        icon={<Pencil size={14} />}
      >
        {t("renameSession")}
      </VButton>
      {session.agentId && onOpenAgentConfig ? (
        <VButton
          type="button"
          role="menuitem"
          className={styles.sessionContextMenuItem}
          onPress={() => onOpenAgentConfig(session)}
          icon={<Settings2 size={14} />}
          title={lang === "zh" ? "打开当前 Agent 配置" : "Open current Agent configuration"}
        >
          {lang === "zh" ? "打开 Agent 配置" : "Open Agent config"}
        </VButton>
      ) : null}
      {clearHistoryVisible ? (
        <VButton
          type="button"
          role="menuitem"
          className={styles.sessionContextMenuItem}
          onPress={() => onClearHistory(session)}
          isDisabled={clearHistoryDisabled}
          aria-describedby={clearHistoryDescriptionId}
          aria-disabled={clearHistoryDisabled ? true : undefined}
          icon={<Eraser size={14} />}
          title={clearHistoryTitle}
        >
          {clearHistoryPending ? t("clearingSessionHistory") : t("clearSessionHistory")}
        </VButton>
      ) : null}
      <VButton
        type="button"
        role="menuitem"
        className={`${styles.sessionContextMenuItem} ${styles.sessionContextMenuDanger}`}
        variant="danger"
        onPress={() => onDelete(session)}
        isDisabled={deleteDisabled}
        aria-describedby={deleteDescriptionId}
        aria-disabled={deleteDisabled ? true : undefined}
        icon={<Trash2 size={14} />}
        title={deleteTitle}
      >
        {t("deleteSession")}
      </VButton>
    </div>
  );
}
