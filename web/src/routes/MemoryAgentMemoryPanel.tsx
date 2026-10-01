import { useMemo, useState } from "react";
import { ArrowLeft, ChevronDown, ChevronRight, Search } from "lucide-react";
import { VButton, VDialog, VNativeInput, VSkeleton, VSplitWorkspace, VStateSurface, VStringSelect, VTabs } from "../components/vui";
import { WORKBENCH_LAYOUT_IDS } from "../components/layout/workbenchLayoutIds";
import { MemoryReadableBlocks } from "./MemoryContentBrowsePanel";
import { buildAgentMemoryReaderItems } from "./memory/agentMemoryReader";
import styles from "./MemoryAgentMemoryPanel.styles";

export type MemoryAgentMemorySummaryView = {
  agentCount: number;
  privateFileCount: number;
  privateByteText: string;
  formalKnowledgeItemCount: number;
  formalKnowledgeBaseCount: number;
  warningCount: number;
};

export type MemoryAgentMemoryAgentView = {
  id: string;
  name: string;
  status: string;
  origin: string;
  path: string;
  privateFileCount: number;
  formalKnowledgeBaseCount: number;
  hasPrivateMemory: boolean;
  primaryMode: string;
  active: boolean;
};

export type MemoryAgentMemoryItemView = {
  id: string;
  title: string;
  updatedAtText: string;
  path: string;
  summary: string;
  sizeText: string;
  contentType: string;
  truncated: boolean;
  active: boolean;
  content?: string;
};

export type MemoryAgentMemoryKnowledgeBaseView = {
  id: string;
  label: string;
  title: string;
};

export type MemoryAgentMemorySelectedAgentView = {
  name: string;
  privateRoot: string;
  workspacePath: string;
  fileCount: number;
  formalKnowledgeItemCount: number;
  formalKnowledgeBaseCount: number;
  knowledgeError?: string;
  knowledgeBases: MemoryAgentMemoryKnowledgeBaseView[];
};

export type MemoryAgentMemorySelectedItemView = {
  title: string;
  path: string;
  sizeText: string;
  contentType: string;
  contentLanguage: string;
  content: string;
};

export type MemoryAgentMemoryPanelCopy = {
  agentMemoryAgents: string;
  privateMemoryLabel: string;
  privateMemoryFileUnit: string;
  privateMemorySwitchAgent: string;
  privateMemoryReadingHint: string;
  privateMemoryIsolationHint: string;
  privateMemoryAllFiles: string;
  agentMemoryPrivateFiles: string;
  agentMemoryFormalKnowledge: string;
  agentMemoryFormalBases: string;
  warnings: string;
  agentMemorySelectedAgent: string;
  agentMemorySelectPrompt: string;
  searchPlaceholder: string;
  searchAgents: string;
  loading: string;
  loadFailed: string;
  agentMemoryNoAgents: string;
  agentMemoryPrivateRoot: string;
  sourcePath: string;
  agentMemoryNoPrivateMemory: string;
  truncated: string;
  agentMemorySelectedFile: string;
  agentMemoryNoFileSelected: string;
  noMatches: string;
  rawContent: string;
  noContent: string;
  generatedAt: string;
  browseBack: string;
  memoryCount: string;
  groupHasMemory: string;
  groupNoMemory: string;
  expandGroup: string;
  collapseGroup: string;
  groupChat: string;
  groupResearch: string;
  groupSelfEvolution: string;
  groupSupervised: string;
  groupGeneral: string;
  groupOther: string;
};

type MemoryAgentMemoryPanelProps = {
  lang?: "zh" | "en";
  selectedAgentId?: string;
  copy: MemoryAgentMemoryPanelCopy;
  summary: MemoryAgentMemorySummaryView;
  searchText: string;
  onSearchTextChange: (value: string) => void;
  agents: MemoryAgentMemoryAgentView[];
  selectedAgent: MemoryAgentMemorySelectedAgentView | null;
  selectedItem: MemoryAgentMemorySelectedItemView | null;
  items: MemoryAgentMemoryItemView[];
  inventoryPending: boolean;
  inventoryErrorText: string;
  detailPending: boolean;
  detailFetching: boolean;
  detailErrorText: string;
  generatedAtText: string;
  onSelectAgent: (agentId: string) => void;
  onSelectItem: (itemId: string) => void;
};

