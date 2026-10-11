// Documentation fixture. Production components, public example data, no runtime.
import React from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { VuiProvider } from "../../../web/src/components/vui";
import { ConversationView } from "../../../web/src/components/conversation/ConversationView";
import { MemoryAgentMemoryPanel } from "../../../web/src/routes/MemoryAgentMemoryPanel";
import type { MemoryAgentMemoryPanelCopy } from "../../../web/src/routes/MemoryAgentMemoryPanel";
import type { ConversationMessage } from "../../../web/src/api/types";
import { dictionary } from "../../../web/src/i18n/dictionary";
import { queryKeys } from "../../../web/src/api/queryKeys";
import { DICTIONARY_DOMAIN_IDS, dictionaryDomainsQueryKey } from "../../../web/src/i18n/dictionaryDomainIds";
import "./capture.css";

const lang = new URLSearchParams(location.search).get("lang") === "en" ? "en" : "zh";
document.documentElement.lang = lang;
document.documentElement.dataset.theme = "light";
// Fail closed: this fixture never calls a model or reads live conversations.
window.fetch = async () => new Response("{}", { status: 403, headers: { "content-type": "application/json" } });
const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
client.setQueryData(queryKeys.configPublic(), { language: lang });
client.setQueryData(["i18n", "dictionary-domains", dictionaryDomainsQueryKey(DICTIONARY_DOMAIN_IDS)], dictionary);
client.setQueryData(["i18n", "dictionary-domains", "core,chat"], dictionary);
const en = lang === "en";
const answer = en
  ? "## Start with one clear task\n\nKeep sources, options and the next step together.\n\n| Step | Keep |\n| --- | --- |\n| Read | Sources and context |\n| Discuss | Questions and options |\n| Review | Evidence and next step |\n\n**Next:** compare two approaches."
  : "## 从一个清楚的任务开始\n\n将资料、方案与下一步留在同一段对话中。\n\n| 步骤 | 留下什么 |\n| --- | --- |\n| 阅读 | 资料与上下文 |\n| 讨论 | 问题与方案 |\n| 评审 | 依据与下一步 |\n\n**下一步：** 对比两种方案。";
