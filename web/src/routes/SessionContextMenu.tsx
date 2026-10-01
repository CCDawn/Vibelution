import { Archive, ArchiveRestore, BookPlus, Eraser, Library, Pencil, Pin, PinOff, Settings2, Trash2 } from "lucide-react";
import type { CSSProperties } from "react";

import type { SessionSummary } from "../api/types";
import { VDropdownMenu } from "../components/vui";
import type { TranslationKey } from "../i18n/dictionary";
import styles from "./SessionContextMenu.styles";

const MENU_WIDTH = 188;
const MENU_HEIGHT = 260;
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
  archiveDisabled?: boolean;
  archivePending?: boolean;
  clearHistoryDisabled: boolean;
  clearHistoryPending: boolean;
  clearHistoryVisible: boolean;
  deleteDisabled: boolean;
  lang: "zh" | "en";
  pinDisabled?: boolean;
  pinPending?: boolean;
  position: SessionContextMenuPosition;
  session: SessionSummary;
  t: (key: TranslationKey) => string;
  onAddToReview: (session: SessionSummary) => void;
  onArchive?: (session: SessionSummary) => void;
  onClearHistory: (session: SessionSummary) => void;
  onDelete: (session: SessionSummary) => void;
  onOpenAgentConfig?: (session: SessionSummary) => void;
  onOpenReportLibrary?: (session: SessionSummary) => void;
  onRename: (session: SessionSummary) => void;
  onTogglePin?: (session: SessionSummary) => void;
  onDismiss?: () => void;
};

export function SessionContextMenu({
  addToReviewDisabled,
  addToReviewPending,
  archiveDisabled = false,
  archivePending = false,
  clearHistoryDisabled,
  clearHistoryPending,
  clearHistoryVisible,
  deleteDisabled,
  lang,
  pinDisabled = false,
  pinPending = false,
  position,
  session,
  t,
  onAddToReview,
  onArchive,
  onClearHistory,
  onDelete,
  onOpenAgentConfig,
  onOpenReportLibrary,
  onRename,
  onTogglePin,
  onDismiss,
}: SessionContextMenuProps) {
  const busy = addToReviewPending || clearHistoryPending || archivePending || pinPending;
  const archived = String(session.archiveState?.status || "").trim().toLowerCase() === "archived";
  const pinned = Number(session.pinnedAtMs ?? 0) > 0;
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
  const archiveLabel = archived
    ? (archivePending ? t("unarchivingSession") : t("unarchiveSession"))
    : (archivePending ? t("archivingSession") : t("archiveSession"));
  const archiveTitle = archivePending
    ? archiveLabel
    : archiveDisabled
      ? (archived ? t("unarchiveSessionBusy") : t("archiveSessionBusy"))
      : archiveLabel;

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
          id: "pin",
          icon: pinned ? <PinOff size={14} /> : <Pin size={14} />,
          disabled: pinDisabled || !onTogglePin,
          title: pinPending
            ? (pinned ? t("unpinningSession") : t("pinningSession"))
            : (pinned ? t("unpinSession") : t("pinSession")),
          label: pinned
            ? (pinPending ? t("unpinningSession") : t("unpinSession"))
            : (pinPending ? t("pinningSession") : t("pinSession")),
          onSelect: () => onTogglePin?.(session),
        },
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
        ...(session.agentId && onOpenReportLibrary
          ? [{
              id: "open-report-library",
              icon: <Library size={14} />,
              title: lang === "zh" ? "打开财报知识库" : "Open the report library",
              label: lang === "zh" ? "财报知识库" : "Report library",
              onSelect: () => onOpenReportLibrary(session),
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
        ...(onArchive
          ? [{
              id: "archive",
              icon: archived ? <ArchiveRestore size={14} /> : <Archive size={14} />,
              disabled: archiveDisabled,
              title: archiveTitle,
              label: archiveLabel,
              onSelect: () => onArchive(session),
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
