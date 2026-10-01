import styles from "./FinanceRoute.styles";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { listFinancialAssistants, createFinancialAssistant } from "../api/financialAssistant";
import { queryKeys } from "../api/queryKeys";
import { VButton, VDenseOpsPage, VRouteLinkButton, VStateSurface } from "../components/vui";
import { useShellI18n } from "../i18n/useShellI18n";
import { agentCenterConfigRoute, agentCenterMemoryRoute } from "./agentCenterRoutes";
import { useChatRouteSelection } from "./chat/useChatRouteSelection";

export function FinanceRoute() {
  const { lang } = useShellI18n();
  const zh = lang === "zh";
  const cache = useQueryClient();
  const { openSession } = useChatRouteSelection();
  const assistants = useQuery({ queryKey: queryKeys.financialAssistants(),
    queryFn: ({ signal }) => listFinancialAssistants({ signal }), staleTime: 0 });
  const create = useMutation({ mutationFn: createFinancialAssistant,
    onSuccess: async () => {
      // Creation updates caches only: a late response must not navigate away from a newer page.
      await Promise.all([queryKeys.financialAssistants(), queryKeys.agents(), queryKeys.sessions()]
        .map((queryKey) => cache.invalidateQueries({ queryKey })));
    } });
  const rows = assistants.data ?? [];
  const setupButton = <VButton type="button" isPending={create.isPending} onPress={() => create.mutate()}>
    {zh ? "创建 / 继续配置金融助手" : "Create / resume assistant setup"}
  </VButton>;
  return <VDenseOpsPage ariaLabel={zh ? "炒股智能体" : "Investment assistant"}
    title={zh ? "炒股智能体" : "Investment assistant"}
    meta={zh ? "A 股 · 财报证据 · 只读风险研究" : "A-shares · Report evidence · Read-only risk research"}
    bodyClassName={styles.body}>
    <div className={styles.sections} data-vui-domain-recipe="financial-assistant-entry">
      <VStateSurface title={zh ? "当前能力" : "Current capabilities"} tone="info">
        {zh ? "原生会话、身份配置与独立财报知识库已适配。财报服务需单独配置并验证；分钟行情和 K 线尚未接入，新闻跨团队委派默认关闭。" : "Native chat, identity settings and a separate report library are integrated. The report service requires configuration and verification. Minute quotes/charts are not connected; cross-team news delegation is disabled."}
      </VStateSurface>
      {assistants.isPending ? <VStateSurface title={zh ? "正在载入" : "Loading"} tone="loading" busy />
        : assistants.isError ? <VStateSurface title={zh ? "载入失败" : "Could not load"} tone="error"
            actions={<VButton onPress={() => assistants.refetch()}>{zh ? "重试" : "Retry"}</VButton>} />
        : rows.length === 0 ? <VStateSurface title={zh ? "还没有金融助手" : "No financial assistant yet"} tone="empty" actions={setupButton}>
            {zh ? "创建独立身份、原生会话和空的财报库。默认只授予两项财报只读工具；不会连接券商或创建交易权限。" : "Create a separate identity, native session and empty report library with two read-only evidence tools. No brokerage connection or trading access is created."}
          </VStateSurface>
        : rows.map((item) => <VStateSurface key={item.agentId} title={`${item.displayName} · ${item.agentCode}`}
            actions={<div className={styles.actions}>
              <VButton isDisabled={!item.directSessionId || item.status !== "active"}
                onPress={() => openSession(item.directSessionId, { replace: false, telemetrySource: "financial_assistant_entry" })}>
                {zh ? "进入对话" : "Open chat"}
              </VButton>
              <VRouteLinkButton to={agentCenterConfigRoute({ agentId: item.agentId, returnTo: "/finance", returnLabel: zh ? "炒股智能体" : "Investment assistant" })}>
                {zh ? "身份与模型配置" : "Identity and model settings"}
              </VRouteLinkButton>
              {item.knowledgeBaseId ? <VRouteLinkButton to={agentCenterMemoryRoute({ agentId: item.agentId, knowledgeBaseId: item.knowledgeBaseId, returnTo: "/finance" })}>
                {zh ? "财报知识库" : "Report library"}
              </VRouteLinkButton> : null}
              {item.status === "active" && item.setupStatus === "pending" ? setupButton : null}
            </div>}>
            <p>{zh ? "状态" : "Status"}: {item.status} · {item.setupStatus}</p>
            <p>{zh ? "模型配置（尚未验证连接）" : "Model configuration (connection unverified)"}: {item.modelStatus}</p>
            <p>{zh ? "外部财报服务（尚未验证连接）" : "External report service (connection unverified)"}: {item.reportStatus}</p>
            <p>{zh ? "本地财报库读取权限" : "Local report read access"}: {item.knowledgeReadable ? (zh ? "已绑定" : "Bound") : (zh ? "待配置" : "Needs configuration")}</p>
          </VStateSurface>)}
      {create.isError ? <VStateSurface title={zh ? "配置未完成" : "Setup incomplete"} tone="error">
        {create.error instanceof Error ? create.error.message : (zh ? "请重试或检查 Agent 配置" : "Retry or inspect Agent settings")}
      </VStateSurface> : null}
      <VStateSurface title={zh ? "个人财务边界" : "Private financial data"}>
        {zh ? "尚未接入账户、持仓和现金流账本。金额、投资目标、投入意愿及风险承受能力未知时保持空缺；此页不采集这些信息，公共新闻和财报库不用于保存个人财务数据。建议仅供研究，不自动执行交易。" : "Accounts, holdings and a cash-flow ledger are not connected. Unknown amounts, goals, contribution preferences and risk tolerance stay unknown. This page collects no financial data; public news/report stores must not hold it. Research does not execute trades."}
      </VStateSurface>
    </div>
  </VDenseOpsPage>;
}