const messages: ConversationMessage[] = [
  { id: "readme-user", role: "user", content: en ? "How do I start a review with one Agent?" : "用一个 Agent 开始项目审查，先做什么？", timestamp: "2026-10-11T08:00:00Z" },
  { id: "readme-answer", role: "assistant", status: "completed", timestamp: "2026-10-11T08:00:01Z", turnId: "readme-example", turnItems: [{ id: "readme-final", itemId: "readme-final", version: 3, sessionId: "readme-example", turnId: "readme-example", type: "agent_message", phase: "final_answer", status: "completed", sequence: 1, revision: 1, createdAt: "2026-10-11T08:00:01Z", updatedAt: "2026-10-11T08:00:01Z", text: answer, terminal: true }] },
];
const copy: MemoryAgentMemoryPanelCopy = {
  agentMemoryAgents: en ? "Agents" : "Agent 列表", privateMemoryLabel: en ? "Private" : "私有", privateMemoryFileUnit: en ? "memory files" : "份记忆文件", privateMemorySwitchAgent: en ? "Switch Agent" : "切换 Agent", privateMemoryReadingHint: en ? "Read saved memory files." : "阅读已保存的记忆文件。", privateMemoryIsolationHint: en ? "Private memory belongs to its Agent." : "每个 Agent 的私有记忆相互隔离。", privateMemoryAllFiles: en ? "All memory files" : "全部记忆文件", agentMemoryPrivateFiles: en ? "Private files" : "私有文件", agentMemoryFormalKnowledge: en ? "Knowledge" : "正式知识", agentMemoryFormalBases: en ? "Knowledge bases" : "正式知识库", warnings: en ? "Notices" : "提醒", agentMemorySelectedAgent: en ? "Selected Agent" : "当前 Agent", agentMemorySelectPrompt: en ? "Select an Agent" : "选择一个 Agent", searchPlaceholder: en ? "Search" : "搜索", searchAgents: en ? "Search Agents" : "搜索 Agent", loading: en ? "Loading" : "正在加载", loadFailed: en ? "Could not load" : "加载失败", agentMemoryNoAgents: en ? "No Agents" : "暂无 Agent", agentMemoryPrivateRoot: en ? "Private memory" : "私有记忆目录", sourcePath: en ? "Source path" : "来源路径", agentMemoryNoPrivateMemory: en ? "No private memory" : "暂无私有记忆", truncated: en ? "Truncated" : "内容已截断", agentMemorySelectedFile: en ? "Memory file" : "记忆文件", agentMemoryNoFileSelected: en ? "Choose a file" : "请选择文件", noMatches: en ? "No matching Agents" : "没有匹配的 Agent", rawContent: en ? "Raw content" : "原始内容", noContent: en ? "No content" : "无内容", generatedAt: en ? "Updated" : "更新时间", browseBack: en ? "Back" : "返回列表", memoryCount: en ? "memories" : "份记忆", groupHasMemory: en ? "Has memory" : "有记忆", groupNoMemory: en ? "No memory" : "暂无记忆", expandGroup: en ? "Expand" : "展开", collapseGroup: en ? "Collapse" : "收起", groupChat: en ? "Chat" : "对话", groupResearch: en ? "Research" : "研究", groupSelfEvolution: en ? "Self evolution" : "自我进化", groupSupervised: en ? "Supervised" : "监督式进化", groupGeneral: en ? "General" : "通用", groupOther: en ? "Other" : "其他",
};
const content = JSON.stringify(en ? {
  "Working agreement": "Read the relevant files before proposing changes. Keep source references with each finding.",
  "Next task": "Compare two approaches and explain their tradeoffs.",
  "Data source": "Public example notes; no private Agent memory.",
} : {
  "工作约定": "提出修改建议前先阅读相关文件，每一条发现都保留来源。",
  "下一项任务": "对比两种方案，说明各自的取舍。",
  "数据来源": "公开示例笔记，不是真实 Agent 的私有记忆。",
}, null, 2);
const sizeText = `${new TextEncoder().encode(content).length} B`;
function App() {
  const memory = new URLSearchParams(location.search).get("view") === "memory";
  return <QueryClientProvider client={client}><VuiProvider><div className="capture">
    <header><strong>Vibelution</strong><span>{memory ? (en ? "Memory" : "记忆库") : (en ? "Conversation" : "对话")}</span><small>{en ? "Production component · example data" : "生产组件 · 示例数据"}</small></header>
    <main>{memory ? <MemoryAgentMemoryPanel lang={lang} selectedAgentId="review-agent" copy={copy} summary={{ agentCount: 1, privateFileCount: 1, privateByteText: sizeText, formalKnowledgeItemCount: 0, formalKnowledgeBaseCount: 0, warningCount: 0 }} searchText="" onSearchTextChange={() => {}} agents={[{ id: "review-agent", name: en ? "Project reviewer" : "项目评审 Agent", status: "idle", origin: "example", path: "example/reviewer/memory", privateFileCount: 1, formalKnowledgeBaseCount: 0, hasPrivateMemory: true, primaryMode: "chat", active: true }]} selectedAgent={{ name: en ? "Project reviewer" : "项目评审 Agent", privateRoot: "example/reviewer/memory", workspacePath: "example/reviewer", fileCount: 1, formalKnowledgeItemCount: 0, formalKnowledgeBaseCount: 0, knowledgeBases: [] }} selectedItem={{ title: "review-notes.json", path: "example/reviewer/memory/review-notes.json", sizeText: sizeText, contentType: "application/json", contentLanguage: lang, content }} items={[{ id: "review-notes", title: "review-notes.json", updatedAtText: "2026-10-11", path: "example/reviewer/memory/review-notes.json", summary: en ? "Working agreement and the next task" : "工作约定与下一项任务", sizeText: sizeText, contentType: "application/json", truncated: false, active: true, content }]} inventoryPending={false} inventoryErrorText="" detailPending={false} detailFetching={false} detailErrorText="" generatedAtText="2026-10-11" onSelectAgent={() => {}} onSelectItem={() => {}} />
      : <ConversationView defaultFileContext="workspace" sessionId="readme-example" title={en ? "Project review" : "项目审查"} phase="ready" assistantDisplayName={en ? "Project reviewer" : "项目评审 Agent"} assistantAvatarFallback="V" userDisplayName={en ? "You" : "你"} messages={messages} showHeader={false} showSessionOverview={false} showMentalSnapshots={false} promptSuggestionEnabled={false} processDisplayMode="answer" composerValue="" composerPlaceholder={en ? "Describe the next task…" : "描述下一项任务…"} composerDisabled={false} composerPending={false} submitLabel={en ? "Send" : "发送"} onComposerChange={() => {}} onSubmit={() => {}} onEditUserMessage={() => {}} />}</main>
    <footer>{en ? "UI example only · no model run or live data" : "界面示例 · 未调用模型，未读取运行数据"}</footer>
  </div></VuiProvider></QueryClientProvider>;
}
createRoot(document.getElementById("root")!).render(<App />);
