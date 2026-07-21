import { Archive, MessageSquareText, Pencil, Plus, Settings2 } from "lucide-react";
import type { CSSProperties, PointerEvent } from "react";

import type { AgentInstance, SessionSummary } from "../api/types";
import { VButton } from "../components/vui";
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
};

function metadataFlag(agent: AgentInstance, key: string) {
  const value = agent.metadata?.[key];
  if (typeof value === "boolean") {
    return value;
  }
  return ["1", "true", "yes"].includes(String(value ?? "").trim().toLowerCase());
}

function metadataText(agent: AgentInstance, key: string) {
  const value = agent.metadata?.[key];
  return typeof value === "string" ? value.trim() : "";
}

export function agentCanArchiveFromContextMenu(agent: AgentInstance) {
  if (!agent.agentId || String(agent.status || "").trim().toLowerCase() === "archived") {
    return false;
  }
  const systemOwnedRole = [
    metadataText(agent, "systemRole"),
    metadataText(agent, "selfEvolutionRole"),
    metadataText(agent, "supervisedRole"),
    metadataText(agent, "aiSearchRole"),
  ].some(Boolean);
  const researchOrgRole = metadataText(agent, "researchOrgRole");
  return !(
    metadataFlag(agent, "protected")
    || metadataFlag(agent, "fixedRole")
    || systemOwnedRole
    || ["ceo", "organization_advisor", "capability_steward", "knowledge_steward"].includes(researchOrgRole)
  );
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
}: AgentContextMenuProps) {
  const viewport = typeof window === "undefined"
    ? undefined
    : { width: window.innerWidth, height: window.innerHeight };
  const style = agentContextMenuStyle(state, viewport);

  function stopPointerPropagation(event: PointerEvent<HTMLDivElement>) {
    event.stopPropagation();
  }

  return (
    <div
      className={styles.sessionContextMenu}
      style={style}
      role="menu"
      aria-label={lang === "zh" ? "Agent 操作" : "Agent actions"}
      aria-busy={createPending || renamePending || archivePending ? true : undefined}
      aria-orientation="vertical"
      data-agent-context-menu={state.agent.agentId}
      onPointerDown={stopPointerPropagation}
    >
      <VButton
        type="button"
        role="menuitem"
        className={styles.sessionContextMenuItem}
        onPress={() => onRename(state.agent)}
        isDisabled={renamePending}
        icon={<Pencil size={14} />}
      >
        {renamePending
          ? (lang === "zh" ? "正在重命名" : "Renaming")
          : (lang === "zh" ? "重命名 Agent" : "Rename Agent")}
      </VButton>
      <VButton
        type="button"
        role="menuitem"
        className={styles.sessionContextMenuItem}
        onPress={() => onOpenLatest(state.agent, state.latestSession)}
        isDisabled={!state.latestSession}
        icon={<MessageSquareText size={14} />}
      >
        {lang === "zh" ? "打开最近会话" : "Open latest session"}
      </VButton>
      <VButton
        type="button"
        role="menuitem"
        className={styles.sessionContextMenuItem}
        onPress={() => onCreateSession(state.agent)}
        isDisabled={createPending}
        icon={<Plus size={14} />}
      >
        {createPending
          ? (lang === "zh" ? "正在新建会话" : "Creating session")
          : (lang === "zh" ? "新建会话" : "New session")}
      </VButton>
      <VButton
        type="button"
        role="menuitem"
        className={styles.sessionContextMenuItem}
        onPress={() => onOpenConfig(state.agent, state.latestSession)}
        icon={<Settings2 size={14} />}
      >
        {lang === "zh" ? "打开 Agent 设置" : "Open Agent settings"}
      </VButton>
      {agentCanArchiveFromContextMenu(state.agent) ? (
        <VButton
          type="button"
          role="menuitem"
          className={`${styles.sessionContextMenuItem} ${styles.sessionContextMenuDanger}`}
          variant="danger"
          onPress={() => onArchive(state.agent)}
          isDisabled={archivePending}
          aria-disabled={archivePending ? true : undefined}
          icon={<Archive size={14} />}
          title={lang === "zh" ? "安全归档并保留会话、记忆和日志" : "Archive safely and keep sessions, memory, and logs"}
        >
          {archivePending
            ? (lang === "zh" ? "正在归档" : "Archiving")
            : (lang === "zh" ? "安全归档" : "Safe archive")}
        </VButton>
      ) : null}
    </div>
  );
}
