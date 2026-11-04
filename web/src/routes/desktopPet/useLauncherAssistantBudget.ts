import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getLauncherAssistantBudget, launcherAssistantBudgetQueryKey, setLauncherAssistantBudget } from "../../api/launcherAssistant";
import type { SessionBudgetParameters } from "../../api/types";
import type { ChatComposerBudgetControl, ChatComposerBudgetParametersPatch } from "../chat/ChatComposerBudgetPopover";

/** Fixed assistant bridge owns storage; this hook only projects its CAS view. */
export function useLauncherAssistantBudget(sessionId: string, agentId: string, lang: "zh" | "en"): ChatComposerBudgetControl | undefined {
  const client = useQueryClient();
  const key = launcherAssistantBudgetQueryKey(agentId, sessionId);
  const owner = JSON.stringify([agentId, sessionId]);
  const currentOwner = useRef(owner);
  currentOwner.current = owner;
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const flight = useRef(false);
  const [pendingOwner, setPendingOwner] = useState("");
  const [failure, setFailure] = useState<{ owner: string; message: string } | null>(null);
  const query = useQuery({ queryKey: key, queryFn: async () => {
    const incoming = await getLauncherAssistantBudget();
    const current = client.getQueryData<SessionBudgetParameters>(key);
    return current && current.revision >= incoming.revision ? current : incoming;
  },
    enabled: Boolean(sessionId && agentId), retry: false, staleTime: 0 });

  async function save(parameters: ChatComposerBudgetParametersPatch) {
    if (flight.current || !sessionId || !agentId) return;
    flight.current = true;
    setPendingOwner(owner);
    setFailure(null);
    try {
      // Cancel stale reads before applying the authoritative receipt.
      await client.cancelQueries({ queryKey: key, exact: true });
      const receipt = await setLauncherAssistantBudget(parameters);
      if (!mounted.current || currentOwner.current !== owner) return;
      client.setQueryData<SessionBudgetParameters>(key, current =>
        current && current.revision > receipt.revision ? current : receipt);
    } catch (error) {
      if (!mounted.current || currentOwner.current !== owner) return;
      const conflict = error instanceof Error && error.message.includes("ASSISTANT_BUDGET_CONFLICT");
      setFailure({ owner, message: lang === "zh"
        ? conflict ? "预算已在别处更新，请核对后重新保存。" : "预算保存尚未确认，请刷新核对后重试。"
        : conflict ? "Budget changed elsewhere. Review and save again." : "Budget save is unconfirmed. Refresh and try again." });
      // Read back uncertainty or a conflict; never replay a write.
      void client.invalidateQueries({ queryKey: key, exact: true });
    } finally {
      flight.current = false;
      if (mounted.current) setPendingOwner("");
    }
  }

  return sessionId && agentId ? {
    sessionId, revision: query.data?.revision, maxCallsPerTurn: query.data?.maxCallsPerTurn ?? null,
    loading: query.isPending, error: query.isError, pending: pendingOwner === owner,
    errorMessage: failure?.owner === owner ? failure.message : "", onSave: parameters => { void save(parameters); },
  } : undefined;
}
