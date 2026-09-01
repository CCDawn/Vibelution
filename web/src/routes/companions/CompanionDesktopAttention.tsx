import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef } from "react";
import { useLocation } from "react-router-dom";

import { listVirtualHumanCompanionActivity } from "../../api/agentPlugins";
import { queryKeys } from "../../api/queryKeys";
import { postBrowserTelemetry } from "../../app/browserTelemetry";
import { usePageVisibility } from "../../app/pollingPolicy";
import {
  browserDesktopNotificationBridge,
  createDesktopConversationNotifier,
  subscribeCompanionNotificationOpened,
} from "../chatDesktopNotifications";
import { markSessionActivitySeen } from "../sessionActivityIndicator";
import { useChatRouteSelection } from "../chat/useChatRouteSelection";

/** Companion-only observer for hidden native Session activity and notification deep links. */
export function CompanionDesktopAttention() {
  const location = useLocation();
  const pageVisible = usePageVisibility();
  const { openCompanionSession } = useChatRouteSelection();
  const desktopBridge = useMemo(() => browserDesktopNotificationBridge(), []);
  const companionsQuery = useQuery({
    queryKey: queryKeys.virtualHumanCompanionActivity(),
    queryFn: listVirtualHumanCompanionActivity,
    refetchInterval: desktopBridge ? 5_000 : (pageVisible ? 5_000 : false),
    refetchIntervalInBackground: Boolean(desktopBridge),
  });
  const notifierRef = useRef(createDesktopConversationNotifier({
    bridge: desktopBridge,
    postTelemetry: postBrowserTelemetry,
  }));
  const viewedSessionId = useMemo(() => {
    if (location.pathname !== "/chat") {
      return "";
    }
    const params = new URLSearchParams(location.search);
    return params.get("companion") ? String(params.get("session") || "").trim() : "";
  }, [location.pathname, location.search]);
  const summaries = useMemo(() => (
    (companionsQuery.data ?? []).flatMap((companion) => {
      const activity = companion.sessionActivity;
      if (!activity?.id) {
        return [];
      }
      return [{
        ...activity,
        title: companion.displayName,
        agentDisplayName: companion.displayName,
        companionAgentId: companion.agentId,
        completionIdentity: String(activity.activityStamp || "").trim(),
      }];
    })
  ), [companionsQuery.data]);
  const markViewedCompanionSeen = useCallback(() => {
    if (!viewedSessionId || (typeof document !== "undefined" && !document.hasFocus())) {
      return;
    }
    const activity = (companionsQuery.data ?? []).find(
      (companion) => companion.directSessionId === viewedSessionId,
    )?.sessionActivity;
    if (activity) {
      markSessionActivitySeen(viewedSessionId, String(activity.activityStamp || ""));
    }
  }, [companionsQuery.data, viewedSessionId]);

  useEffect(() => {
    notifierRef.current.handleSessionSummaries(summaries, { viewedSessionId });
  }, [summaries, viewedSessionId]);

  useEffect(() => {
    markViewedCompanionSeen();
    if (typeof window === "undefined") {
      return;
    }
    window.addEventListener("focus", markViewedCompanionSeen);
    return () => window.removeEventListener("focus", markViewedCompanionSeen);
  }, [markViewedCompanionSeen]);

  useEffect(() => subscribeCompanionNotificationOpened(
    desktopBridge,
    ({ sessionId, companionAgentId }) => {
      const activity = (companionsQuery.data ?? []).find(
        (companion) => companion.agentId === companionAgentId
          && companion.directSessionId === sessionId,
      )?.sessionActivity;
      if (activity) {
        markSessionActivitySeen(sessionId, String(activity.activityStamp || ""));
      }
      openCompanionSession(sessionId, companionAgentId, {
        returnLabel: "人物大厅",
        telemetrySource: "virtual_human_companion_notification",
      });
    },
  ), [companionsQuery.data, desktopBridge, openCompanionSession]);

  return null;
}
