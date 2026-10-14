import React, { useCallback, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { queryKeys } from "../../src/api/queryKeys";
import type { SessionLlmModelOption } from "../../src/api/types";
import { VuiProvider } from "../../src/components/vui/VuiProvider";
import { ConversationTurnModelControl } from "../../src/components/conversation/ConversationTurnModelControl";
import { dictionaryDomainsQueryKey, normalizeDictionaryDomains } from "../../src/i18n/dictionaryDomainIds";
import { loadDictionaryDomains } from "../../src/i18n/loadDictionaryDomains";
import "../../src/design/tokens.css";
import "../../src/design/base.css";
import "../../src/design/tailwind.css";
import "../../src/design/vui-provider-theme.css";
import "../../src/design/vui-native-controls.css";
import "./preview.css";

window.fetch = async () => {
  throw new Error("Network access is disabled in this preview.");
};

type PreviewAgent = {
  sessionId: string;
  agentId: string;
  configRevision: number;
  contextWindow: number;
  maxContextWindow: number;
  currentReasoningEffort: string;
  model: SessionLlmModelOption;
};

const agents: PreviewAgent[] = [
  {
    sessionId: "preview-session-sol",
    agentId: "preview-agent-sol",
    configRevision: 12,
    contextWindow: 128_000,
    maxContextWindow: 200_000,
    currentReasoningEffort: "high",
    model: {
      modelId: "openai/gpt-6.1-sol",
      modelRef: "openai/gpt-6.1-sol",
      label: "GPT-6.1 Sol",
      model: "gpt-6.1-sol",
      providerId: "openai",
      providerLabel: "OpenAI",
      providerKind: "openai",
      apiKeyConfigured: true,
      missingApiKey: false,
      supportsReasoningEffort: true,
      reasoningEffortValues: ["low", "medium", "high", "xhigh", "max", "ultra"],
      reasoningEffortOptions: [
        { value: "low", label: "低", description: "快速响应" },
        { value: "medium", label: "中", description: "平衡" },
        { value: "high", label: "高", description: "更充分推理" },
        { value: "xhigh", label: "很高", description: "" },
        { value: "max", label: "最大", description: "" },
        { value: "ultra", label: "极致", description: "" },
      ],
      defaultReasoningEffort: "high",
      isDefault: true,
    },
  },
  {
    sessionId: "preview-session-claude",
    agentId: "preview-agent-claude",
    configRevision: 6,
    contextWindow: 96_000,
    maxContextWindow: 200_000,
    currentReasoningEffort: "high",
    model: {
      modelId: "anthropic/claude-sonnet-4",
      modelRef: "anthropic/claude-sonnet-4",
      label: "Claude Sonnet 4",
      model: "claude-sonnet-4",
      providerId: "anthropic",
      providerLabel: "Anthropic",
      providerKind: "anthropic",
      apiKeyConfigured: true,
      missingApiKey: false,
      supportsReasoningEffort: true,
      reasoningEffortValues: ["low", "medium", "high"],
      reasoningEffortOptions: [
        { value: "low", label: "低", description: "快速响应" },
        { value: "medium", label: "中", description: "平衡" },
        { value: "high", label: "高", description: "更充分推理" },
      ],
      defaultReasoningEffort: "medium",
      isDefault: false,
    },
  },
];

function App() {
  const [agentIndex, setAgentIndex] = useState(0);
  const agentScopeRef = useRef(0);
  const agentIndexRef = useRef(agentIndex);
  const saveOperationRef = useRef(0);
  const [contextWindow, setContextWindow] = useState(agents[0].contextWindow);
  const [reasoningEffort, setReasoningEffort] = useState(agents[0].currentReasoningEffort);
  const [outcome, setOutcome] = useState<"success" | "failure">("success");
  const [pending, setPending] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [status, setStatus] = useState("等待操作");
  const agent = useMemo(() => ({
    ...agents[agentIndex],
    contextWindow,
    currentReasoningEffort: reasoningEffort,
  }), [agentIndex, contextWindow, reasoningEffort]);

  const handleSave = useCallback((parameters: { contextWindow: number; reasoningEffort: string }) => {
    const operation = ++saveOperationRef.current;
    const agentScope = agentScopeRef.current;
    const savingAgentIndex = agentIndex;
    setPending(true);
    setErrorMessage("");
    setStatus("保存中");
    window.setTimeout(() => {
      if (
        operation !== saveOperationRef.current
        || agentScope !== agentScopeRef.current
        || savingAgentIndex !== agentIndexRef.current
      ) return;
      setPending(false);
      if (outcome === "success") {
        setContextWindow(parameters.contextWindow);
        setReasoningEffort(parameters.reasoningEffort);
        setStatus("保存成功");
      } else {
        setErrorMessage("模型参数保存失败");
        setStatus("保存失败：草稿仍保留");
      }
    }, 1_200);
  }, [agentIndex, outcome]);

  const handleAgentSwitch = () => {
    agentScopeRef.current += 1;
    saveOperationRef.current += 1;
    const nextIndex = (agentIndex + 1) % agents.length;
    agentIndexRef.current = nextIndex;
    setAgentIndex(nextIndex);
    setContextWindow(agents[nextIndex].contextWindow);
    setReasoningEffort(agents[nextIndex].currentReasoningEffort);
    setPending(false);
    setErrorMessage("");
    setStatus("已切换 Agent");
  };

  return (
    <main className="preview-page">
      <header className="preview-heading">
        <h1>消息栏模型参数</h1>
      </header>

      <details className="preview-controls" aria-label="Preview controls">
        <summary>预览状态</summary>
        <div className="preview-state-controls">
        <label className="preview-scenario">
          <span>保存结果</span>
          <select
            value={outcome}
            onChange={(event) => setOutcome(event.target.value as "success" | "failure")}
            aria-label="模拟保存结果"
          >
            <option value="success">成功</option>
            <option value="failure">失败</option>
          </select>
        </label>
        <button type="button" onClick={() => { setPending(true); setErrorMessage(""); setStatus("保存中"); }}>
          模拟保存中
        </button>
        <button type="button" onClick={() => { setPending(false); setStatus("保存状态已结束"); }}>
          结束保存
        </button>
        <button type="button" onClick={handleAgentSwitch}>
          切换 Agent
        </button>
        <button type="button" onClick={() => { setPending(false); setErrorMessage("模型参数保存失败"); setStatus("保存失败：草稿仍保留"); }}>
          显示失败
        </button>
        <span className="preview-status" role="status">{status}</span>
        </div>
      </details>

      <section className="chat-preview" aria-label="Composer preview">
        <div className="sample-message">
          <div className="sample-avatar" aria-hidden="true">A</div>
          <p>请分析这个模块的主要职责，并指出最值得优先处理的问题。</p>
        </div>
        <div className="composer-preview">
          <textarea aria-label="消息输入预览" placeholder="发送消息给 Agent…" rows={2} />
          <div className="composer-footer">
            <span className="composer-add" aria-hidden="true">+</span>
            <div className="composer-model-slot">
              <ConversationTurnModelControl
                sessionId={agent.sessionId}
                agentId={agent.agentId}
                configRevision={agent.configRevision}
                model={agent.model}
                contextWindow={agent.contextWindow}
                maxContextWindow={agent.maxContextWindow}
                currentReasoningEffort={agent.currentReasoningEffort}
                pending={pending}
                errorMessage={errorMessage}
                onSave={handleSave}
              />
            </div>
            <span className="composer-context">64K / {agent.contextWindow % 1_000 === 0 ? `${agent.contextWindow / 1_000}K` : agent.contextWindow.toLocaleString("zh-CN")}</span>
          <button className="composer-send" type="button" aria-label="发送预览" disabled={pending}>↑</button>
          </div>
        </div>
      </section>

    </main>
  );
}

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, staleTime: Infinity } },
});
const domains = normalizeDictionaryDomains(["chat"]);
const dictionaryKey = ["i18n", "dictionary-domains", dictionaryDomainsQueryKey(domains)] as const;
let previewRoot: ReturnType<typeof createRoot> | undefined;
let previewDisposed = false;

if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    previewDisposed = true;
    previewRoot?.unmount();
  });
}

async function mountPreview() {
  queryClient.setQueryData(queryKeys.configPublic(), { language: "zh" });
  queryClient.setQueryData(dictionaryKey, await loadDictionaryDomains(["chat"]));
  if (previewDisposed) return;
  previewRoot = createRoot(document.getElementById("root")!);
  previewRoot.render(
    <React.StrictMode>
      <QueryClientProvider client={queryClient}>
        <VuiProvider>
          <App />
        </VuiProvider>
      </QueryClientProvider>
    </React.StrictMode>,
  );
}

void mountPreview();