export function MemoryAgentMemoryPanel({
  lang = "zh", selectedAgentId, copy, searchText, onSearchTextChange, agents, selectedAgent, items,
  inventoryPending, inventoryErrorText, detailPending, detailFetching, detailErrorText,
  onSelectAgent, onSelectItem,
}: MemoryAgentMemoryPanelProps) {
  const [showEmpty, setShowEmpty] = useState(false);
  const [showMobileAgents, setShowMobileAgents] = useState(false);
  const hasMemory = agents.filter((agent) => agent.hasPrivateMemory);
  const noMemory = agents.filter((agent) => !agent.hasPrivateMemory);
  const expanded = showEmpty || Boolean(searchText.trim());
  const chooseAgent = (id: string) => { onSelectAgent(id); setShowMobileAgents(false); };
  const avatar = (name: string) => name.trim().slice(0, 2).toUpperCase();
  const agentRows = (rows: MemoryAgentMemoryAgentView[]) => rows.map((agent) => (
    <VButton contentLayout="plain" key={agent.id} variant="ghost" className={`${styles.agentRow} ${agent.active ? styles.agentRowActive : ""}`}
      aria-pressed={agent.active} onClick={() => chooseAgent(agent.id)}>
      <span className={styles.avatar}>{avatar(agent.name)}</span>
      <span className={styles.agentIdentity}><strong>{agent.name}</strong><small>{agent.privateFileCount} {copy.privateMemoryFileUnit}</small></span>
      {agent.active ? <span className={styles.selectedDot} /> : null}
    </VButton>
  ));
  const rail = (
    <div className={styles.agentRail}>
      <p className={styles.railHeading}>{copy.agentMemoryAgents}</p>
      <label className={styles.searchBox}><Search size={16} aria-hidden="true" />
        <VNativeInput aria-label={copy.searchAgents} placeholder={copy.searchAgents} value={searchText}
          onChange={(event) => onSearchTextChange(event.target.value)} />
      </label>
      <div className={styles.railScroll}>
        {inventoryErrorText ? <VStateSurface tone="error" title={copy.loadFailed}>{inventoryErrorText}</VStateSurface> : null}
        {inventoryPending && !agents.length ? <div aria-label={copy.loading}><VSkeleton shape="line" /><VSkeleton shape="line" /></div> : null}
        <p className={styles.groupHeading}>{lang === "zh" ? "有私有文件" : "With private files"}<span>{hasMemory.length}</span></p>
        <div className={styles.agentList}>{agentRows(hasMemory)}</div>
        {!agents.length && !inventoryPending ? <p className={styles.emptyState}>{searchText.trim() ? copy.noMatches : copy.agentMemoryNoAgents}</p> : null}
        <VButton contentLayout="plain" variant="ghost" className={styles.groupToggle} aria-expanded={expanded} onClick={() => setShowEmpty(!showEmpty)}>
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}<span>{copy.groupNoMemory}</span><span>{noMemory.length}</span>
        </VButton>
        {expanded ? <div className={styles.agentList}>{agentRows(noMemory)}</div> : null}
      </div>
    </div>
  );
  // Key by the selected owner, never by the filtered Agent rail. Search must not
  // unmount the current reader; changing owner must reset its filters and tabs.
  const ownerKey = selectedAgentId || selectedAgent?.privateRoot || selectedAgent?.workspacePath || selectedAgent?.name || "";
  const detail = <div className={styles.reader}>
    <VButton aria-label={copy.privateMemorySwitchAgent} contentLayout="plain" variant="ghost" className={styles.mobileSwitch} onClick={() => setShowMobileAgents(true)}>
      {selectedAgent?.name || copy.privateMemorySwitchAgent}<ChevronDown size={14} />
    </VButton>
    <AgentMemoryLibrary key={ownerKey} lang={lang} copy={copy} items={items} selectedAgent={selectedAgent}
      pending={detailPending} fetching={detailFetching} error={detailErrorText} onSelectItem={onSelectItem} />
  </div>;
  return <div className={styles.agentMemoryWorkspace} data-vui-region="memory-agent-workspace">
    <VSplitWorkspace className={styles.workspace} resize={{layoutId: WORKBENCH_LAYOUT_IDS.memory, sidebar: {id: "agent-list", defaultWidth: 220, minWidth: 180, maxWidth: 320}}} sidebar={rail} main={detail} />
    <VDialog open={showMobileAgents} onOpenChange={setShowMobileAgents} title={copy.privateMemorySwitchAgent} size="sm" contentClassName={styles.mobileDialog}>{showMobileAgents ? rail : null}</VDialog>
  </div>;
}

