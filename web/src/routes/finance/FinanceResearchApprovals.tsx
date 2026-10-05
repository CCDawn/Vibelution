import { useEffect, useRef, useState } from "react";
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { listPendingSessionToolApprovals, resolveSessionToolApprovalDecision } from "../../api/chat";
import { queryKeys } from "../../api/queryKeys";
import type { SessionToolApprovalRequest } from "../../api/types";
import type { FinancialResearchBatchTurnRef } from "../../api/financialJobs";
import { VButton, VStateSurface } from "../../components/vui";
import { ChatToolApprovalDialog } from "../chat/ChatToolApprovalDialog";
import { toolApprovalRiskLabel } from "../chat/toolApprovalLabels";
import { toolApprovalActionPreview, toolApprovalDisplayName } from "../chat/toolApprovalPreview";
import styles from "./FinanceResearchApprovals.styles";

export type FinanceApprovalTurnRef = FinancialResearchBatchTurnRef & { agentId?: string; symbol?: string };
const ROLES = {
  market: ["行情", "Market"], fundamental: ["基本面", "Fundamentals"], news: ["新闻", "News"],
  bull: ["乐观研究", "Bull case"], bear: ["审慎研究", "Bear case"], synthesis: ["主助手", "Assistant"],
} as const;
const FINANCE_TOOLS: Record<string, readonly [string, string]> = {
  financial_market_snapshot_tool: ["查询行情与K线", "Market and candles"],
  news_search_tool: ["检索公开新闻", "Public news search"],
  financial_report_query_tool: ["查询财报证据", "Report evidence query"],
  financial_evidence_search_tool: ["检索财报证据", "Report evidence search"],
};

/** Reads native pending requests; never changes a permission preset or grants lasting access. */
export function FinanceResearchApprovals({ assistantAgentId, turns, zh }: {
  assistantAgentId: string; turns: FinanceApprovalTurnRef[]; zh: boolean;
}) {
  const queryClient = useQueryClient();
  const scope = JSON.stringify([assistantAgentId, turns.map((ref) => [ref.sessionId, ref.turnId, ref.agentId])]);
  const currentScope = useRef(scope);
  currentScope.current = scope;
  const mounted = useRef(false);
  const decisionGate = useRef(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { setPending(false); setError(""); }, [scope]);
  const sessions = [...new Set(turns.filter((ref) => ref.sessionId && ref.turnId).map((ref) => ref.sessionId))];
  const queries = useQueries({ queries: sessions.map((sessionId) => ({
    queryKey: queryKeys.sessionToolApprovals(sessionId),
    queryFn: () => listPendingSessionToolApprovals(sessionId),
    staleTime: 0, retry: false, refetchInterval: 1800,
  })) });
  const requests = queries.flatMap((query, index) => (query.data ?? []).flatMap((request) => {
    const ref = turns.find((turn) => turn.sessionId === sessions[index] && turn.sessionId === request.sessionId
      && turn.turnId === request.turnId && (!turn.agentId || turn.agentId === request.agentId));
    return request.status === "pending" && ref ? [{ request, ref }] : [];
  })).sort((a, b) => a.request.createdAt.localeCompare(b.request.createdAt));
  const first = requests[0];
  const readFailed = queries.some((query) => query.isError);

  async function decide(request: SessionToolApprovalRequest, decision: "accept" | "decline") {
    if (decisionGate.current || !request.availableDecisions.includes(decision)
      || !requests.some((entry) => entry.request.requestId === request.requestId)) return;
    const decisionScope = scope;
    decisionGate.current = true;
    setPending(true); setError("");
    try {
      await resolveSessionToolApprovalDecision(request, decision);
    } catch (cause) {
      if (mounted.current && currentScope.current === decisionScope) {
        setError(cause instanceof Error ? cause.message : (zh ? "授权请求未完成" : "Approval request failed"));
      }
    } finally {
      await queryClient.invalidateQueries({ queryKey: queryKeys.sessionToolApprovals(request.sessionId) });
      decisionGate.current = false;
      if (mounted.current && currentScope.current === decisionScope) setPending(false);
    }
  }

  if (!first && !error && !readFailed) return null;
  const lang = zh ? "zh" : "en";
  return <div data-finance-research-approvals>
    {first ? <>
      <p className={styles.status} role="status">{first.ref.symbol ? `${first.ref.symbol} · ` : ""}{ROLES[first.ref.role][zh ? 0 : 1]}{zh ? `等待授权 · ${requests.length} 项` : ` awaiting approval · ${requests.length}`}</p>
      <ChatToolApprovalDialog lang={lang} variant="inline" pending={pending || !first.request.availableDecisions.includes("accept") || !first.request.availableDecisions.includes("decline")}
        rawTitle={first.request.toolName} riskLabel={toolApprovalRiskLabel(first.request.risk, lang)}
        scopeLabel={zh ? "仅本次调用" : "This call only"}
        toolLabels={[{ id: first.request.toolName, label: FINANCE_TOOLS[first.request.toolName]?.[zh ? 0 : 1] || toolApprovalDisplayName(first.request.toolName, lang) }]}
        toolName={first.request.toolName} actionPreview={toolApprovalActionPreview(first.request.argumentSummary, first.request.toolName)}
        onApprove={() => void decide(first.request, "accept")} onReject={() => void decide(first.request, "decline")} />
    </> : null}
    {error || readFailed ? <VStateSurface tone="error" title={error || (zh ? "待授权查询暂不可用" : "Pending approvals unavailable")}
      actions={<VButton onPress={() => { setError(""); queries.forEach((query) => { void query.refetch(); }); }}>{zh ? "重试" : "Retry"}</VButton>} /> : null}
  </div>;
}
