import { useEffect, useRef, useState } from "react";
import { useQueryClient, type InfiniteData } from "@tanstack/react-query";
import { deleteChatSession, fetchSessionDetail, isSessionNotFoundError, querySessions } from "../../api/chat";
import { archiveChatSession, unarchiveChatSession } from "../../api/sessionArchive";
import { queryKeys } from "../../api/queryKeys";
import { createFinancialAssistant, listFinancialAssistants, type FinancialAssistant } from "../../api/financialAssistant";
import type { SessionQueryResponse, SessionSummary } from "../../api/types";
import type { FinancialReportPage } from "../../api/types/financialReports";
import { VConfirmDialog } from "../../components/vui";
import { createChatWorkspaceCache } from "../chatWorkspaceCache";
import { useChatRouteSelection } from "../chat/useChatRouteSelection";
import { isFinancialSession } from "./financialResearchModel";
import type { FinanceSessionAction } from "./FinanceSessionMenu";
import { researchRecordStatus } from "./stockResearchModel";

export type FinanceSessionLifecycle = ReturnType<typeof useFinanceSessionLifecycle>;

type LifecycleResult = { changed: boolean; archiveChanged?: boolean; error?: string; skippedRunning?: boolean };
type DeleteConfirmation = { records: SessionSummary[]; skippedRunning: number; isBatch: boolean; initialErrors: string[] };
type LifecycleOperation = { agentId: string; generation: number };

class RunningResearchError extends Error {}

function errorMessage(cause: unknown, fallback: string) {
  return cause instanceof Error ? cause.message : fallback;
}

function researchLabel(record: SessionSummary) {
  return record.title || record.id;
}

function isRunningResearch(record: SessionSummary) {
  return ["Running", "Stopping"].includes(researchRecordStatus(record, false));
}

