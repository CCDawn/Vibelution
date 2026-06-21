import { BookPlus, Pencil, Settings2, Trash2 } from "lucide-react";
import type { CSSProperties, PointerEvent } from "react";

import type { SessionSummary } from "../api/types";
import type { TranslationKey } from "../i18n/dictionary";
import styles from "./ChatCodingRoute.module.css";

const MENU_WIDTH = 188;
const MENU_HEIGHT = 164;
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
  deleteDisabled: boolean;
  lang: "zh" | "en";
  position: SessionContextMenuPosition;
  session: SessionSummary;
  t: (key: TranslationKey) => string;
  onAddToReview: (session: SessionSummary) => void;
  onDelete: (session: SessionSummary) => void;
  onOpenAgentConfig?: (session: SessionSummary) => void;
  onRename: (session: SessionSummary) => void;
};

export function SessionContextMenu({
  addToReviewDisabled,
  addToReviewPending,
  deleteDisabled,
  lang,
  position,
  session,
  t,
  onAddToReview,
  onDelete,
  onOpenAgentConfig,
  onRename,
}: SessionContextMenuProps) {
  const viewport = typeof window === "undefined"
    ? undefined
    : { width: window.innerWidth, height: window.innerHeight };
  const style = sessionContextMenuStyle(position, viewport);

  function stopPointerPropagation(event: PointerEvent<HTMLDivElement>) {
    event.stopPropagation();
  }

  return (
    <div
      className={styles.sessionContextMenu}
      style={style}
      role="menu"
      aria-label={lang === "zh" ? "会话操作" : "Session actions"}
      onPointerDown={stopPointerPropagation}
    >
      <button
        type="button"
        role="menuitem"
        className={styles.sessionContextMenuItem}
        onClick={() => onAddToReview(session)}
        disabled={addToReviewDisabled}
        title={
          addToReviewPending
            ? t("addingSessionToReview")
            : addToReviewDisabled
              ? t("addSessionToReviewBusy")
              : t("addSessionToReview")
        }
      >
        <BookPlus size={14} />
        <span>{addToReviewPending ? t("addingSessionToReview") : t("addSessionToReview")}</span>
      </button>
      <button
        type="button"
        role="menuitem"
        className={styles.sessionContextMenuItem}
        onClick={() => onRename(session)}
      >
        <Pencil size={14} />
        <span>{t("renameSession")}</span>
      </button>
      {session.agentId && onOpenAgentConfig ? (
        <button
          type="button"
          role="menuitem"
          className={styles.sessionContextMenuItem}
          onClick={() => onOpenAgentConfig(session)}
          title={lang === "zh" ? "打开当前 Agent 配置" : "Open current Agent configuration"}
        >
          <Settings2 size={14} />
          <span>{lang === "zh" ? "打开 Agent 配置" : "Open Agent config"}</span>
        </button>
      ) : null}
      <button
        type="button"
        role="menuitem"
        className={`${styles.sessionContextMenuItem} ${styles.sessionContextMenuDanger}`}
        onClick={() => onDelete(session)}
        disabled={deleteDisabled}
        title={deleteDisabled ? t("deleteSessionBusy") : t("deleteSession")}
      >
        <Trash2 size={14} />
        <span>{t("deleteSession")}</span>
      </button>
    </div>
  );
}
