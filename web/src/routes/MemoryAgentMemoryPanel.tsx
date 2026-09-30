import { useState } from "react";
import { ArrowLeft, BookOpen, ChevronDown, ChevronRight, FileText, LockKeyhole, Search, ShieldCheck } from "lucide-react";
import { VButton, VDialog, VNativeInput, VSkeleton, VSplitWorkspace, VStateSurface } from "../components/vui";
import { WORKBENCH_LAYOUT_IDS } from "../components/layout/workbenchLayoutIds";
import { MemoryReadableBlocks } from "./MemoryContentBrowsePanel";
import { toReadableMemoryBlocks } from "./memory/memoryReadableContent";
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
  copy, searchText, onSearchTextChange, agents, selectedAgent, selectedItem, items,
  inventoryPending, inventoryErrorText, detailPending, detailFetching, detailErrorText,
  onSelectAgent,
}: MemoryAgentMemoryPanelProps) {
  const [showEmpty, setShowEmpty] = useState(false);
  const [showMobileAgents, setShowMobileAgents] = useState(false);
  const hasMemory = agents.filter((agent) => agent.hasPrivateMemory);
  const noMemory = agents.filter((agent) => !agent.hasPrivateMemory);
  const expanded = showEmpty || Boolean(searchText.trim());
  const chooseAgent = (id: string) => { onSelectAgent(id); setShowMobileAgents(false); };
  const avatar = (name: string) => name.trim().slice(0, 2).toUpperCase();
  const agentRows = (rows: MemoryAgentMemoryAgentView[]) => rows.map((agent) => (
    <VButton key={agent.id} variant="ghost" className={`${styles.agentRow} ${agent.active ? styles.agentRowActive : ""}`}
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
        <p className={styles.groupHeading}>{copy.groupHasMemory}<span>{hasMemory.length}</span></p>
        <div className={styles.agentList}>{agentRows(hasMemory)}</div>
        {!agents.length && !inventoryPending ? <p className={styles.emptyState}>{searchText.trim() ? copy.noMatches : copy.agentMemoryNoAgents}</p> : null}
        <VButton variant="ghost" className={styles.groupToggle} aria-expanded={expanded} onClick={() => setShowEmpty(!showEmpty)}>
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}<span>{copy.groupNoMemory}</span><span>{noMemory.length}</span>
        </VButton>
        {expanded ? <div className={styles.agentList}>{agentRows(noMemory)}</div> : null}
      </div>
      <p className={styles.railNote}><LockKeyhole size={14} />{copy.privateMemoryIsolationHint}</p>
    </div>
  );
  const detail = (
    <div className={styles.reader}>
      <div className={styles.readerTop}>
        <VButton variant="ghost" className={styles.mobileSwitch} onClick={() => setShowMobileAgents(true)}><ArrowLeft size={15} />{copy.privateMemorySwitchAgent}</VButton>
        <span className={styles.breadcrumb}>{copy.agentMemorySelectedAgent}<ChevronRight size={13} />{selectedAgent?.name || copy.agentMemorySelectPrompt}</span>
        <span className={styles.privateBadge}><LockKeyhole size={12} />{copy.privateMemoryLabel}</span>
      </div>
      <div className={styles.readingScroll} key={selectedAgent?.privateRoot || selectedAgent?.workspacePath || selectedAgent?.name} aria-busy={detailPending || detailFetching}>
        <div className={styles.readingContent}>
          {selectedAgent ? <header className={styles.agentTitle}><span className={styles.avatarLarge}>{avatar(selectedAgent.name)}</span><div><h2>{selectedAgent.name}</h2><p>{selectedAgent.fileCount} {copy.privateMemoryFileUnit}</p></div></header> : null}
          {detailErrorText ? <VStateSurface tone="error" title={copy.loadFailed}>{detailErrorText}</VStateSurface> : null}
          {detailPending ? <div aria-label={copy.loading} className="grid gap-5"><VSkeleton shape="line" /><VSkeleton shape="line" /><VSkeleton shape="line" /></div> : null}
          {!detailPending && !detailErrorText && selectedAgent ? <>
            <div className={styles.collectionHeading}><BookOpen size={16} /><span>{copy.privateMemoryAllFiles}</span><span>{items.length}</span></div>
            {items.length ? <div className={styles.documents}>{items.map((item) => (
              <article key={item.id} className={styles.document}>
                <div className={styles.documentKicker}><FileText size={15} /><span>{copy.agentMemoryPrivateFiles}</span><span>{item.updatedAtText}</span></div>
                <h3 className={styles.documentTitle}>{item.title}</h3>
                <div className={styles.documentBody}><MemoryReadableBlocks blocks={toReadableMemoryBlocks(item.content || (item.active ? selectedItem?.content : "") || item.summary)} emptyText={copy.noContent} /></div>
                {item.truncated ? <p className={styles.truncated}>{copy.truncated}</p> : null}
                <footer className={styles.documentFooter}><span title={item.path}>{item.path || item.title}</span><span>{item.sizeText}</span></footer>
              </article>
            ))}</div> : <VStateSurface title={copy.agentMemoryNoPrivateMemory} />}
            <p className={styles.readingNote}><ShieldCheck size={16} />{copy.privateMemoryReadingHint}</p>
          </> : null}
          {!selectedAgent && !detailPending ? <VStateSurface title={copy.agentMemorySelectPrompt} /> : null}
        </div>
      </div>
    </div>
  );
  return <div className={styles.agentMemoryWorkspace} data-vui-region="memory-agent-workspace">
    <VSplitWorkspace className={styles.workspace} resize={{layoutId: WORKBENCH_LAYOUT_IDS.memory, sidebar: {id: "agent-list", defaultWidth: 278, minWidth: 220, maxWidth: 380}}} sidebar={rail} main={detail} />
    <VDialog open={showMobileAgents} onOpenChange={setShowMobileAgents} title={copy.privateMemorySwitchAgent} size="sm" contentClassName={styles.mobileDialog}>{showMobileAgents ? rail : null}</VDialog>
  </div>;
}
