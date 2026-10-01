import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { VuiProvider } from "../../src/components/vui";
import { MemoryAgentMemoryPanel, type MemoryAgentMemoryPanelCopy } from "../../src/routes/MemoryAgentMemoryPanel";
import "./production.css";
const copy: MemoryAgentMemoryPanelCopy = {
  agentMemoryAgents: "Agent 列表",
  privateMemoryLabel: "私有",
  privateMemoryFileUnit: "份记忆文件",
  privateMemorySwitchAgent: "切换 Agent",
  privateMemoryReadingHint: "这里展示已保存的记忆。",
  privateMemoryIsolationHint: "每个 Agent 的私有记忆相互隔离。",
  privateMemoryAllFiles: "全部记忆文件",
  agentMemoryPrivateFiles: "私有文件",
  agentMemoryFormalKnowledge: "正式知识",
  agentMemoryFormalBases: "正式知识库",
  warnings: "提醒",
  agentMemorySelectedAgent: "当前 Agent",
  agentMemorySelectPrompt: "选择一个 Agent",
  searchPlaceholder: "搜索",
  searchAgents: "搜索 Agent",
  loading: "正在加载",
  loadFailed: "加载失败",
  agentMemoryNoAgents: "暂无 Agent",
  agentMemoryPrivateRoot: "私有记忆目录",
  sourcePath: "来源路径",
  agentMemoryNoPrivateMemory: "暂无私有记忆",
  truncated: "内容已截断",
  agentMemorySelectedFile: "记忆文件",
  agentMemoryNoFileSelected: "请选择文件",
  noMatches: "没有匹配的 Agent",
  rawContent: "原始内容",
  noContent: "无内容",
  generatedAt: "更新时间",
  browseBack: "返回列表",
  memoryCount: "份记忆",
  groupHasMemory: "有记忆",
  groupNoMemory: "暂无记忆",
  expandGroup: "展开",
  collapseGroup: "收起",
  groupChat: "对话",
  groupResearch: "研究",
  groupSelfEvolution: "自我进化",
  groupSupervised: "监督式进化",
  groupGeneral: "通用",
  groupOther: "其他",
};

const agents = [
  {
    id: "agent-alpha",
    name: "Alpha Agent",
    status: "active",
    origin: "alpha",
    path: "C:/agents/alpha/memory",
    privateFileCount: 1,
    formalKnowledgeBaseCount: 0,
    hasPrivateMemory: true,
    primaryMode: "chat",
    active: true,
  },
  {
    id: "agent-beta",
    name: "Beta Agent",
    status: "active",
    origin: "beta",
    path: "C:/agents/beta/memory",
    privateFileCount: 1,
    formalKnowledgeBaseCount: 0,
    hasPrivateMemory: true,
    primaryMode: "research",
    active: false,
  },
  {
    id: "agent-empty",
    name: "Empty Agent",
    status: "idle",
    origin: "empty",
    path: "C:/agents/empty/memory",
    privateFileCount: 0,
    formalKnowledgeBaseCount: 0,
    hasPrivateMemory: false,
    primaryMode: "general",
    active: false,
  },
];

const baseProps: React.ComponentProps<typeof MemoryAgentMemoryPanel> = {
  copy,
  summary: {
    agentCount: agents.length,
    privateFileCount: 2,
    privateByteText: "128 B",
    formalKnowledgeItemCount: 0,
    formalKnowledgeBaseCount: 0,
    warningCount: 0,
  },
  searchText: "",
  onSearchTextChange: () => undefined,
  agents,
  selectedAgent: {
    name: "Alpha Agent",
    privateRoot: "C:/agents/alpha/memory",
    workspacePath: "C:/agents/alpha",
    fileCount: 1,
    formalKnowledgeItemCount: 0,
    formalKnowledgeBaseCount: 0,
    knowledgeBases: [],
  },
  selectedItem: {
    title: "preferences.md",
    path: "C:/agents/alpha/memory/preferences.md",
    sizeText: "128 B",
    contentType: "text/markdown",
    contentLanguage: "zh",
    content: "Alpha saved memory body",
  },
  items: [
    {
      id: "alpha-preferences",
      title: "preferences.md",
      updatedAtText: "刚刚",
      path: "C:/agents/alpha/memory/preferences.md",
      summary: "Alpha summary",
      sizeText: "128 B",
      contentType: "text/markdown",
      truncated: false,
      active: true,
      content: "Alpha saved memory body",
    },
  ],
  inventoryPending: false,
  inventoryErrorText: "",
  detailPending: false,
  detailFetching: false,
  detailErrorText: "",
  generatedAtText: "刚刚",
  onSelectAgent: () => undefined,
  onSelectItem: () => undefined,
};


function App() {
 const [agentId, setAgentId] = useState("agent-alpha"), [selected,setSelected]=useState("alpha-preferences"), [search,setSearch]=useState("");
 const initial={...baseProps.items[0], id:"initial",title:"memory.json",content:'{"core_wisdom":"初始状态","current_goal":"","last_archive_time":null}', active:false};
 const body={...baseProps.items[0],content: JSON.stringify({交流约定:"先给结论，再展开依据。技术讨论使用中文，代码名称和协议字段保留原文。",经验:"启动成功不等于更新已经生效，需要区分代码合入、构建与运行验证。",注意事项:["这些是验收用测试数据，不是任何真实 Agent 的记忆。","生产组件只接收现有接口提供的文件正文。"]})};
 const items=agentId==="agent-alpha"?[body,initial]:[];
 return <VuiProvider><div className="production-test"><header>正式记忆组件 · 隔离验收 · 测试数据</header><MemoryAgentMemoryPanel {...baseProps}
 agents={agents.filter(a=>a.name.toLowerCase().includes(search.toLowerCase())).map(a=>({...a,active:a.id===agentId}))}
 searchText={search} onSearchTextChange={setSearch} onSelectAgent={setAgentId} onSelectItem={setSelected}
 selectedAgent={{...baseProps.selectedAgent!,name:agents.find(a=>a.id===agentId)!.name,privateRoot:agentId}}
 items={items.map(i=>({...i,active:i.id===selected}))}/></div></VuiProvider>;
}
const root=createRoot(document.getElementById("root")!);root.render(<App/>);
if(import.meta.hot) import.meta.hot.dispose(()=>root.unmount());
