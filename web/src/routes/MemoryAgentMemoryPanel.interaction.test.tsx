/** @vitest-environment happy-dom */
import React, { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { VuiProvider } from "../components/vui";
import { MemoryAgentMemoryPanel, type MemoryAgentMemoryPanelCopy } from "./MemoryAgentMemoryPanel";

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

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("MemoryAgentMemoryPanel interaction", () => {
  let container: HTMLDivElement | null = null;
  let root: Root | null = null;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    if (root) {
      await act(async () => root?.unmount());
    }
    container?.remove();
    root = null;
    container = null;
    document.body.querySelectorAll('[role="dialog"]').forEach((dialog) => dialog.remove());
  });

  it("keeps Agents without memory collapsed until their group is expanded", async () => {
    const host = await mount(<MemoryAgentMemoryPanel {...baseProps} />, container!, root!);

    expect(host.textContent).toContain("Alpha Agent");
    expect(host.textContent).not.toContain("Empty Agent");
    const groupToggle = buttonContaining(host, copy.groupNoMemory);
    expect(groupToggle?.getAttribute("aria-expanded")).toBe("false");

    await act(async () => groupToggle?.click());

    expect(buttonContaining(host, "Empty Agent")).not.toBeNull();
    expect(buttonContaining(host, copy.groupNoMemory)?.getAttribute("aria-expanded")).toBe("true");
  });

  it("keeps the selected memory readable while search filters the Agent list", async () => {
    const onSelectAgent = vi.fn();
    const host = await mount(<SearchHarness onSelectAgent={onSelectAgent} />, container!, root!);
    const search = host.querySelector<HTMLInputElement>('input[aria-label="搜索 Agent"]');
    expect(search).not.toBeNull();

    await act(async () => setInputValue(search!, "Beta"));

    expect(buttonContaining(host, "Beta Agent")).not.toBeNull();
    expect(host.querySelector('button[aria-pressed="true"]')?.textContent).not.toContain("Alpha Agent");
    expect(host.querySelector('[role="tabpanel"] h2')?.textContent).toContain("Alpha Agent");
    expect(host.querySelector('[role="tabpanel"] h2')?.textContent).toContain("preferences.md");
    expect(host.textContent).toContain("Alpha saved memory body");
    expect(onSelectAgent).not.toHaveBeenCalled();
  });

  it("opens the Agent switcher on narrow layouts and closes it after selection", async () => {
    const onSelectAgent = vi.fn();
    const host = await mount(<MemoryAgentMemoryPanel {...baseProps} onSelectAgent={onSelectAgent} />, container!, root!);

    await act(async () => host.querySelector<HTMLButtonElement>('button[aria-label="切换 Agent"]')?.click());

    const dialog = document.body.querySelector<HTMLElement>('[role="dialog"]');
    expect(dialog).not.toBeNull();
    const beta = buttonContaining(dialog!, "Beta Agent");
    expect(beta).not.toBeNull();

    await act(async () => beta?.click());

    expect(onSelectAgent).toHaveBeenCalledWith("agent-beta");
    expect(document.body.querySelector('[role="dialog"]')).toBeNull();
  });

  it("searches full memory content and dispatches item selection", async () => {
    const onSelectItem = vi.fn();
    const second = { ...baseProps.items[0], id: "second", title: "other.md", active: false, content: "Unique needle deep in the file" };
    const host = await mount(<MemoryAgentMemoryPanel {...baseProps} items={[...baseProps.items, second]} onSelectItem={onSelectItem} />, container!, root!);
    const search = host.querySelector<HTMLInputElement>('input[aria-label="搜索记忆正文"]')!;
    await act(async () => setInputValue(search, "needle"));
    expect(buttonContaining(host, "preferences.md")).toBeNull();
    expect(host.querySelector('[role="tabpanel"]')?.textContent).toContain("Unique needle");
    await act(async () => buttonContaining(host, "other.md")?.click());
    expect(onSelectItem).toHaveBeenCalledWith("second");
    await act(async () => setInputValue(search, "absent"));
    expect(host.textContent).toContain("没有匹配的记忆");
    expect(host.querySelector('[role="tabpanel"]')).toBeNull();
  });

  it("does not invent source history or usage and escapes raw content", async () => {
    const content = '<img src=x onerror="alert(1)">';
    const host = await mount(<MemoryAgentMemoryPanel {...baseProps} items={[{...baseProps.items[0], content}]} />, container!, root!);
    await selectTab(host, "来源与变化");
    expect(host.textContent).toContain("未提供来源会话或修改历史");
    await act(async () => buttonContaining(host, copy.rawContent)?.click());
    expect(host.querySelector("pre")?.textContent).toBe(content);
    expect(host.querySelector("img")).toBeNull();
    await selectTab(host, "对话使用记录");
    expect(host.textContent).toContain("暂未提供使用证据");
    expect(host.textContent).not.toContain("最近一次使用");
  });

  it("clears filters, tab and raw expansion when the selected owner changes", async () => {
    const host = await mount(<MemoryAgentMemoryPanel {...baseProps} />, container!, root!);
    expect(host.querySelector('[role="tabpanel"] h2')?.textContent).toContain("Alpha Agent");
    await act(async () => setInputValue(host.querySelector<HTMLInputElement>('input[aria-label="搜索记忆正文"]')!, "Alpha"));
    await selectTab(host, "来源与变化");
    await act(async () => buttonContaining(host, copy.rawContent)?.click());
    await mount(<MemoryAgentMemoryPanel {...baseProps} selectedAgentId="agent-beta" selectedAgent={{...baseProps.selectedAgent!, name: "Beta Agent", privateRoot: "C:/beta"}}
      items={[{...baseProps.items[0], id: "beta", content: "Beta only"}]} />, container!, root!);
    expect(host.querySelector<HTMLInputElement>('input[aria-label="搜索记忆正文"]')?.value).toBe("");
    expect(host.querySelector('[role="tab"][aria-selected="true"]')?.textContent).toBe("正文");
    expect(host.querySelector("pre")).toBeNull();
    expect(host.textContent).not.toContain("Alpha saved memory body");
    expect(host.textContent).toContain("Beta only");
    expect(host.querySelector('[role="tabpanel"] h2')?.textContent).toContain("Beta Agent");
    expect(host.querySelector('[role="tabpanel"] h2')?.textContent).not.toContain("Alpha Agent");
  });

  it("hides stale body and owner during loading, failed, or unselected detail reads", async () => {
    const host = await mount(<MemoryAgentMemoryPanel {...baseProps} detailPending />, container!, root!);
    expect(host.textContent).not.toContain("Alpha saved memory body");
    expect(host.querySelector('[role="tabpanel"] h2')).toBeNull();
    await mount(<MemoryAgentMemoryPanel {...baseProps} detailErrorText="Access denied" />, container!, root!);
    expect(host.textContent).toContain("Access denied");
    expect(host.textContent).not.toContain("Alpha saved memory body");
    expect(host.querySelector('[role="tabpanel"] h2')).toBeNull();

    await mount(<MemoryAgentMemoryPanel {...baseProps} selectedAgent={null} selectedItem={null} items={[]} />, container!, root!);
    expect(host.querySelector('[role="tabpanel"] h2')).toBeNull();
  });
});

