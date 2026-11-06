import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { launcherAssistantComputer } from "../../api/launcherAssistantComputer";
import type { SessionDetail } from "../../api/types";
import type { ComputerState } from "../../api/types/personalAssistantComputer";
import { computerAccessMatches, latestComputerTurn } from "./launcherComputerAccess";
import type { LauncherControlContinuation } from "./useLauncherControlContinuation";

type Options = {
  detail: SessionDetail | undefined; agentId: string; reading: boolean;
  manualOpen: boolean; onCloseManual: () => void; lang: "zh" | "en";
  continuation?: LauncherControlContinuation;
};

/** Polling only projects state; an explicit operator action can continue its bound task. */
export function useLauncherComputerAccess(options: Options) {
  const { detail, agentId, reading, manualOpen, lang } = options;
  const client = useQueryClient();
  const sessionId = detail?.id || "";
  const turnId = latestComputerTurn(detail);
  // A grant belongs to the native identity, not an individual tool call. Keep
  // its controls available through new turns and temporary read failures.
  const key = ["launcher-assistant", "computer-access", agentId, sessionId] as const;
  const [dismissed, setDismissed] = useState<string[]>([]);
  const [notice, setNotice] = useState("");
  const query = useQuery({
    queryKey: key, queryFn: ({ signal }) => launcherAssistantComputer.state({ signal }),
    enabled: reading && Boolean(agentId && sessionId), retry: false,
    refetchInterval: query => reading && Boolean(turnId || manualOpen || query.state.data?.grantId) ? 2_000 : false,
    refetchIntervalInBackground: false,
  });
  const request = !query.isError && Date.now() - query.dataUpdatedAt <= 5_000
    && computerAccessMatches(query.data?.authorizationRequest, detail, agentId)
    ? query.data!.authorizationRequest! : null;
  const latest = useRef({ request, options });
  const knownControl = useRef("");
  latest.current = { request, options };
  useEffect(() => {
    const signature = query.data ? `${query.data.grantId || ""}:${query.data.available}:${query.data.status}` : "";
    const previous = knownControl.current;
    knownControl.current = signature;
    if (previous && signature !== previous && query.data && (!query.data.grantId || !query.data.available
      || ["manual", "paused", "ended", "error"].includes(query.data.status))) {
      latest.current.options.continuation?.cancel();
    }
  }, [query.data]);
  const onDismiss = useCallback(() => {
    const { request, options } = latest.current;
    if (request) setDismissed(previous => [...previous.filter(id => id !== request.id), request.id].slice(-64));
    setNotice("");
    options.onCloseManual();
  }, []);
  const onGranted = (state: ComputerState) => {
    if (!state.available || !state.grantId || !state.window || ["ended", "error"].includes(state.status)) return;
    void client.cancelQueries({ queryKey: key, exact: true });
    client.setQueryData(key, state);
    setNotice(lang === "zh" ? "已授权。结束后可随时取消授权。" : "Access granted. You can end access at any time.");
  };
  const prepareContinuation = useCallback((action: "grant" | "return" | "resume") => {
    const { request, options } = latest.current;
    if (action === "grant" && (!request || !computerAccessMatches(request, options.detail, options.agentId))) return;
    const intent = options.continuation?.capture();
    if (!intent || action === "grant" && intent.origin.turnId !== request?.turnId) return;
    const targetKey = ["launcher-assistant", "computer-access", options.agentId, options.detail?.id || ""] as const;
    return (state: ComputerState) => {
      void client.cancelQueries({ queryKey: targetKey, exact: true });
      client.setQueryData(targetKey, state);
      options.continuation?.complete(intent, () => {
        const current = client.getQueryData<ComputerState>(targetKey);
        return Boolean(current?.available && current.grantId === state.grantId && current.status === "ready" && !current.pending);
      });
    };
  }, [client]);
  const cancelContinuation = useCallback(() => latest.current.options.continuation?.cancel(), []);
  return { request, state: query.data,
    show: reading && (manualOpen || Boolean(query.data?.grantId) || Boolean(request && !dismissed.includes(request.id))),
    onGranted, onDismiss, prepareContinuation, cancelContinuation, notice: query.data?.grantId ? notice : "" };
}
