import { MessageSquareText, Plus, Settings2 } from "lucide-react";
import type { CSSProperties, PointerEvent } from "react";

import type { AgentInstance, SessionSummary } from "../api/types";
import { VButton } from "../components/vui";
import styles from "./SessionContextMenu.styles";

const MENU_WIDTH = 188;
const MENU_HEIGHT = 132;
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
  createPending: boolean;
  lang: "zh" | "en";
  state: AgentContextMenuState;
  onCreateSession: (agent: AgentInstance) => void;
  onOpenConfig: (agent: AgentInstance, latestSession: SessionSummary | null) => void;
  onOpenLatest: (agent: AgentInstance, latestSession: SessionSummary | null) => void;
};

export function AgentContextMenu({
  createPending,
  lang,
  state,
  onCreateSession,
  onOpenConfig,
  onOpenLatest,
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
      aria-busy={createPending ? true : undefined}
      aria-orientation="vertical"
      data-agent-context-menu={state.agent.agentId}
      onPointerDown={stopPointerPropagation}
    >
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
    </div>
  );
}
