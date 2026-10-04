import { CheckCircle2, Circle, Loader2, ShieldAlert, XCircle } from "lucide-react";
import type { AssistantConversationTurn } from "../../api/types";
import { VButton, VStateSurface } from "../../components/vui";
import type { FinancialSessionView } from "./FinancialResearchBridge";
import { latestResearchTurn, projectStockReport } from "./stockResearchModel";

const toolLabels: Record<string, string> = {
  financial_evidence_search_tool: "检索财报证据",
  financial_report_query_tool: "读取财报数据",
  news_search_tool: "检索新闻线索",
  agent_delegate_tool: "委派资料查询",
  knowledge_search_tool: "检索资料库",
};

export function FinanceResearchProcess({ view, activeTurn, zh, onOpenChat }: {
  view: FinancialSessionView | null;
  activeTurn: AssistantConversationTurn | null;
  zh: boolean;
  onOpenChat: () => void;
}) {
  const turn = activeTurn ?? latestResearchTurn(view?.messages ?? []);
  const tools = turn?.turnItems.filter((item) => item.type === "tool_call") ?? [];
  const error = view?.error || turn?.turnItems.find((item) => item.type === "error")?.text;
  const report = projectStockReport(view?.messages ?? []);
  const running = Boolean(view?.busy || view?.submitPending);
  const approvalPending = Boolean(view?.approvalPending);
  const status = view?.stopping ? (zh ? "正在停止" : "Stopping")
    : approvalPending ? (zh ? "等待授权" : "Awaiting approval")
    : running ? (zh ? "研究中" : "Research running")
    : error ? (zh ? "研究未完成" : "Research incomplete")
    : report ? (zh ? "已完成" : "Completed")
    : view?.status === "stopped" ? (zh ? "已停止" : "Stopped")
    : (zh ? "待开始" : "Ready");
  const errorPreview = error && (error.length > 110 ? `${error.slice(0, 110)}…` : error);

  return (
    <div className="grid gap-5 p-4" data-finance-research-process>
      <div>
        <span className="text-xs text-[var(--fg-tertiary)]">{zh ? "当前研究" : "Current research"}</span>
        <p className="text-sm font-medium mt-2 mb-0 break-words">
          {view?.title || (zh ? "等待发起研究" : "Ready to research")}
        </p>
      </div>
      <div className="flex items-center gap-2 text-sm" role="status">
        {approvalPending ? <ShieldAlert size={16} className="text-[var(--state-warning)]" />
          : running ? <Loader2 size={16} className="animate-spin motion-reduce:animate-none text-[var(--accent-cool)]" />
          : error ? <XCircle size={16} className="text-[var(--state-error)]" />
          : report ? <CheckCircle2 size={16} className="text-[var(--state-success)]" />
          : <Circle size={16} className="text-[var(--fg-tertiary)]" />}
        <strong>{status}</strong>
      </div>
      {tools.length ? (
        <ol className="list-none grid gap-4 p-0 m-0">
          {tools.map((item) => (
            <li key={item.itemId} className="flex items-start gap-2.5 text-xs">
              {item.status === "running" ? <Loader2 size={14} className="shrink-0 animate-spin motion-reduce:animate-none text-[var(--accent-cool)]" />
                : item.status === "pending" ? <Circle size={14} className="shrink-0 text-[var(--fg-tertiary)]" />
                : item.status === "failed" ? <XCircle size={14} className="shrink-0 text-[var(--state-error)]" />
                : <CheckCircle2 size={14} className="shrink-0 text-[var(--state-success)]" />}
              <div className="min-w-0">
                <strong className="font-medium">{zh ? toolLabels[item.toolName] || item.title || item.toolName : item.title || item.toolName}</strong>
                <p className="mt-1 mb-0 text-[var(--fg-tertiary)]">
                  {item.status === "completed" ? (zh ? "已完成" : "Completed")
                    : item.status === "failed" ? (zh ? "失败" : "Failed")
                    : item.status === "pending" ? (zh ? "等待执行" : "Pending")
                    : (zh ? "执行中" : "Running")}
                </p>
              </div>
            </li>
          ))}
        </ol>
      ) : <p className="text-xs leading-6 text-[var(--fg-tertiary)] m-0">{running ? (zh ? "正在分析…" : "Analyzing…") : (zh ? "尚未开始研究" : "No research started")}</p>}
      {errorPreview ? (
        <VStateSurface tone="error" title={zh ? "需要处理" : "Needs attention"}>
          <span className="block break-words">{errorPreview}</span>
        </VStateSurface>
      ) : null}
      <VButton variant="secondary" onPress={onOpenChat}>
        {approvalPending ? (zh ? "查看并授权" : "Review and approve")
          : running ? (zh ? "查看研究 / 停止" : "View / stop research")
          : error ? (zh ? "查看与重试" : "View and retry")
          : (zh ? "打开研究对话" : "Open research chat")}
      </VButton>
    </div>
  );
}
