// Documentation fixture. Production components, public example data, no runtime.
import React, { useState } from "react";
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
const memoryRecords = en ? [
  {
    id: "review-notes",
    title: "review-notes.json",
    updatedAtText: "2026-10-11",
    summary: "Keyboard behavior, source references, and next browser checks.",
    body: {
      "Project agreement": {
        "Keys": "Tab moves focus; Enter opens; Escape closes.",
        "Focus": "Return to the task card after closing details.",
      },
      "Source references": {
        "Component": "src/TaskBoard.tsx",
        "Guide": "docs/keyboard.md",
      },
      "Next check": "Try the keyboard flow in a browser and confirm focus returns.",
    },
  },
  {
    id: "project-brief",
    title: "project-brief.json",
    updatedAtText: "2026-10-10",
    summary: "Task-board goal, audience, and scope.",
    body: {
      "Goal": "Help a team create, assign, and track actionable tasks.",
      "Scope": "Task list, task details, and keyboard access to open and close the panel.",
      "Completion": "A user can locate a task, open its details, and return using only the keyboard.",
    },
  },
  {
    id: "visual-checklist",
    title: "visual-checklist.json",
    updatedAtText: "2026-10-10",
    summary: "Browser checks for task-board keyboard access.",
    body: {
      "Tab order": "Move through the task list and controls without skipping the focused task.",
      "Open and close": "Use Enter to open the selected task and Escape to close its panel.",
      "Focus": "Confirm focus returns to the task that opened the panel.",
      "Browser run": "Complete the list-to-detail flow without using a pointer.",
    },
  },
] : [
  {
    id: "review-notes",
    title: "review-notes.json",
    updatedAtText: "2026-10-11",
    summary: "任务看板键盘操作、来源与下一步检查。",
    body: {
      "项目约定": {
        "按键": "Tab 切换焦点，Enter 打开，Escape 关闭。",
        "焦点": "关闭详情后，返回原任务卡片。",
      },
      "来源引用": {
        "组件": "src/TaskBoard.tsx",
        "指南": "docs/keyboard.md",
      },
      "下一步": "在浏览器走一遍键盘流程，核对焦点返回。",
    },
  },
  {
    id: "project-brief",
    title: "project-brief.json",
    updatedAtText: "2026-10-10",
    summary: "任务看板目标与使用范围。",
    body: {
      "目标": "帮助团队创建、分派并跟踪可执行任务。",
      "范围": "任务列表、任务详情，以及用键盘打开和关闭详情面板。",
      "完成标准": "用户只用键盘就能找到任务、打开详情并返回列表。",
    },
  },
  {
    id: "visual-checklist",
    title: "visual-checklist.json",
    updatedAtText: "2026-10-10",
    summary: "浏览器中的任务看板键盘核对清单。",
    body: {
      "焦点顺序": "Tab 依序经过任务列表和控件，不跳过当前任务。",
      "打开与关闭": "Enter 打开所选任务，Escape 关闭详情面板。",
      "焦点恢复": "确认关闭后焦点回到打开详情的任务。",
      "浏览器走查": "不使用鼠标，完成列表、详情与关闭的全流程。",
    },
  },
];
function App() {
  const memory = new URLSearchParams(location.search).get("view") === "memory";
  const [selectedMemoryId, setSelectedMemoryId] = useState("review-notes");
  const [searchText, setSearchText] = useState("");
  const [selectedAgentId, setSelectedAgentId] = useState("review-agent");
  const memoryItems = memoryRecords.map((record) => {
    const content = JSON.stringify(record.body, null, 2);
    return {
      id: record.id,
      title: record.title,
      updatedAtText: record.updatedAtText,
      path: `example/task-board/memory/${record.title}`,
      summary: record.summary,
      sizeText: `${new TextEncoder().encode(content).length} B`,
      contentType: "application/json",
      truncated: false,
      active: record.id === selectedMemoryId,
      content,
    };
  });
  const selectedMemory = memoryItems.find((item) => item.id === selectedMemoryId) ?? memoryItems[0];
  const privateByteText = `${memoryItems.reduce((total, item) => total + new TextEncoder().encode(item.content).length, 0)} B`;
  return <QueryClientProvider client={client}><VuiProvider><div className={`capture${memory ? " capture-memory" : ""}`}>
    <header><strong>Vibelution</strong><span>{memory ? (en ? "Memory" : "记忆库") : (en ? "Conversation" : "对话")}</span><small>{memory ? (en ? "Example data" : "示例数据") : (en ? "Production component · example data" : "生产组件 · 示例数据")}</small></header>
    <main>{memory ? <MemoryAgentMemoryPanel lang={lang} selectedAgentId={selectedAgentId} copy={copy} summary={{ agentCount: 1, privateFileCount: memoryItems.length, privateByteText, formalKnowledgeItemCount: 0, formalKnowledgeBaseCount: 0, warningCount: 0 }} searchText={searchText} onSearchTextChange={setSearchText} agents={[{ id: "review-agent", name: en ? "Project reviewer" : "项目评审 Agent", status: "idle", origin: "example", path: "example/task-board/memory", privateFileCount: memoryItems.length, formalKnowledgeBaseCount: 0, hasPrivateMemory: true, primaryMode: "chat", active: selectedAgentId === "review-agent" }]} selectedAgent={{ name: en ? "Project reviewer" : "项目评审 Agent", privateRoot: "example/task-board/memory", workspacePath: "example/task-board", fileCount: memoryItems.length, formalKnowledgeItemCount: 0, formalKnowledgeBaseCount: 0, knowledgeBases: [] }} selectedItem={selectedMemory ? { title: selectedMemory.title, path: selectedMemory.path, sizeText: selectedMemory.sizeText, contentType: selectedMemory.contentType, contentLanguage: lang, content: selectedMemory.content } : null} items={memoryItems} inventoryPending={false} inventoryErrorText="" detailPending={false} detailFetching={false} detailErrorText="" generatedAtText="2026-10-11" onSelectAgent={setSelectedAgentId} onSelectItem={setSelectedMemoryId} />
      : <ConversationView defaultFileContext="workspace" sessionId="readme-example" title={en ? "Project review" : "项目审查"} phase="ready" assistantDisplayName={en ? "Project reviewer" : "项目评审 Agent"} assistantAvatarFallback="V" userDisplayName={en ? "You" : "你"} messages={messages} showHeader={false} showSessionOverview={false} showMentalSnapshots={false} promptSuggestionEnabled={false} processDisplayMode="answer" composerValue="" composerPlaceholder={en ? "Describe the next task…" : "描述下一项任务…"} composerDisabled={false} composerPending={false} submitLabel={en ? "Send" : "发送"} onComposerChange={() => {}} onSubmit={() => {}} onEditUserMessage={() => {}} />}</main>
    <footer>{en ? "UI example only · no model run or live data" : "界面示例 · 未调用模型，未读取运行数据"}</footer>
  </div></VuiProvider></QueryClientProvider>;
}
createRoot(document.getElementById("root")!).render(<App />);
