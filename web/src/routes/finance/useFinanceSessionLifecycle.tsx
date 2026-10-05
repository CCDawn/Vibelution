import { useEffect, useRef, useState } from "react";
import { useQueryClient, type InfiniteData } from "@tanstack/react-query";
import { deleteChatSession, fetchSessionDetail, isSessionNotFoundError, querySessions } from "../../api/chat";
import { archiveChatSession, unarchiveChatSession } from "../../api/sessionArchive";
import { queryKeys } from "../../api/queryKeys";
import { createFinancialAssistant, listFinancialAssistants, type FinancialAssistant } from "../../api/financialAssistant";
import type { SessionQueryResponse, SessionSummary } from "../../api/types";
import { VConfirmDialog } from "../../components/vui";
import { createChatWorkspaceCache } from "../chatWorkspaceCache";
import { useChatRouteSelection } from "../chat/useChatRouteSelection";
import { isFinancialSession } from "./financialResearchModel";
import type { FinanceSessionAction } from "./FinanceSessionMenu";

export function useFinanceSessionLifecycle(agentId: string, zh: boolean) {
  const client = useQueryClient();
  const route = useChatRouteSelection();
  const routeRef = useRef(route); routeRef.current = route;
  const gate = useRef(false);
  const verifiedDeletes = useRef(new Set<string>());
  const mounted = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState<SessionSummary | null>(null);

  async function apply(record: SessionSummary, action: FinanceSessionAction) {
    if (gate.current) return;
    gate.current = true; setPending(true); setError("");
    const expected = routeRef.current.selection;
    let changed = false;
    try {
      const deletionKey = `${agentId}:${record.id}`;
      try {
        const detail = await fetchSessionDetail(record.id, { transcriptScope: "none", includeSecondary: false });
        if (detail.id !== record.id || detail.agentId !== agentId) throw new Error(zh ? "这条研究不属于当前助手" : "Research identity mismatch");
      } catch (cause) {
        // An unknown DELETE response can leave the old list row visible. Only
        // a previously verified deletion may reconcile native NotFound here.
        if (action !== "delete" || !verifiedDeletes.current.has(deletionKey) || !isSessionNotFoundError(cause)) throw cause;
      }
      if (action === "delete") {
        verifiedDeletes.current.add(deletionKey);
        const result = await deleteChatSession(record.id);
        if (!result.deleted || result.deletedSessionId !== record.id) throw new Error(zh ? "删除尚未完成" : "Delete was not accepted");
        verifiedDeletes.current.delete(deletionKey);
      } else {
        const result = await (action === "archive" ? archiveChatSession(record.id) : unarchiveChatSession(record.id));
        if (result.sessionId !== record.id) throw new Error(zh ? "会话操作返回了其他研究" : "Session operation identity mismatch");
      }
      changed = true; setDeleting(null);
      await client.cancelQueries({ queryKey: ["sessions", "finance", agentId] });
      client.setQueriesData<InfiniteData<SessionQueryResponse>>({ queryKey: ["sessions", "finance", agentId] }, (data) => data ? ({ ...data, pages: data.pages.map((page) => ({ ...page, items: page.items.filter((row) => row.id !== record.id) })) }) : data);
      client.removeQueries({ queryKey: ["finance", "session-binding", agentId, record.id], exact: true });
      const cache = createChatWorkspaceCache(client);
      if (action === "delete") void cache.afterSessionDeleted({ deletedSessionId: record.id });
      else void cache.afterSessionChanged({ sessionId: record.id, agentId });
      client.setQueryData<FinancialAssistant[]>(queryKeys.financialAssistants(), (rows) => rows?.map((row) => row.agentId === agentId && row.directSessionId === record.id && action !== "delete" ? { ...row, directSessionArchived: action === "archive" } : row));
      if (action === "delete") {
        const assistants = await listFinancialAssistants();
        client.setQueryData(queryKeys.financialAssistants(), assistants);
        const owner = assistants.find((row) => row.agentId === agentId);
        if (owner?.status === "active" && owner.setupStatus === "session_missing") {
          const repaired = (await createFinancialAssistant()).assistant;
          if (repaired.agentId !== agentId || !repaired.directSessionId || repaired.setupStatus !== "ready") throw new Error(zh ? "研究已删除，助手会话恢复失败" : "Research deleted; assistant session recovery failed");
          client.setQueryData(queryKeys.financialAssistants(), assistants.map((row) => row.agentId === agentId ? repaired : row));
        }
      }
      void client.invalidateQueries({ queryKey: ["sessions", "finance-archived", agentId] });
      if (mounted.current && action !== "restore" && expected.kind === "session" && expected.sessionId === record.id && routeRef.current.matchesSelection(expected)) {
        // The native deletion response may point to another Agent. Pick only a
        // verified surviving research owned by this financial assistant.
        const page = await querySessions({ agentId, limit: 30 });
        const next = page.items.find((row) => row.id !== record.id && isFinancialSession(row, agentId));
        if (next) {
          const replacement = await fetchSessionDetail(next.id, { transcriptScope: "none", includeSecondary: false });
          if (replacement.id !== next.id || !isFinancialSession(replacement, agentId)) throw new Error(zh ? "下一条研究尚未准备好" : "Next research is unavailable");
          client.setQueryData(["finance", "session-binding", agentId, next.id], replacement);
          if (mounted.current) routeRef.current.replaceIfStillViewing(expected, { kind: "session", sessionId: next.id });
        } else if (mounted.current) routeRef.current.replaceIfStillViewing(expected, { kind: "bare" });
      }
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : (zh ? "会话操作失败，请重试" : "Session operation failed");
      if (mounted.current) setError(changed ? (zh ? `研究记录已更新；页面刷新失败：${message}` : `Research updated; refresh failed: ${message}`) : message);
      if (mounted.current && changed && expected.kind === "session" && expected.sessionId === record.id) routeRef.current.replaceIfStillViewing(expected, { kind: "bare" });
    } finally {
      if (changed) void client.invalidateQueries({ queryKey: queryKeys.financialAssistants() });
      gate.current = false;
      if (mounted.current) setPending(false);
    }
  }

  function requestAction(record: SessionSummary, action: FinanceSessionAction) {
    if (gate.current || record.agentId !== agentId) return;
    setError("");
    if (action === "delete") setDeleting(record);
    else void apply(record, action);
  }

  return { requestAction, pending, error, dialog: <VConfirmDialog open={Boolean(deleting)} title={zh ? "删除这条研究？" : "Delete this research?"} description={zh ? `「${deleting?.title || "研究会话"}」的会话记录将被删除。需要保留时可改用归档。` : `The conversation for “${deleting?.title || "Research"}” will be deleted. Archive it to keep the record.`} tone="danger" confirmLabel={zh ? "删除研究" : "Delete"} cancelLabel={zh ? "取消" : "Cancel"} confirmPending={pending} onOpenChange={(open) => { if (!open && !gate.current) setDeleting(null); }} onConfirm={() => { if (deleting) void apply(deleting, "delete"); }} /> };
}
