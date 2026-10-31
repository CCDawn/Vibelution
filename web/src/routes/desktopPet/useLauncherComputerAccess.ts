import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useRef, useState } from "react";
import { launcherAssistantComputer } from "../../api/launcherAssistantComputer";
import type { SessionDetail } from "../../api/types";
import type { ComputerState } from "../../api/types/personalAssistantComputer";
import { computerAccessMatches, latestComputerTurn } from "./launcherComputerAccess";

type Options = {
  detail: SessionDetail | undefined; agentId: string; reading: boolean; epoch: number;
  manualOpen: boolean; onCloseManual: () => void; lang: "zh" | "en";
};

/** Operator state only. A grant never submits a synthetic message or replays a tool. */
export function useLauncherComputerAccess(options: Options) {
  const { detail, agentId, reading, epoch, manualOpen, lang } = options;
  const client = useQueryClient();
  const sessionId = detail?.id || "";
  const turnId = latestComputerTurn(detail);
  const key = ["launcher-assistant", "computer-access", epoch, agentId, sessionId, turnId] as const;
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
  latest.current = { request, options };
  const onDismiss = useCallback(() => {
    const { request, options } = latest.current;
    if (request) setDismissed(previous => [...previous.filter(id => id !== request.id), request.id].slice(-64));
    setNotice("");
    options.onCloseManual();
  }, []);
  const onGranted = (state: ComputerState) => {
    if (!state.available || !state.grantId || !state.window || ["ended", "error"].includes(state.status)) return;
    client.setQueryData(key, state);
    setNotice(lang === "zh" ? "已授权。你可以在对话中让助理继续；结束后可随时取消授权。" : "Access granted. Ask the assistant to continue in chat; you can end access at any time.");
  };
  return { request, state: query.data,
    show: reading && (manualOpen || Boolean(query.data?.grantId) || Boolean(request && !dismissed.includes(request.id))),
    onGranted, onDismiss, notice: query.data?.grantId ? notice : "" };
}
