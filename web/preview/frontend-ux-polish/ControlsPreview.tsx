import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

import type { AgentInstance, SessionLlmModelOption, SessionModelSelection } from "../../src/api/types";
import { queryKeys } from "../../src/api/queryKeys";
import { VPanel, VPanelHeader } from "../../src/components/vui";
import { ConversationInferenceControl } from "../../src/components/conversation/ConversationInferenceControl";
import { ConversationTurnModelControl } from "../../src/components/conversation/ConversationTurnModelControl";
import { dictionary } from "../../src/i18n/dictionary";
import { dictionaryDomainsQueryKey, normalizeDictionaryDomains } from "../../src/i18n/dictionaryDomainIds";
import { ToolsRouteAgentScopePanel } from "../../src/routes/ToolsRouteAgentScopePanel";

const previewAgent = {
  agentId: "frontend-ux-preview-agent",
  agentCode: "UX-01",
  displayName: "验收 Agent",
} as AgentInstance;

const scopeCopy = {
  blocked: "当前范围受阻",
  callable: "所选范围可调用",
  configure: "配置",
  configureAgent: "配置 Agent",
  loading: "加载中",
  scope: "Agent 范围",
  synced: "已同步",
  unsaved: "未保存",
  visible: "当前范围可见",
};

const previewModel: SessionLlmModelOption = {
  modelId: "preview/luna",
  modelRef: "preview/luna",
  label: "Luna 5.6",
  model: "luna-5.6",
  providerId: "preview",
  providerLabel: "Preview",
  providerKind: "relay",
  apiKeyConfigured: true,
  missingApiKey: false,
  supportsReasoningEffort: true,
  reasoningEffortValues: ["low", "high"],
  reasoningEffortOptions: [
    { value: "low", label: "低", description: "快速响应" },
    { value: "high", label: "高", description: "复杂任务" },
  ],
  defaultReasoningEffort: "low",
  isDefault: true,
};

const alternateModel: SessionLlmModelOption = {
  ...previewModel,
  modelId: "preview/sol",
  modelRef: "preview/sol",
  label: "Sol 4",
  model: "sol-4",
  isDefault: false,
};

const previewQueryClient = () => {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        staleTime: Infinity,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
      },
    },
  });
  const chatDomains = normalizeDictionaryDomains(["chat"]);
  client.setQueryData(queryKeys.configPublic(), { language: "zh" });
  client.setQueryData(
    ["i18n", "dictionary-domains", dictionaryDomainsQueryKey(chatDomains)],
    dictionary,
  );
  // ConversationInferenceControl enables this query whenever it receives a
  // model. Seed an empty local result so the isolated preview makes no request.
  client.setQueryData(queryKeys.chatReviewModelCurationStats(), { models: [] });
  return client;
};

export function ControlsPreview() {
  const [queryClient] = useState(previewQueryClient);
  const [reasoningEffort, setReasoningEffort] = useState("high");
  const [modelSelection, setModelSelection] = useState<SessionModelSelection | null>(null);

  return (
    <QueryClientProvider client={queryClient}>
      <div className="grid h-full min-h-0 content-start gap-3 overflow-auto p-3">
        <section className="grid min-w-0 gap-2" aria-label="工具范围与 Agent 权限口径">
          <ToolsRouteAgentScopePanel
            copy={scopeCopy}
            activeAgents={[previewAgent]}
            activeAgent={previewAgent}
            agentsLoading={false}
            activeAgentScopeId="main_agent"
            scopeOptions={[{ id: "main_agent", label: "主 Agent" }]}
            scopeCounts={{ visible: 128, callable: 125, blocked: 3 }}
            dirty={false}
            deepLinkNotice=""
            onAgentChange={() => undefined}
            onScopeChange={() => undefined}
          />
          <VPanel ariaLabel="Agent 工具权限预览" className="grid min-w-0 gap-2 p-3">
            <VPanelHeader title="Agent 工具权限 · UX-01 验收 Agent" />
            <div className="grid min-w-0 grid-cols-2 gap-2 text-vui-xs max-[520px]:grid-cols-1">
              <span>所选范围可调用：125</span>
              <span>明确允许：0</span>
            </div>
            <p className="m-0 text-vui-xs leading-[var(--vui-line-readable)] text-vui-fg-secondary">
              顶部统计所选 Agent 范围内的可调用工具（不是全局注册总数）；当前 Agent 的明确允许项与工具测试批准分别判断。
            </p>
          </VPanel>
        </section>

        <VPanel ariaLabel="对话输入区模型控件预览" className="grid min-w-0 gap-2 p-3">
          <VPanelHeader title="对话输入区控件 · 本地交互" />
          <p className="m-0 text-vui-xs leading-[var(--vui-line-readable)] text-vui-fg-secondary">
            推理强度控制会话推理级别；本轮模型选择只影响下一次发送。点击控件可切换选项，状态仅保存在此预览中。
          </p>
          <div className="flex min-w-0 flex-wrap items-center gap-2" aria-label="推理强度与本轮模型">
            <ConversationInferenceControl
              model={previewModel}
              sessionId="frontend-ux-preview-session"
              currentReasoningEffort={reasoningEffort}
              disabled={false}
              pending={false}
              onReasoningEffortChange={setReasoningEffort}
            />
            <ConversationTurnModelControl
              choices={[previewModel, alternateModel]}
              sessionDefaultModelId={previewModel.modelRef}
              selection={modelSelection}
              disabled={false}
              onSelectionChange={setModelSelection}
            />
          </div>
        </VPanel>
      </div>
    </QueryClientProvider>
  );
}
