import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation } from "react-router-dom";
import { fetchSessionDetail } from "../../api/chat";
import { createPersonalAssistant, fetchPersonalAssistant } from "../../api/personalAssistant";
import { queryKeys } from "../../api/queryKeys";
import { useChatRouteSelection } from "../chat/useChatRouteSelection";
import { personalAssistantSessionMatches, validPersonalAssistant } from "./personalAssistantModel";

/** A page visit explicitly provisions/restores the singleton; reads elsewhere stay pure. */
export function usePersonalAssistant(enabled = true) {
  const route = useChatRouteSelection();
  const location = useLocation();
  const setup = useQuery({
    queryKey: queryKeys.personalAssistant(),
    queryFn: async ({ signal }) => {
      const result = await fetchPersonalAssistant({ signal });
      if (signal.aborted) throw new DOMException("Aborted", "AbortError");
      return !result.assistant || result.assistant.setupStatus !== "ready" ? createPersonalAssistant() : result;
    },
    enabled, staleTime: Infinity, retry: false, refetchOnWindowFocus: false,
  });
  const assistant = setup.data?.assistant;
  const ready = validPersonalAssistant(assistant);
  const binding = useQuery({
    queryKey: queryKeys.personalAssistantBinding(assistant?.agentId ?? "", assistant?.directSessionId ?? ""),
    queryFn: ({ signal }) => fetchSessionDetail(assistant!.directSessionId, { signal, transcriptScope: "none", includeSecondary: false }),
    enabled: enabled && ready, staleTime: 0, retry: false,
  });
  useEffect(() => {
    if (enabled && ready && route.selection.kind === "bare") {
      route.replaceIfStillViewing(route.selection, { kind: "session", sessionId: assistant.directSessionId });
    }
  }, [enabled, ready, assistant, route]);
  const selectionMatches = ready && route.selection.kind === "session" && route.selection.sessionId === assistant.directSessionId
    && !new URLSearchParams(location.search).get("companion");
  return { setup, binding, assistant, route, ready,
    verified: enabled && ready && selectionMatches && !binding.isError && personalAssistantSessionMatches(assistant, binding.data),
    selectionMismatch: ready && route.selection.kind !== "bare" && !selectionMatches,
  };
}