export function useFinanceSessionLifecycle(agentId: string, zh: boolean) {
  const client = useQueryClient();
  const route = useChatRouteSelection();
  const routeRef = useRef(route); routeRef.current = route;
  const gate = useRef(false);
  const owner = useRef(agentId), generation = useRef(0);
  if (owner.current !== agentId) generation.current += 1;
  owner.current = agentId;
  const verifiedDeletes = useRef(new Set<string>());
  const mounted = useRef(false);
  const returnFocusTarget = useRef<HTMLElement | null>(null);
  const undoableArchives = useRef<SessionSummary[]>([]);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [canUndoBatchArchive, setCanUndoBatchArchive] = useState(false);
  const [deleting, setDeleting] = useState<DeleteConfirmation | null>(null);
  useEffect(() => {
    gate.current = false;
    verifiedDeletes.current.clear();
    undoableArchives.current = [];
    returnFocusTarget.current = null;
    setPending(false); setError(""); setNotice(""); setDeleting(null); setCanUndoBatchArchive(false);
  }, [agentId]);

  function operation(): LifecycleOperation { return { agentId, generation: generation.current }; }
  function isCurrent(request: LifecycleOperation) {
    return mounted.current && owner.current === request.agentId && generation.current === request.generation;
  }

  async function performRecord(record: SessionSummary, action: FinanceSessionAction, expected: typeof route.selection, request: LifecycleOperation): Promise<LifecycleResult> {
    if (!isCurrent(request)) return { changed: false };
    const deletionKey = `${agentId}:${record.id}`;
    let changed = false;
    let archiveChanged: boolean | undefined;
    let skippedRunning = false;
    let failure: string | undefined;
    try {
      try {
        const detail = await fetchSessionDetail(record.id, { transcriptScope: "none", includeSecondary: false });
        if (detail.id !== record.id || detail.agentId !== agentId) throw new Error(zh ? "这条研究不属于当前助手" : "Research identity mismatch");
        if (action !== "restore" && isRunningResearch(detail)) throw new RunningResearchError();
      } catch (cause) {
        // An unknown DELETE response can leave the old list row visible. Only
        // a previously verified deletion may reconcile native NotFound here.
        if (action !== "delete" || !verifiedDeletes.current.has(deletionKey) || !isSessionNotFoundError(cause)) throw cause;
      }
      if (!isCurrent(request)) return { changed: false };
      if (action === "delete") {
        verifiedDeletes.current.add(deletionKey);
        const result = await deleteChatSession(record.id);
        if (!result.deleted || result.deletedSessionId !== record.id) throw new Error(zh ? "删除尚未完成" : "Delete was not accepted");
        verifiedDeletes.current.delete(deletionKey);
      } else if (action === "archive") {
        const result = await archiveChatSession(record.id);
        archiveChanged = result.changed;
        if (result.sessionId !== record.id) throw new Error(zh ? "会话操作返回了其他研究" : "Session operation identity mismatch");
      } else {
        const result = await unarchiveChatSession(record.id);
        if (result.sessionId !== record.id) throw new Error(zh ? "会话操作返回了其他研究" : "Session operation identity mismatch");
      }
      changed = true;
      if (isCurrent(request)) setDeleting(null);
      await Promise.all([
        client.cancelQueries({ queryKey: ["sessions", "finance", agentId] }),
        client.cancelQueries({ queryKey: ["finance", "report-catalog", agentId] }),
        ...(action === "delete" ? [client.cancelQueries({ queryKey: ["finance", "exact-report", agentId, record.id] })] : []),
      ]);
      if (action === "restore") void client.invalidateQueries({ queryKey: ["sessions", "finance", agentId] });
      else client.setQueriesData<InfiniteData<SessionQueryResponse>>({ queryKey: ["sessions", "finance", agentId] }, (data) => data ? ({ ...data, pages: data.pages.map((page) => ({ ...page, items: page.items.filter((row) => row.id !== record.id) })) }) : data);
      if (action !== "restore") client.setQueriesData<InfiniteData<FinancialReportPage>>({ queryKey: ["finance", "report-catalog", agentId] }, (data) => data ? ({ ...data, pages: data.pages.map((page) => ({ ...page, items: page.items.filter((row) => row.sessionId !== record.id) })) }) : data);
      if (action === "delete") client.removeQueries({ queryKey: ["finance", "exact-report", agentId, record.id] });
      client.removeQueries({ queryKey: ["finance", "session-binding", agentId, record.id], exact: true });
      const cache = createChatWorkspaceCache(client);
      if (action === "delete") void cache.afterSessionDeleted({ deletedSessionId: record.id });
      else void cache.afterSessionChanged({ sessionId: record.id, agentId });
      client.setQueryData<FinancialAssistant[]>(queryKeys.financialAssistants(), (rows) => rows?.map((row) => row.agentId === agentId && row.directSessionId === record.id && action !== "delete" ? { ...row, directSessionArchived: action === "archive" } : row));
      if (action === "delete") {
        const assistants = await listFinancialAssistants();
        client.setQueryData(queryKeys.financialAssistants(), assistants);
        const owner = assistants.find((row) => row.agentId === agentId);
        if (isCurrent(request) && owner?.status === "active" && owner.setupStatus === "session_missing") {
          const repaired = (await createFinancialAssistant()).assistant;
          if (repaired.agentId !== agentId || !repaired.directSessionId || repaired.setupStatus !== "ready") throw new Error(zh ? "研究已删除，助手会话恢复失败" : "Research deleted; assistant session recovery failed");
          client.setQueryData(queryKeys.financialAssistants(), assistants.map((row) => row.agentId === agentId ? repaired : row));
        }
      }
      void client.invalidateQueries({ queryKey: ["sessions", "finance-archived", agentId] });
      void client.invalidateQueries({ queryKey: queryKeys.sessionArchive() });
      if (isCurrent(request) && action !== "restore" && expected.kind === "session" && expected.sessionId === record.id && routeRef.current.matchesSelection(expected)) {
        // The native deletion response may point to another Agent. Pick only a
        // verified surviving research owned by this financial assistant.
        const page = await querySessions({ agentId, limit: 30 });
        const next = page.items.find((row) => row.id !== record.id && isFinancialSession(row, agentId));
        if (next) {
          const replacement = await fetchSessionDetail(next.id, { transcriptScope: "none", includeSecondary: false });
          if (replacement.id !== next.id || !isFinancialSession(replacement, agentId)) throw new Error(zh ? "下一条研究尚未准备好" : "Next research is unavailable");
          client.setQueryData(["finance", "session-binding", agentId, next.id], replacement);
          if (isCurrent(request)) routeRef.current.replaceIfStillViewing(expected, { kind: "session", sessionId: next.id });
        } else if (isCurrent(request)) routeRef.current.replaceIfStillViewing(expected, { kind: "bare" });
      }
    } catch (cause) {
      if (cause instanceof RunningResearchError) skippedRunning = true;
      else {
        const message = errorMessage(cause, zh ? "会话操作失败，请重试" : "Session operation failed");
        failure = changed ? (zh ? `研究记录已更新；页面刷新失败：${message}` : `Research updated; refresh failed: ${message}`) : message;
        if (isCurrent(request) && changed && expected.kind === "session" && expected.sessionId === record.id) routeRef.current.replaceIfStillViewing(expected, { kind: "bare" });
      }
    } finally {
      if (changed) {
        void client.invalidateQueries({ queryKey: queryKeys.financialAssistants() });
        void client.invalidateQueries({ queryKey: ["finance", "report-catalog", agentId] });
      }
    }
    return { changed, ...(archiveChanged !== undefined ? { archiveChanged } : {}), ...(failure ? { error: failure } : {}), ...(skippedRunning ? { skippedRunning: true } : {}) };
  }

  async function apply(record: SessionSummary, action: FinanceSessionAction) {
    if (gate.current) return;
    const request = operation();
    gate.current = true; setPending(true); setError(""); setNotice("");
    try {
      const result = await performRecord(record, action, routeRef.current.selection, request);
      if (result.error && isCurrent(request)) setError(result.error);
      if (result.skippedRunning && isCurrent(request)) {
        setDeleting(null);
        setNotice(zh ? "研究正在运行或停止，已跳过操作。" : "Research is running or stopping; action skipped.");
      }
    } finally {
      if (isCurrent(request)) { gate.current = false; setPending(false); }
    }
  }

  async function applyBatch(records: SessionSummary[], action: FinanceSessionAction, skippedRunning: number, initialErrors: string[] = []) {
    if (gate.current) return;
    const request = operation();
    gate.current = true; setPending(true); setError(""); setNotice("");
    if (action === "archive") {
      undoableArchives.current = [];
      setCanUndoBatchArchive(false);
    }
    const successes: SessionSummary[] = [];
    const undoable: SessionSummary[] = [];
    const failures = [...initialErrors];
    let skippedCount = skippedRunning;
    try {
      for (const record of records) {
        if (!isCurrent(request)) break;
        const result = await performRecord(record, action, routeRef.current.selection, request);
        if (result.skippedRunning) { skippedCount += 1; continue; }
        if (result.changed) {
          successes.push(record);
          if (action === "archive" && result.archiveChanged) undoable.push(record);
        }
        if (result.error) failures.push(`${researchLabel(record)}：${result.error}`);
      }
      if (action === "archive" && isCurrent(request)) {
        undoableArchives.current = undoable;
        setCanUndoBatchArchive(undoable.length > 0);
      }
      const actionLabel = action === "delete" ? (zh ? "删除" : "Deleted") : action === "archive" ? (zh ? "归档" : "Archived") : (zh ? "恢复" : "Restored");
      const runningLabel = skippedCount ? (zh ? `，跳过 ${skippedCount} 条运行中的研究` : `, skipped ${skippedCount} running research sessions`) : "";
      const failureLabel = failures.length ? (zh ? `，${failures.length} 条未完成` : `, ${failures.length} failed`) : "";
      if (isCurrent(request)) {
        setNotice(zh ? `已${actionLabel} ${successes.length} 条研究${failureLabel}${runningLabel}。` : `${actionLabel} ${successes.length} research sessions${failureLabel}${runningLabel}.`);
        setError(failures.join("\n"));
      }
    } finally {
      if (isCurrent(request)) { gate.current = false; setPending(false); }
    }
  }

  function requestAction(record: SessionSummary, action: FinanceSessionAction) {
    if (gate.current || record.agentId !== agentId) return;
    setError(""); setNotice("");
    if (action === "delete") {
      returnFocusTarget.current = typeof document !== "undefined" && document.activeElement instanceof HTMLElement ? document.activeElement : null;
      setDeleting({ records: [record], skippedRunning: 0, isBatch: false, initialErrors: [] });
    } else void apply(record, action);
  }

  function requestBatchAction(records: SessionSummary[], action: FinanceSessionAction, returnFocus?: HTMLElement | null) {
    if (gate.current) return;
    setError(""); setNotice("");
    const unique = [...new Map(records.filter((record) => record?.id).map((record) => [record.id, record])).values()];
    const running = action === "restore" ? [] : unique.filter(isRunningResearch);
    const runningIds = new Set(running.map((record) => record.id));
    const wrongOwner = unique.filter((record) => !runningIds.has(record.id) && record.agentId !== agentId);
    const candidates = unique.filter((record) => !runningIds.has(record.id) && record.agentId === agentId);
    const initialErrors = wrongOwner.map((record) => `${researchLabel(record)}：${zh ? "这条研究不属于当前助手" : "Research identity mismatch"}`);
    if (!candidates.length) {
      const skipped = running.length ? (zh ? `跳过 ${running.length} 条运行中的研究；` : `Skipped ${running.length} running research sessions; `) : "";
      setNotice(`${skipped}${zh ? "没有可处理的研究。" : "No research sessions can be changed."}`);
      setError(initialErrors.join("\n"));
      return;
    }
    if (action === "delete") {
      returnFocusTarget.current = returnFocus ?? (typeof document !== "undefined" && document.activeElement instanceof HTMLElement ? document.activeElement : null);
      setDeleting({ records: candidates, skippedRunning: running.length, isBatch: true, initialErrors });
      return;
    }
    void applyBatch(candidates, action, running.length, initialErrors);
  }

  async function confirmDelete() {
    const request = deleting;
    if (!request || gate.current) return;
    const currentOperation = operation();
    if (request.isBatch) {
      setDeleting(null);
      await applyBatch(request.records, "delete", request.skippedRunning, request.initialErrors);
      return;
    }
    gate.current = true; setPending(true); setError(""); setNotice("");
    try {
      const record = request.records[0];
      if (!record) return;
      const result = await performRecord(record, "delete", routeRef.current.selection, currentOperation);
      if (result.error && isCurrent(currentOperation)) setError(result.error);
      if (result.skippedRunning && isCurrent(currentOperation)) {
        setDeleting(null);
        setNotice(zh ? "研究正在运行或停止，已跳过删除。" : "Research is running or stopping; deletion skipped.");
      }
    } finally {
      if (isCurrent(currentOperation)) { gate.current = false; setPending(false); }
    }
  }

  async function undoBatchArchive() {
    if (gate.current || !undoableArchives.current.length) return;
    const request = operation();
    gate.current = true; setPending(true); setError(""); setNotice("");
    const remaining: SessionSummary[] = [];
    const failures: string[] = [];
    let restored = 0;
    try {
      for (const record of undoableArchives.current) {
        if (!isCurrent(request)) break;
        const result = await performRecord(record, "restore", routeRef.current.selection, request);
        if (result.changed) restored += 1;
        else {
          remaining.push(record);
          failures.push(`${researchLabel(record)}：${result.error || (zh ? "恢复失败，请重试" : "Restore failed; try again")}`);
        }
        if (result.changed && result.error) failures.push(`${researchLabel(record)}：${result.error}`);
      }
      if (isCurrent(request)) {
        undoableArchives.current = remaining;
        setCanUndoBatchArchive(remaining.length > 0);
        setNotice(zh ? `已撤销归档，恢复 ${restored} 条研究${remaining.length ? `，仍有 ${remaining.length} 条可重试` : ""}。` : `Undid archive for ${restored} research sessions${remaining.length ? `; ${remaining.length} can be retried` : ""}.`);
        setError(failures.join("\n"));
      }
    } finally {
      if (isCurrent(request)) { gate.current = false; setPending(false); }
    }
  }

  const batchCount = deleting?.records.length ?? 0;
  const confirmDescription = deleting?.isBatch
    ? (zh ? `将删除 ${batchCount} 条研究的会话记录，删除后无法恢复。${deleting.skippedRunning ? `运行中的研究将跳过（${deleting.skippedRunning} 条）。` : ""}需要保留时可改用归档。` : `The conversation records for ${batchCount} research sessions will be deleted and cannot be restored. ${deleting.skippedRunning ? `${deleting.skippedRunning} running sessions will be skipped. ` : ""}Archive them to keep the records.`)
    : (zh ? `「${deleting?.records[0]?.title || "研究会话"}」的会话记录将被删除。需要保留时可改用归档。` : `The conversation for “${deleting?.records[0]?.title || "Research"}” will be deleted. Archive it to keep the record.`);

  return {
    requestAction,
    requestBatchAction,
    undoBatchArchive,
    canUndoBatchArchive,
    pending,
    error,
    notice,
    dialog: <VConfirmDialog
      open={Boolean(deleting)}
      title={deleting?.isBatch ? (zh ? "删除所选研究？" : "Delete selected research?") : (zh ? "删除这条研究？" : "Delete this research?")}
      description={confirmDescription}
      tone="danger"
      confirmLabel={zh ? "删除研究" : "Delete"}
      cancelLabel={zh ? "取消" : "Cancel"}
      confirmPending={pending}
      onOpenChange={(open) => { if (!open && !gate.current) setDeleting(null); }}
      onCancel={() => { if (!gate.current) setDeleting(null); }}
      onCloseAutoFocus={(event) => {
        const target = returnFocusTarget.current;
        if (target?.isConnected) { event.preventDefault(); target.focus({ preventScroll: true }); }
        returnFocusTarget.current = null;
      }}
      onConfirm={() => { void confirmDelete(); }}
    />,
  };
}