async function selectTab(host: ParentNode, label: string) {
  const tab = Array.from(host.querySelectorAll<HTMLElement>('[role="tab"]')).find((node) => node.textContent === label)!;
  await act(async () => tab.focus());
}

function SearchHarness({ onSelectAgent }: { onSelectAgent: (agentId: string) => void }) {
  const [searchText, setSearchText] = useState("");
  const visibleAgents = agents.filter((agent) => agent.name.toLowerCase().includes(searchText.trim().toLowerCase()));
  return (
    <MemoryAgentMemoryPanel
      {...baseProps}
      searchText={searchText}
      onSearchTextChange={setSearchText}
      agents={visibleAgents}
      onSelectAgent={onSelectAgent}
    />
  );
}

async function mount(node: React.ReactNode, host: HTMLDivElement, mountedRoot: Root): Promise<HTMLDivElement> {
  await act(async () => {
    mountedRoot.render(<VuiProvider>{node}</VuiProvider>);
  });
  return host;
}

function buttonContaining(host: ParentNode, text: string): HTMLButtonElement | null {
  return Array.from(host.querySelectorAll<HTMLButtonElement>("button"))
    .find((button) => button.textContent?.includes(text)) ?? null;
}

function setInputValue(element: HTMLInputElement, value: string) {
  const valueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  valueSetter?.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
}
