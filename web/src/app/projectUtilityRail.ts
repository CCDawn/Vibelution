import { useSyncExternalStore } from "react";
import { EMPTY_CHAT_RIGHT_RAIL, openChatRightRailTab, type ChatRightRailKind, type ChatRightRailModel } from "../routes/chat/chatRightRailModel";
import { storeAgentBroadcastReadAtMs } from "./agentBroadcastBadge";

export type ProjectUtilityKind = "project_tasks" | "project_git" | "project_notices";
export const isProjectUtilityKind = (kind: ChatRightRailKind | undefined): kind is ProjectUtilityKind => Boolean(kind?.startsWith("project_"));
type ProjectUtilityState = { model: ChatRightRailModel; selected: boolean; opened: boolean; hosted: boolean; readAtMs: number };
const initial: ProjectUtilityState = { model: EMPTY_CHAT_RIGHT_RAIL, selected: false, opened: false, hosted: false, readAtMs: 0 };
let state = initial;
const listeners = new Set<() => void>();
function publish(next: ProjectUtilityState) { state = next; listeners.forEach((listener) => listener()); }
export const getProjectUtilityRail = () => state;
function subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; }
export function useProjectUtilityRail() { return useSyncExternalStore(subscribe, getProjectUtilityRail, getProjectUtilityRail); }
/** Transient UI state belongs to this project window, never a Session transcript or shell persistence. */
export function openProjectUtilityRail(kind: ProjectUtilityKind, toggle = true) {
  const hide = toggle && state.opened && state.selected && state.model.activeId === kind;
  publish({ ...state, model: openChatRightRailTab(state.model, { kind }), selected: true, opened: !hide });
}
export function setProjectUtilityModel(model: ChatRightRailModel, selected: boolean) {
  publish({ ...state, model, selected, opened: selected && model.tabs.length > 0 ? true : state.opened });
}
export function selectSessionUtilityRail() { if (state.selected) publish({ ...state, selected: false }); }
export function setProjectUtilityHost(hosted: boolean) { if (state.hosted !== hosted) publish({ ...state, hosted }); }
export function collapseProjectUtilityRail() { if (state.opened) publish({ ...state, opened: false }); }
export function markProjectNoticesSeen(latestEventMs: number) {
  if (latestEventMs <= 0 || latestEventMs <= state.readAtMs) return;
  storeAgentBroadcastReadAtMs(latestEventMs);
  publish({ ...state, readAtMs: latestEventMs });
}
export function resetProjectUtilityRailForTests() { publish(initial); }

/** Project kinds have distinct singleton identities; ordinary side:<n> IDs keep their original semantics. */
export function composeUtilityRail(session: ChatRightRailModel, project: ChatRightRailModel, projectSelected: boolean, order: readonly string[] = []): ChatRightRailModel {
  const all = [...project.tabs, ...session.tabs];
  const rank = new Map(order.map((id, index) => [id, index]));
  const tabs = [...all].sort((a, b) => (rank.get(a.id) ?? order.length + all.indexOf(a)) - (rank.get(b.id) ?? order.length + all.indexOf(b)));
  return { ...session, tabs, closed: [...project.closed, ...session.closed], activeId: projectSelected ? project.activeId ?? session.activeId : session.activeId ?? project.activeId };
}
export function splitUtilityRail(next: ChatRightRailModel, session: ChatRightRailModel, project: ChatRightRailModel) {
  const projectSelected = isProjectUtilityKind(next.tabs.find((tab) => tab.id === next.activeId)?.kind);
  const sessionTabs = next.tabs.filter((tab) => !isProjectUtilityKind(tab.kind));
  const projectTabs = next.tabs.filter((tab) => isProjectUtilityKind(tab.kind));
  const retained = (id: string | null, tabs: ChatRightRailModel["tabs"]) => tabs.some((tab) => tab.id === id) ? id : tabs[0]?.id ?? null;
  return {
    projectSelected,
    order: next.tabs.map((tab) => tab.id),
    session: { ...session, ...next, tabs: sessionTabs, closed: next.closed.filter((tab) => !isProjectUtilityKind(tab.kind)), activeId: projectSelected ? retained(session.activeId, sessionTabs) : retained(next.activeId, sessionTabs) },
    project: { ...project, tabs: projectTabs, closed: next.closed.filter((tab) => isProjectUtilityKind(tab.kind)), activeId: projectSelected ? retained(next.activeId, projectTabs) : retained(project.activeId, projectTabs) },
  };
}
