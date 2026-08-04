import { BookPlus, Eraser, Pencil, Settings2, Trash2 } from "lucide-react";
import type { CSSProperties } from "react";

import type { SessionSummary } from "../api/types";
import { VDropdownMenu } from "../components/vui";
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
  onDismiss?: () => void;
};

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
  onDismiss,
}: SessionContextMenuProps) {
  const busy = addToReviewPending || clearHistoryPending;
  const addToReviewTitle = addToReviewPending
    ? t("addingSessionToReview")
    : addToReviewDisabled
      ? t("addSessionToReviewBusy")
      : t("addSessionToReview");
  const deleteTitle = deleteDisabled ? t("deleteSessionBusy") : t("deleteSession");
  const clearHistoryTitle = clearHistoryPending
    ? t("clearingSessionHistory")
    : clearHistoryDisabled
      ? t("clearSessionHistoryBusy")
      : t("clearSessionHistory");

  return (
    <VDropdownMenu
      open
      onOpenChange={(open) => {
        if (!open) {
          onDismiss?.();
        }
      }}
      position={position}
      aria-label={lang === "zh" ? "会话操作" : "Session actions"}
      contentClassName={styles.sessionContextMenu}
      itemClassName={styles.sessionContextMenuItem}
      dangerItemClassName={styles.sessionContextMenuDanger}
      contentProps={{
        "aria-busy": busy ? "true" : undefined,
      }}
      items={[
        {
          id: "add-to-review",
          icon: <BookPlus size={14} />,
          disabled: addToReviewDisabled,
          title: addToReviewTitle,
          label: addToReviewPending ? t("addingSessionToReview") : t("addSessionToReview"),
          onSelect: () => onAddToReview(session),
        },
        {
          id: "rename",
          icon: <Pencil size={14} />,
          label: t("renameSession"),
          onSelect: () => onRename(session),
        },
        ...(session.agentId && onOpenAgentConfig
          ? [{
              id: "open-agent-config",
              icon: <Settings2 size={14} />,
              title: lang === "zh" ? "打开当前 Agent 配置" : "Open current Agent configuration",
              label: lang === "zh" ? "打开 Agent 配置" : "Open Agent config",
              onSelect: () => onOpenAgentConfig(session),
            }]
          : []),
        ...(clearHistoryVisible
          ? [{
              id: "clear-history",
              icon: <Eraser size={14} />,
              disabled: clearHistoryDisabled,
              title: clearHistoryTitle,
              label: clearHistoryPending ? t("clearingSessionHistory") : t("clearSessionHistory"),
              onSelect: () => onClearHistory(session),
            }]
          : []),
        {
          id: "delete",
          icon: <Trash2 size={14} />,
          danger: true,
          disabled: deleteDisabled,
          title: deleteTitle,
          label: t("deleteSession"),
          onSelect: () => onDelete(session),
        },
      ]}
    />
  );
}
