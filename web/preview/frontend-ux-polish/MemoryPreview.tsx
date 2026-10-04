import { useState } from "react";

import { VuiProvider } from "../../src/components/vui";
import {
  MemoryAgentMemoryPanel,
  type MemoryAgentMemoryAgentView,
  type MemoryAgentMemoryItemView,
  type MemoryAgentMemoryPanelCopy,
  type MemoryAgentMemorySelectedAgentView,
} from "../../src/routes/MemoryAgentMemoryPanel";

type PreviewAgentId = "agent-alpha" | "agent-beta" | "agent-empty";

type PreviewAgentFixture = {
  selectedAgent: MemoryAgentMemorySelectedAgentView;
  items: MemoryAgentMemoryItemView[];
};

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

const previewAgents: Omit<MemoryAgentMemoryAgentView, "active">[] = [
  {
    id: "agent-alpha",
    name: "Alpha Agent",
    status: "active",
    origin: "alpha",
    path: "模拟路径/Alpha Agent/memory",
    privateFileCount: 1,
    formalKnowledgeBaseCount: 0,
    hasPrivateMemory: true,
    primaryMode: "chat",
  },
  {
    id: "agent-beta",
    name: "Beta Agent",
    status: "active",
    origin: "beta",
    path: "模拟路径/Beta Agent/memory",
    privateFileCount: 1,
    formalKnowledgeBaseCount: 0,
    hasPrivateMemory: true,
    primaryMode: "research",
  },
  {
    id: "agent-empty",
    name: "Empty Agent",
    status: "idle",
    origin: "empty",
    path: "模拟路径/Empty Agent/memory",
    privateFileCount: 0,
    formalKnowledgeBaseCount: 0,
    hasPrivateMemory: false,
    primaryMode: "general",
  },
];

const previewFixtures: Record<PreviewAgentId, PreviewAgentFixture> = {
  "agent-alpha": {
    selectedAgent: {
      name: "Alpha Agent",
      privateRoot: "模拟路径/Alpha Agent/memory",
      workspacePath: "模拟路径/Alpha Agent",
      fileCount: 1,
      formalKnowledgeItemCount: 0,
      formalKnowledgeBaseCount: 0,
      knowledgeBases: [],
    },
    items: [
      {
        id: "alpha-memory",
        title: "memory.json",
        updatedAtText: "模拟更新时间",
        path: "模拟路径/Alpha Agent/memory/memory.json",
        summary: "Alpha 的本地模拟记忆",
        sizeText: "128 B",
        contentType: "application/json",
        truncated: false,
        active: true,
        content: JSON.stringify({
          core_wisdom: "Alpha 的模拟记忆正文",
          current_goal: "验证搜索过滤与归属显示",
          mock_note: "此内容仅用于本地验收",
        }, null, 2),
      },
    ],
  },
  "agent-beta": {
    selectedAgent: {
      name: "Beta Agent",
      privateRoot: "模拟路径/Beta Agent/memory",
      workspacePath: "模拟路径/Beta Agent",
      fileCount: 1,
      formalKnowledgeItemCount: 0,
      formalKnowledgeBaseCount: 0,
      knowledgeBases: [],
    },
    items: [
      {
        id: "beta-memory",
        title: "memory.json",
        updatedAtText: "模拟更新时间",
        path: "模拟路径/Beta Agent/memory/memory.json",
        summary: "Beta 的本地模拟记忆",
        sizeText: "96 B",
        contentType: "application/json",
        truncated: false,
        active: true,
        content: JSON.stringify({
          core_wisdom: "Beta 的模拟记忆正文",
          current_goal: "展示切换 Agent 后的文件归属",
          mock_note: "此内容仅用于本地验收",
        }, null, 2),
      },
    ],
  },
  "agent-empty": {
    selectedAgent: {
      name: "Empty Agent",
      privateRoot: "模拟路径/Empty Agent/memory",
      workspacePath: "模拟路径/Empty Agent",
      fileCount: 0,
      formalKnowledgeItemCount: 0,
      formalKnowledgeBaseCount: 0,
      knowledgeBases: [],
    },
    items: [],
  },
};

export function MemoryPreview() {
  const [selectedAgentId, setSelectedAgentId] = useState<PreviewAgentId>("agent-alpha");
  const [selectedItemId, setSelectedItemId] = useState("alpha-memory");
  const [searchText, setSearchText] = useState("");

  const selectedFixture = previewFixtures[selectedAgentId];
  const items = selectedFixture.items.map((item) => ({
    ...item,
    active: item.id === selectedItemId,
  }));
  const selectedItem = items.find((item) => item.active);
  const visibleAgents = previewAgents
    .filter((agent) => agent.name.toLocaleLowerCase().includes(searchText.trim().toLocaleLowerCase()))
    .map((agent) => ({ ...agent, active: agent.id === selectedAgentId }));

  const selectAgent = (agentId: string) => {
    if (!isPreviewAgentId(agentId)) {
      return;
    }
    setSelectedAgentId(agentId);
    setSelectedItemId(previewFixtures[agentId].items[0]?.id ?? "");
  };

  const selectItem = (itemId: string) => {
    if (selectedFixture.items.some((item) => item.id === itemId)) {
      setSelectedItemId(itemId);
    }
  };

  return (
    <VuiProvider>
      <section className="memory-preview" aria-label="记忆阅读器隔离预览">
        <p className="memory-preview__notice" role="note">
          模拟数据：Agent、文件和正文均为本地示例；搜索与选择只更新预览状态，不会写入真实记忆。
        </p>
        <MemoryAgentMemoryPanel
          lang="zh"
          selectedAgentId={selectedAgentId}
          copy={copy}
          summary={{
            agentCount: previewAgents.length,
            privateFileCount: 2,
            privateByteText: "224 B",
            formalKnowledgeItemCount: 0,
            formalKnowledgeBaseCount: 0,
            warningCount: 0,
          }}
          searchText={searchText}
          onSearchTextChange={setSearchText}
          agents={visibleAgents}
          selectedAgent={selectedFixture.selectedAgent}
          selectedItem={selectedItem ? {
            title: selectedItem.title,
            path: selectedItem.path,
            sizeText: selectedItem.sizeText,
            contentType: selectedItem.contentType,
            contentLanguage: "zh",
            content: selectedItem.content || "",
          } : null}
          items={items}
          inventoryPending={false}
          inventoryErrorText=""
          detailPending={false}
          detailFetching={false}
          detailErrorText=""
          generatedAtText="模拟更新时间"
          onSelectAgent={selectAgent}
          onSelectItem={selectItem}
        />
      </section>
    </VuiProvider>
  );
}

function isPreviewAgentId(agentId: string): agentId is PreviewAgentId {
  return Object.hasOwn(previewFixtures, agentId);
}
