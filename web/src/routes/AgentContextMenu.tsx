import { Archive, MessageSquareText, Pencil, Plus, Settings2 } from "lucide-react";
import type { CSSProperties } from "react";

import type { AgentInstance, SessionSummary } from "../api/types";
import { VDropdownMenu } from "../components/vui";
import { agentArchiveProtected } from "./agentArchiveProtection";
import styles from "./AgentContextMenu.styles";

const MENU_WIDTH = 188;
const MENU_HEIGHT = 212;
const MENU_MARGIN = 12;

export type AgentContextMenuPosition = {
  x: number;
  y: number;
};

export type AgentContextMenuState = AgentContextMenuPosition & {
  agent: AgentInstance;
  latestSession: SessionSummary | null;
};

export function agentContextMenuStyle(
  position: AgentContextMenuPosition,
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

type AgentContextMenuProps = {
  archivePending: boolean;
  createPending: boolean;
  renamePending: boolean;
  lang: "zh" | "en";
  state: AgentContextMenuState;
  onArchive: (agent: AgentInstance) => void;
  onCreateSession: (agent: AgentInstance) => void;
  onOpenConfig: (agent: AgentInstance, latestSession: SessionSummary | null) => void;
  onOpenLatest: (agent: AgentInstance, latestSession: SessionSummary | null) => void;
  onRename: (agent: AgentInstance) => void;
  /** Called when the Radix menu requests close (select / Escape / dismiss). */
  onDismiss?: () => void;
};

export function agentCanArchiveFromContextMenu(agent: AgentInstance) {
  if (!agent.agentId || String(agent.status || "").trim().toLowerCase() === "archived") {
    return false;
  }
  return !agentArchiveProtected(agent);
}

export function AgentContextMenu({
  archivePending,
  createPending,
  renamePending,
  lang,
  state,
  onArchive,
  onCreateSession,
  onOpenConfig,
  onOpenLatest,
  onRename,
  onDismiss,
}: AgentContextMenuProps) {
  const canArchive = agentCanArchiveFromContextMenu(state.agent);
  const busy = createPending || renamePending || archivePending;

  return (
    <VDropdownMenu
      open
      onOpenChange={(open) => {
        if (!open) {
          onDismiss?.();
        }
      }}
      position={{ x: state.x, y: state.y }}
      aria-label={lang === "zh" ? "Agent 操作" : "Agent actions"}
      contentClassName={styles.sessionContextMenu}
      itemClassName={styles.sessionContextMenuItem}
      dangerItemClassName={styles.sessionContextMenuDanger}
      contentProps={{
        "data-agent-context-menu": state.agent.agentId,
        "aria-busy": busy ? "true" : undefined,
      }}
      items={[
        {
          id: "rename",
          icon: <Pencil size={14} />,
          disabled: renamePending,
          label: renamePending
            ? (lang === "zh" ? "正在重命名" : "Renaming")
            : (lang === "zh" ? "重命名 Agent" : "Rename Agent"),
          onSelect: () => onRename(state.agent),
        },
        {
          id: "open-latest",
          icon: <MessageSquareText size={14} />,
          disabled: !state.latestSession,
          label: lang === "zh" ? "打开最近会话" : "Open latest session",
          onSelect: () => onOpenLatest(state.agent, state.latestSession),
        },
        {
          id: "create-session",
          icon: <Plus size={14} />,
          disabled: createPending,
          label: createPending
            ? (lang === "zh" ? "正在新建会话" : "Creating session")
            : (lang === "zh" ? "新建会话" : "New session"),
          onSelect: () => onCreateSession(state.agent),
        },
        {
          id: "open-config",
          icon: <Settings2 size={14} />,
          label: lang === "zh" ? "打开 Agent 设置" : "Open Agent settings",
          onSelect: () => onOpenConfig(state.agent, state.latestSession),
        },
        ...(canArchive
          ? [{
              id: "archive",
              icon: <Archive size={14} />,
              danger: true,
              disabled: archivePending,
              title: lang === "zh"
                ? "安全归档并保留会话、记忆和日志"
                : "Archive safely and keep sessions, memory, and logs",
              label: archivePending
                ? (lang === "zh" ? "正在归档" : "Archiving")
                : (lang === "zh" ? "安全归档" : "Safe archive"),
              onSelect: () => onArchive(state.agent),
            }]
          : []),
      ]}
    />
  );
}
