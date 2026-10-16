import { useCallback, useEffect, useMemo, useState } from "react";

import { isProjectUtilityKind } from "../../app/projectUtilityRail";
import {
  classifySessionBarDrop,
  type DockedSession,
  type PaneDockPayload,
  type SessionBarDockChip,
} from "./chatPaneDock";
import {
  activeChatRightRailTab,
  chatRightRailTabLabel,
  closeChatRightRailTab,
  EMPTY_CHAT_RIGHT_RAIL,
  setChatRightRailTabHost,
  type ChatRightRailModel,
  type ChatRightRailTab,
} from "./chatRightRailModel";

type RailModelUpdate = ChatRightRailModel | ((current: ChatRightRailModel) => ChatRightRailModel);
type RailsBySessionUpdate = Record<string, ChatRightRailModel> | ((current: Record<string, ChatRightRailModel>) => Record<string, ChatRightRailModel>);

export type CenterPresentation = {
  scope: "session" | "project";
  sessionId: string;
  tabId: string;
};

export function useChatPaneDock({
  routeSessionId,
  railOwnerId,
  railModel,
  railsBySession,
  projectModel,
  updateRailModel,
  setRailsBySession,
  lang,
  openSession,
  revealRightRail,
  groupPanelActive,
  sessionBrowserVisible,
}: {
  routeSessionId: string | null;
  railOwnerId: string;
  railModel: ChatRightRailModel;
  railsBySession: Record<string, ChatRightRailModel>;
  projectModel: ChatRightRailModel;
  updateRailModel: (update: RailModelUpdate) => void;
  setRailsBySession: (update: RailsBySessionUpdate) => void;
  lang: "zh" | "en";
  openSession: (sessionId: string) => void;
  revealRightRail: () => void;
  groupPanelActive: boolean;
  sessionBrowserVisible: boolean;
}) {
  const [dockedSessions, setDockedSessions] = useState<DockedSession[]>([]);
  const [activeDockedSessionId, setActiveDockedSessionId] = useState<string | null>(null);
  const [centerPresentation, setCenterPresentation] = useState<CenterPresentation | null>(null);
  const [parkHost, setParkHost] = useState<HTMLDivElement | null>(null);
  const [centerHost, setCenterHost] = useState<HTMLDivElement | null>(null);

  const onDockHostChange = useCallback((node: HTMLDivElement | null) => {
    setParkHost(node);
  }, []);
  const onCenterHostChange = useCallback((node: HTMLDivElement | null) => {
    setCenterHost(node);
  }, []);

  const dockedSessionIds = useMemo(
    () => new Set(dockedSessions.map((item) => item.sessionId)),
    [dockedSessions],
  );

  const undockSession = useCallback((sessionId: string) => {
    const id = sessionId.trim();
    if (!id) {
      return;
    }
    setDockedSessions((current) => current.filter((item) => item.sessionId !== id));
    setActiveDockedSessionId((current) => (current === id ? null : current));
  }, []);

  const releaseCenterTab = useCallback(() => {
    updateRailModel((current) => {
      const active = current.tabs.find((tab) => tab.id === current.activeId);
      if (active?.host !== "center") {
        return current;
      }
      const next = current.tabs.find((tab) => tab.host !== "center");
      return { ...current, activeId: next?.id ?? null };
    });
  }, [updateRailModel]);

  const dismissCenter = useCallback(() => {
    setCenterPresentation(null);
    releaseCenterTab();
  }, [releaseCenterTab]);

  const dockSession = useCallback((input: { sessionId: string; title: string }) => {
    const sessionId = input.sessionId.trim();
    if (!sessionId) {
      return;
    }
    const title = input.title.trim() || sessionId;
    setDockedSessions((current) => {
      const existing = current.find((item) => item.sessionId === sessionId);
      if (existing) {
        return current.map((item) => (item.sessionId === sessionId ? { sessionId, title } : item));
      }
      return [...current, { sessionId, title }];
    });
    setActiveDockedSessionId(sessionId);
    setCenterPresentation(null);
    releaseCenterTab();
    revealRightRail();
  }, [releaseCenterTab, revealRightRail]);

  const focusDockedSession = useCallback((sessionId: string) => {
    setActiveDockedSessionId(sessionId);
    setCenterPresentation(null);
    releaseCenterTab();
    revealRightRail();
  }, [releaseCenterTab, revealRightRail]);

  const clearDockedFocus = useCallback(() => {
    setActiveDockedSessionId(null);
  }, []);

  const placeTab = useCallback((
    scope: "session" | "project",
    sessionId: string,
    tabId: string,
    host: "rail" | "center",
  ) => {
    if (scope === "project" || sessionId === railOwnerId) {
      updateRailModel((current) => setChatRightRailTabHost(current, tabId, host));
      return;
    }
    setRailsBySession((current) => {
      const model = current[sessionId] ?? EMPTY_CHAT_RIGHT_RAIL;
      return { ...current, [sessionId]: setChatRightRailTabHost(model, tabId, host) };
    });
  }, [railOwnerId, setRailsBySession, updateRailModel]);

  const closeOwnedTab = useCallback((scope: "session" | "project", sessionId: string, tabId: string) => {
    if (scope === "project" || sessionId === railOwnerId) {
      updateRailModel((current) => closeChatRightRailTab(current, tabId));
      return;
    }
    setRailsBySession((current) => {
      const model = current[sessionId] ?? EMPTY_CHAT_RIGHT_RAIL;
      return { ...current, [sessionId]: closeChatRightRailTab(model, tabId) };
    });
  }, [railOwnerId, setRailsBySession, updateRailModel]);

  const presentCenter = useCallback((presentation: CenterPresentation) => {
    setCenterPresentation(presentation);
    setActiveDockedSessionId(null);
    if (presentation.scope === "session" && presentation.sessionId !== railOwnerId) {
      openSession(presentation.sessionId);
      return;
    }
    updateRailModel((current) => (
      current.tabs.some((tab) => tab.id === presentation.tabId)
        ? { ...current, activeId: presentation.tabId }
        : current
    ));
  }, [openSession, railOwnerId, updateRailModel]);

  useEffect(() => {
    if (!centerPresentation || centerPresentation.scope !== "session" || centerPresentation.sessionId !== railOwnerId) {
      return;
    }
    updateRailModel((current) => {
      const tab = current.tabs.find((item) => item.id === centerPresentation.tabId && item.host === "center");
      if (!tab || current.activeId === tab.id) {
        return current;
      }
      return { ...current, activeId: tab.id };
    });
  }, [centerPresentation, railOwnerId, updateRailModel]);

  useEffect(() => {
    if (!centerPresentation) {
      return;
    }
    const tabs = centerPresentation.scope === "project"
      ? projectModel.tabs
      : (railsBySession[centerPresentation.sessionId]?.tabs ?? []);
    const alive = tabs.some((tab) => tab.id === centerPresentation.tabId && tab.host === "center");
    if (!alive) {
      setCenterPresentation(null);
    }
  }, [centerPresentation, projectModel.tabs, railsBySession]);

  const onSurfaceDrop = useCallback((payload: PaneDockPayload) => {
    if (payload.source === "session") {
      dockSession(payload);
      return;
    }
    const decision = classifySessionBarDrop(payload, null);
    if (decision.action === "restore-session") {
      focusDockedSession(decision.sessionId);
      return;
    }
    const scope = payload.scope === "project" ? "project" : "session";
    const sessionId = payload.sessionId || railOwnerId;
    placeTab(scope, sessionId, payload.tabId, "rail");
    setCenterPresentation((current) => (
      current?.tabId === payload.tabId && (scope === "project" || current.sessionId === sessionId) ? null : current
    ));
    setActiveDockedSessionId(null);
    revealRightRail();
  }, [dockSession, focusDockedSession, placeTab, railOwnerId, revealRightRail]);

  const onSessionBarDrop = useCallback((payload: PaneDockPayload) => {
    const tab = payload.source === "rail"
      ? findRailTab(railModel, railsBySession, projectModel, payload)
      : null;
    const decision = classifySessionBarDrop(payload, tab);
    if (decision.action === "restore-session") {
      undockSession(decision.sessionId);
      dismissCenter();
      openSession(decision.sessionId);
      return;
    }
    if (decision.action === "open-session") {
      const scope = payload.source === "rail" && payload.scope === "project" ? "project" : "session";
      closeOwnedTab(scope, payload.source === "rail" ? (payload.sessionId || railOwnerId) : railOwnerId, decision.closeTabId);
      dismissCenter();
      openSession(decision.sessionId);
      return;
    }
    if (decision.action === "show-in-center" && payload.source === "rail") {
      const scope = payload.scope === "project" || (tab && isProjectUtilityKind(tab.kind)) ? "project" : "session";
      const sessionId = payload.sessionId || railOwnerId;
      placeTab(scope, sessionId, decision.tabId, "center");
      presentCenter({ scope, sessionId, tabId: decision.tabId });
    }
  }, [closeOwnedTab, dismissCenter, openSession, placeTab, presentCenter, projectModel, railModel, railOwnerId, railsBySession, undockSession]);

  const chips = useMemo(() => {
    const sessionChips = Object.entries(railsBySession).flatMap(([sessionId, model]) => (
      model.tabs.filter((tab) => tab.host === "center").map((tab) => toChip(sessionId, "session", tab, centerPresentation, lang))
    ));
    const projectChips = projectModel.tabs
      .filter((tab) => tab.host === "center")
      .map((tab) => toChip(railOwnerId, "project", tab, centerPresentation, lang));
    return [...sessionChips, ...projectChips];
  }, [centerPresentation, lang, projectModel.tabs, railOwnerId, railsBySession]);

  const selectChip = useCallback((chip: SessionBarDockChip) => {
    presentCenter({ scope: chip.scope, sessionId: chip.sessionId, tabId: chip.tabId });
  }, [presentCenter]);

  const closeChip = useCallback((chip: SessionBarDockChip) => {
    closeOwnedTab(chip.scope, chip.sessionId, chip.tabId);
    setCenterPresentation((current) => (
      current?.tabId === chip.tabId && current.scope === chip.scope && (chip.scope === "project" || current.sessionId === chip.sessionId)
        ? null
        : current
    ));
  }, [closeOwnedTab]);

  const activeTab = activeChatRightRailTab(railModel);
  const showCenterPane = Boolean(
    centerPresentation
    && activeTab?.host === "center"
    && activeTab.id === centerPresentation.tabId
    && (centerPresentation.scope === "project" || centerPresentation.sessionId === railOwnerId),
  );
  const parkedSessionId = routeSessionId && dockedSessionIds.has(routeSessionId) ? routeSessionId : null;
  const portalWorkspace = Boolean(parkedSessionId && parkHost);
  const showParkedNote = portalWorkspace && !groupPanelActive && !showCenterPane && !sessionBrowserVisible;

  return {
    dockedSessions,
    dockedSessionIds,
    activeDockedSessionId,
    chips,
    parkHost,
    centerHost,
    showCenterPane,
    portalWorkspace,
    showParkedNote,
    parkedSessionId,
    undockSession,
    dismissCenter,
    onDockHostChange,
    onCenterHostChange,
    railPaneDock: {
      dockedSessions,
      activeDockedSessionId,
      parkSessionId: parkedSessionId,
      centerHost,
      showCenterPane,
      ownerSessionId: railOwnerId,
      onDockHostChange,
      onDockSession: dockSession,
      onFocusDockedSession: focusDockedSession,
      onUndockSession: undockSession,
      onClearDockedFocus: clearDockedFocus,
      onSurfaceDrop,
      onPresentCenter: (tabId: string) => {
        const tab = railModel.tabs.find((item) => item.id === tabId);
        if (!tab) {
          return;
        }
        presentCenter({
          scope: isProjectUtilityKind(tab.kind) ? "project" : "session",
          sessionId: railOwnerId,
          tabId,
        });
      },
      onDismissCenter: () => {
        dismissCenter();
      },
    },
    onSessionBarDrop,
    selectChip,
    closeChip,
  };
}

function findRailTab(
  railModel: ChatRightRailModel,
  railsBySession: Record<string, ChatRightRailModel>,
  projectModel: ChatRightRailModel,
  payload: Extract<PaneDockPayload, { source: "rail" }>,
): ChatRightRailTab | null {
  if (payload.scope === "project") {
    return projectModel.tabs.find((tab) => tab.id === payload.tabId) ?? railModel.tabs.find((tab) => tab.id === payload.tabId) ?? null;
  }
  const owned = payload.sessionId ? railsBySession[payload.sessionId] : undefined;
  return owned?.tabs.find((tab) => tab.id === payload.tabId)
    ?? railModel.tabs.find((tab) => tab.id === payload.tabId)
    ?? null;
}

function toChip(
  sessionId: string,
  scope: "session" | "project",
  tab: ChatRightRailTab,
  presentation: CenterPresentation | null,
  lang: "zh" | "en",
): SessionBarDockChip {
  return {
    key: `${scope}:${sessionId}:${tab.id}`,
    tabId: tab.id,
    sessionId,
    scope,
    title: chatRightRailTabLabel(tab, lang),
    active: presentation?.scope === scope && presentation.tabId === tab.id && (scope === "project" || presentation.sessionId === sessionId),
  };
}