function AgentMemoryLibrary({ lang, copy, items, selectedAgent, pending, fetching, error, onSelectItem }: {
  lang: "zh" | "en"; copy: MemoryAgentMemoryPanelCopy; items: MemoryAgentMemoryItemView[];
  selectedAgent: MemoryAgentMemorySelectedAgentView | null; pending: boolean; fetching: boolean;
  error: string; onSelectItem: (id: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");
  const [mobileReading, setMobileReading] = useState(false);
  const text = readerCopy[lang];
  const records = useMemo(() => buildAgentMemoryReaderItems(items, lang), [items, lang]);
  const visible = records.filter((item) => (category === "all" || item.category === category)
    && [item.readerTitle, item.title, item.content, item.excerpt].join(" ").toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const item = visible.find((entry) => entry.active) ?? visible[0];
  const list = <section className={styles.library} aria-label={text.list}>
    <div className={styles.libraryControls}>
      <label className={styles.memorySearch}><Search size={15} aria-hidden="true" />
        <VNativeInput aria-label={text.search} placeholder={text.search} value={query} onChange={(event) => setQuery(event.target.value)} />
      </label>
      <VStringSelect ariaLabel={text.category} className={styles.category} value={category} onValueChange={setCategory}
        options={[{value: "all", label: text.all}, {value: "content", label: text.content}, {value: "initialization", label: text.initialization}]} />
    </div>
    <div className={styles.listScroll} aria-busy={pending || fetching}>
      {pending ? <div className={styles.loading} aria-label={copy.loading}><VSkeleton shape="line" /><VSkeleton shape="line" /></div>
        : error ? <VStateSurface tone="error" title={copy.loadFailed}>{error}</VStateSurface>
        : visible.map((entry) => <VButton contentLayout="plain" variant="ghost" key={entry.id}
          className={`${styles.memoryRow} ${entry.id === item?.id ? styles.memoryRowActive : ""}`}
          aria-pressed={entry.id === item?.id} onClick={() => { onSelectItem(entry.id); setMobileReading(true); }}>
          <span className={styles.rowMeta}><span>{entry.category === "initialization" ? text.initialization : text.content}</span><time>{entry.updatedAtText}</time></span>
          <strong className={styles.rowTitle}>{entry.readerTitle}</strong><span className={styles.rowExcerpt}>{entry.excerpt || copy.noContent}</span>
        </VButton>)}
      {!pending && !error && !visible.length ? <VStateSurface tone="empty" title={query.trim() || category !== "all" ? text.noMatches : copy.agentMemoryNoPrivateMemory} /> : null}
    </div>
  </section>;
  const detail = <section className={styles.reader} aria-label={text.read} aria-busy={pending || fetching}>
    <VButton contentLayout="plain" variant="ghost" className={styles.mobileBack} onClick={() => setMobileReading(false)}><ArrowLeft size={15} />{copy.browseBack}</VButton>
    {!pending && !error && item ? <MemoryRecord key={item.id} item={item} copy={copy} lang={lang} />
      : <div className={styles.emptyReader}><VStateSurface tone={error ? "error" : "empty"} title={pending ? copy.loading : error ? copy.loadFailed : selectedAgent ? (query.trim() || category !== "all" ? text.noMatches : copy.agentMemoryNoPrivateMemory) : copy.agentMemorySelectPrompt}>{error || undefined}</VStateSurface></div>}
  </section>;
  return <VSplitWorkspace className={`${styles.libraryWorkspace} ${mobileReading ? styles.mobileReading : styles.mobileListing}`}
    resize={{layoutId: WORKBENCH_LAYOUT_IDS.memory, sidebar: {id: "private-memory-list", defaultWidth: 300, minWidth: 240, maxWidth: 440}}}
    sidebar={list} main={detail} />;
}

function MemoryRecord({ item, copy, lang }: {
  item: ReturnType<typeof buildAgentMemoryReaderItems>[number]; copy: MemoryAgentMemoryPanelCopy; lang: "zh" | "en";
}) {
  const [tab, setTab] = useState("read");
  const [raw, setRaw] = useState(false);
  const text = readerCopy[lang];
  const heading = <header className={styles.documentHeader}>
    <h2 className={styles.documentTitle}>{item.readerTitle}</h2>
    <p className={styles.documentMeta}>{item.updatedAtText} · {item.sizeText}</p>
  </header>;
  const body = <article className={styles.readingContent}>{heading}
    {item.category === "initialization" ? <p className={styles.notice}>{text.initializationHint}</p> : null}
    <div className={styles.documentBody}><MemoryReadableBlocks blocks={item.blocks} emptyText={copy.noContent} /></div>
    {item.truncated ? <p className={styles.notice}>{copy.truncated}</p> : null}
  </article>;
  const sources = <article className={styles.readingContent}>{heading}
    <dl className={styles.sourceFields}><dt>{copy.sourcePath}</dt><dd>{item.path || item.title}</dd><dt>{text.format}</dt><dd>{item.contentType || "—"}</dd></dl>
    <p className={styles.notice}>{text.noHistory}</p>
    <VButton variant="secondary" aria-expanded={raw} onClick={() => setRaw(!raw)}>{raw ? text.hideRaw : copy.rawContent}</VButton>
    {raw ? <pre className={styles.raw}>{item.content || copy.noContent}</pre> : null}
    {item.truncated ? <p className={styles.notice}>{copy.truncated}</p> : null}
  </article>;
  const usage = <article className={styles.readingContent}>{heading}<VStateSurface tone="empty" title={text.noUsage}>{text.noUsageHint}</VStateSurface></article>;
  return <VTabs className={styles.tabs} listClassName={styles.tabList} triggerClassName={styles.tabTrigger} contentClassName={styles.tabContent}
    aria-label={text.view} value={tab} onValueChange={setTab}
    items={[{id: "read", label: text.read, content: body}, {id: "sources", label: text.sources, content: sources}, {id: "usage", label: text.usage, content: usage}]} />;
}

const readerCopy = {
  zh: {
    list: "记忆列表", search: "搜索记忆正文", category: "记录类型", all: "全部", content: "记忆文件", initialization: "初始化",
    read: "正文", sources: "来源与变化", usage: "对话使用记录", view: "记忆查看方式", noMatches: "没有匹配的记忆", format: "文件格式",
    initializationHint: "这是初始化记录，尚未积累有效记忆。", noHistory: "当前接口只提供文件快照，未提供来源会话或修改历史。文件更新时间不代表记忆形成时间。",
    hideRaw: "收起原始记录", noUsage: "暂未提供使用证据", noUsageHint: "当前接口不提供检索或上下文引用记录，无法据此判断使用情况。保存过不等于在对话中使用过。",
  },
  en: {
    list: "Memory list", search: "Search memory content", category: "Record type", all: "All", content: "Memory file", initialization: "Initial state",
    read: "Content", sources: "Sources & changes", usage: "Conversation usage", view: "Memory view", noMatches: "No matching memories", format: "File format",
    initializationHint: "This is an initialization record, not accumulated memory.", noHistory: "The API provides a file snapshot, not source conversations or revision history. File modification time is not memory formation time.",
    hideRaw: "Hide raw record", noUsage: "Usage evidence unavailable", noUsageHint: "The API does not provide retrieval or context-reference records, so usage cannot be determined. Stored does not mean used in a conversation.",
  },
} as const;
