import styles from "./FinanceResearchProcess.styles";
import { CheckCircle2, Circle, Loader2, ShieldAlert, XCircle, TriangleAlert } from "lucide-react";
import type { AssistantConversationTurn, ToolCallTurnItem } from "../../api/types";
import { operationStatusTone } from "../../components/conversation/conversationOperationState";
import { VButton, VStateSurface } from "../../components/vui";
import type { FinancialSessionView } from "./FinancialResearchBridge";
import { latestResearchTurn, projectStockReport, researchRecordStatus } from "./stockResearchModel";

const toolLabels: Record<string, string> = {
  financial_evidence_search_tool: "检索财报证据",
  financial_report_query_tool: "读取财报数据",
  financial_market_snapshot_tool: "查询行情与K线",
  news_search_tool: "检索新闻线索",
  agent_delegate_tool: "委派资料查询",
  knowledge_search_tool: "检索资料库",
};

function toolState(item: ToolCallTurnItem, zh: boolean) {
  const status = item.status === "completed" ? item.semanticStatus || item.status : item.status;
  const tone = operationStatusTone({ id: item.itemId, kind: "tool", label: item.toolName, status, summary: "", durationSeconds: null });
  const warnings: Record<string, [string, string]> = {
    degraded: ["降级完成", "Completed with limitations"], partial: ["部分结果", "Partial results"],
    fallback: ["使用备用来源", "Fallback source"], recovered: ["重试后恢复", "Recovered after retry"],
    unavailable: ["数据不可用", "Data unavailable"],
  };
  const label = tone === "degraded" ? warnings[status.toLowerCase()]?.[zh ? 0 : 1] || (zh ? "结果需核对" : "Review result")
    : tone === "done" ? (zh ? "已完成" : "Completed") : tone === "failed" ? (zh ? "失败" : "Failed")
    : item.status === "running" ? (zh ? "执行中" : "Running") : (zh ? "等待执行" : "Pending");
  return { tone, label };
}

export function FinanceResearchProcess({ view, activeTurn, zh, onOpenChat, onEnableMarket, marketPending, marketDisabled }: {
  view: FinancialSessionView | null;
  activeTurn: AssistantConversationTurn | null;
  zh: boolean;
  onOpenChat: () => void;
  onEnableMarket?: () => void;
  marketPending?: boolean;
  marketDisabled?: boolean;
}) {
  const turn = activeTurn ?? latestResearchTurn(view?.messages ?? []);
  const tools = turn?.turnItems.filter((item) => item.type === "tool_call") ?? [];
  const error = view?.error || turn?.turnItems.find((item) => item.type === "error")?.text;
  const report = projectStockReport(view?.messages ?? [], view);
  const running = Boolean(view?.busy || view?.submitPending);
  const approvalPending = Boolean(view?.approvalPending);
  const outcome = view ? researchRecordStatus(view, false) : "";
  const stopped = outcome === "Stopped";
  const needsContinue = outcome === "Needs continuation";
  const failed = !stopped && !needsContinue && Boolean(error || outcome === "Failed" || turn?.status === "failed");
  const completed = !stopped && !needsContinue && !failed && Boolean(report || outcome === "Completed");
  const degraded = tools.some((item) => toolState(item, zh).tone === "degraded");
  const status = view?.stopping ? (zh ? "正在停止" : "Stopping")
    : approvalPending ? (zh ? "等待授权" : "Awaiting approval")
    : running ? (zh ? "研究中" : "Research running")
    : failed ? (zh ? "研究未完成" : "Research incomplete")
    : stopped ? (zh ? "已停止" : "Stopped")
    : needsContinue ? (zh ? "待继续" : "Needs continuation")
    : completed ? (degraded ? (zh ? "已完成 · 结果需核对" : "Completed · Review results") : (zh ? "已完成" : "Completed"))
    : (zh ? "待开始" : "Ready");
  const errorPreview = !stopped && error && (error.length > 110 ? `${error.slice(0, 110)}…` : error);

  return (
    <div className={styles.panel} data-finance-research-process>
      <div>
        <span className={styles.caption}>{zh ? "当前研究" : "Current research"}</span>
        <p className={styles.title}>
          {view?.title || (zh ? "等待发起研究" : "Ready to research")}
        </p>
      </div>
      <div className={styles.status} role="status">
        {approvalPending ? <ShieldAlert size={16} className={styles.warning} />
          : running ? <Loader2 size={16} className={styles.running} />
          : failed ? <XCircle size={16} className={styles.error} />
          : completed ? (degraded ? <TriangleAlert size={16} className={styles.warning} /> : <CheckCircle2 size={16} className={styles.success} />)
          : <Circle size={16} className={styles.muted} />}
        <strong>{status}</strong>
      </div>
      {tools.length ? (
        <ol className={styles.tools}>
          {tools.map((item) => {
            const state = toolState(item, zh);
            return (
            <li key={item.itemId} className={styles.tool}>
              {item.status === "running" ? <Loader2 size={14} className={styles.runningTool} />
                : item.status === "pending" ? <Circle size={14} className={styles.pendingTool} />
                : state.tone === "failed" ? <XCircle size={14} className={styles.failedTool} />
                : state.tone === "degraded" ? <TriangleAlert size={14} className={styles.warningTool} />
                : state.tone === "done" ? <CheckCircle2 size={14} className={styles.completedTool} />
                : <Circle size={14} className={styles.pendingTool} />}
              <div className={styles.toolText}>
                <strong className={styles.toolTitle}>{zh ? toolLabels[item.toolName] || item.title || item.toolName : item.title || item.toolName}</strong>
                <p className={state.tone === "degraded" ? styles.warningStatus : styles.toolStatus}>
                  {state.label}
                </p>
              </div>
            </li>
          ); })}
        </ol>
      ) : <p className={styles.empty}>{running ? (zh ? "正在分析…" : "Analyzing…") : turn ? (zh ? "本轮未调用外部工具" : "No external tools used this turn") : (zh ? "尚未开始研究" : "No research started")}</p>}
      {errorPreview ? (
        <VStateSurface tone="error" title={zh ? "需要处理" : "Needs attention"}>
          <span className={styles.errorText}>{errorPreview}</span>
        </VStateSurface>
      ) : null}
      {onEnableMarket ? <VButton variant="secondary" onPress={onEnableMarket} isPending={marketPending} isDisabled={marketDisabled || marketPending}>
        {zh ? "启用行情查询" : "Enable market queries"}
      </VButton> : null}
      <VButton variant="secondary" onPress={onOpenChat}>
        {approvalPending ? (zh ? "查看并授权" : "Review and approve")
          : running ? (zh ? "查看研究 / 停止" : "View / stop research")
          : error ? (zh ? "查看与重试" : "View and retry")
          : (zh ? "打开研究对话" : "Open research chat")}
      </VButton>
    </div>
  );
}
