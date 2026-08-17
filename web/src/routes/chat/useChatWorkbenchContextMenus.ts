import {
  useEffect,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";

import type { AgentContextMenuState } from "../AgentContextMenu";
import { eventInsideContextMenuSurface } from "./chatContextMenuDismiss";
import type { SessionContextMenuState } from "./useChatSessionRenameMenu";

export type UseChatWorkbenchContextMenusResult = {
  sessionContextMenu: SessionContextMenuState | null;
  setSessionContextMenu: Dispatch<SetStateAction<SessionContextMenuState | null>>;
  agentContextMenu: AgentContextMenuState | null;
  setAgentContextMenu: Dispatch<SetStateAction<AgentContextMenuState | null>>;
};

/**
 * Session/Agent context-menu open state plus global dismiss (pointer/scroll/Escape).
 * Menu JSX stays in the workbench slots; this hook only owns chrome state.
 */
export function useChatWorkbenchContextMenus(): UseChatWorkbenchContextMenusResult {
  const [sessionContextMenu, setSessionContextMenu] = useState<SessionContextMenuState | null>(null);
  const [agentContextMenu, setAgentContextMenu] = useState<AgentContextMenuState | null>(null);

  useEffect(() => {
    if (!sessionContextMenu && !agentContextMenu) {
      return;
    }
    function closeSessionContextMenu(event?: Event) {
      // Radix portals the menu outside the React tree; a global pointerdown must
      // not unmount it before item onSelect (rename/create) can run.
      if (event && eventInsideContextMenuSurface(event.target)) {
        return;
      }
      setSessionContextMenu(null);
      setAgentContextMenu(null);
    }
    function handleKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") {
        closeSessionContextMenu();
      }
    }
    window.addEventListener("pointerdown", closeSessionContextMenu);
    window.addEventListener("scroll", closeSessionContextMenu, true);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("pointerdown", closeSessionContextMenu);
      window.removeEventListener("scroll", closeSessionContextMenu, true);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [agentContextMenu, sessionContextMenu]);

  return {
    sessionContextMenu,
    setSessionContextMenu,
    agentContextMenu,
    setAgentContextMenu,
  };
}
