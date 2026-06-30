import { BookPlus, Pencil, Settings2, Trash2 } from "lucide-react";
import type { CSSProperties, PointerEvent } from "react";

import type { SessionSummary } from "../api/types";
import { VButton } from "../components/vui";
import type { TranslationKey } from "../i18n/dictionary";
import styles from "./ChatCodingRoute.styles";

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
      <VButton
        type="button"
        role="menuitem"
        className={styles.sessionContextMenuItem}
        onPress={() => onAddToReview(session)}
        isDisabled={addToReviewDisabled}
        icon={<BookPlus size={14} />}
        title={
          addToReviewPending
            ? t("addingSessionToReview")
            : addToReviewDisabled
              ? t("addSessionToReviewBusy")
              : t("addSessionToReview")
        }
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
      <VButton
        type="button"
        role="menuitem"
        className={`${styles.sessionContextMenuItem} ${styles.sessionContextMenuDanger}`}
        variant="danger"
        onPress={() => onDelete(session)}
        isDisabled={deleteDisabled}
        icon={<Trash2 size={14} />}
        title={deleteDisabled ? t("deleteSessionBusy") : t("deleteSession")}
      >
        {t("deleteSession")}
      </VButton>
    </div>
  );
}
