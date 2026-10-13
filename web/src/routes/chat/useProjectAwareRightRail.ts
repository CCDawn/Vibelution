import { useCallback, useRef, useState } from "react";
import { composeUtilityRail, getProjectUtilityRail, setProjectUtilityModel, splitUtilityRail, useProjectUtilityRail } from "../../app/projectUtilityRail";
import { EMPTY_CHAT_RIGHT_RAIL, type ChatRightRailModel } from "./chatRightRailModel";

/** Keep original session models local; only the presentation combines them with project tools. */
export function useProjectAwareRightRail(sessionId: string | null) {
  const [railsBySession, setSessionState] = useState<Record<string, ChatRightRailModel>>({});
  const sessions = useRef(railsBySession);
  const orders = useRef<Record<string, string[]>>({});
  const project = useProjectUtilityRail();
  const setRailsBySession = useCallback((update: Record<string, ChatRightRailModel> | ((current: Record<string, ChatRightRailModel>) => Record<string, ChatRightRailModel>)) => {
    const next = typeof update === "function" ? update(sessions.current) : update;
    sessions.current = next;
    setSessionState(next);
  }, []);
  const sessionModel = sessionId ? railsBySession[sessionId] ?? EMPTY_CHAT_RIGHT_RAIL : EMPTY_CHAT_RIGHT_RAIL;
  const railModel = composeUtilityRail(sessionModel, project.model, project.selected, orders.current[sessionId ?? ""]);
  const updateRailModel = useCallback((update: ChatRightRailModel | ((current: ChatRightRailModel) => ChatRightRailModel)) => {
    const session = sessionId ? sessions.current[sessionId] ?? EMPTY_CHAT_RIGHT_RAIL : EMPTY_CHAT_RIGHT_RAIL;
    const currentProject = getProjectUtilityRail();
    const current = composeUtilityRail(session, currentProject.model, currentProject.selected, orders.current[sessionId ?? ""]);
    const next = typeof update === "function" ? update(current) : update;
    const split = splitUtilityRail(next, session, currentProject.model);
    orders.current[sessionId ?? ""] = split.order;
    if (sessionId) setRailsBySession({ ...sessions.current, [sessionId]: split.session });
    setProjectUtilityModel(split.project, split.projectSelected);
  }, [sessionId, setRailsBySession]);
  return { railsBySession, setRailsBySession, railModel, updateRailModel, project };
}
