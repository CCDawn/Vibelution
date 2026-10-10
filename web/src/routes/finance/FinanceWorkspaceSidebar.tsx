import { useEffect, useRef, useState } from "react";
import styles from "./FinanceWorkspaceSidebar.styles";
import { Archive, ArchiveRestore, ChevronDown, FileText, MessageSquare, PanelLeftClose, Plus, Search, Settings2, Trash2, TrendingUp, Wallet } from "lucide-react";
import type { SessionSummary } from "../../api/types";
import { VButton, VCheckbox, VDropdownMenu, VIconButton, VInput, VRouteLinkButton, VSkeleton, VStateSurface } from "../../components/vui";
import { FinanceResearchHistory } from "./FinanceResearchHistory";
import type { FinanceSessionAction } from "./FinanceSessionMenu";
import { researchRecordStatus } from "./stockResearchModel";
import { FINANCE_WORKSPACE_GROUPS, financeWorkspaceGroup } from "./financeWorkspaceNavigation";

export type FinanceSessionCollection = "recent" | "archived";
type Props = {
  records: SessionSummary[]; selectedId: string; zh: boolean; area: string;
  collection: FinanceSessionCollection; onCollectionChange: (value: FinanceSessionCollection) => void;
  search: string; onSearchChange: (value: string) => void;
  loading: boolean; error: boolean; hasMore: boolean; morePending: boolean;
  onRetry: () => void; onMore: () => void;
  creating: boolean; onNewResearch: () => void; configHref: string; onCollapse?: () => void;
  onNavigate: (area: string) => void; onOpen: (record: SessionSummary) => void;
  onAction: (record: SessionSummary, action: FinanceSessionAction) => void; actionPending: boolean;
  onBatchAction?: (records: SessionSummary[], action: FinanceSessionAction, returnFocus?: HTMLElement | null) => void;
  actionError?: string; actionNotice?: string; canUndoBatchArchive?: boolean; onUndoBatchArchive?: () => void;
};
const groupIcons = { research: MessageSquare, market: TrendingUp, assets: Wallet, library: FileText };

export function FinanceWorkspaceSidebar(props: Props) {
  const { records, selectedId, zh, collection, search } = props;
  const [managing, setManaging] = useState(false), [selectedIds, setSelectedIds] = useState<string[]>([]);
  const listRef = useRef<HTMLDivElement>(null), lastSelection = useRef("");
  useEffect(() => {
    const key = `${collection}:${search}:${selectedId}`;
    const active = listRef.current?.querySelector<HTMLElement>('button[aria-pressed="true"]');
    if (active && lastSelection.current !== key) { active.scrollIntoView?.({ block: "nearest" }); lastSelection.current = key; }
  }, [collection, search, selectedId, records]);
  useEffect(() => { setSelectedIds([]); }, [collection, search]);
  useEffect(() => { setSelectedIds(ids => { const retained = ids.filter(id => records.some(row => row.id === id)); return retained.length === ids.length ? ids : retained; }); }, [records]);
  const selected = records.filter(row => selectedIds.includes(row.id));
  const allSelected = records.length > 0 && selected.length === records.length;
  const now = new Date();
  const today = now.toDateString(), yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1).toDateString();
  const groups = [
    { id: "today", label: zh ? "今天" : "Today" },
    { id: "yesterday", label: zh ? "昨天" : "Yesterday" },
    { id: "earlier", label: zh ? "更早" : "Earlier" },
  ].map(group => ({ ...group, rows: records.filter(row => { const date = new Date(row.updatedAt).toDateString(); return (date === today ? "today" : date === yesterday ? "yesterday" : "earlier") === group.id; }) }));
  const activeGroup = financeWorkspaceGroup(props.area);
  const batchDisabled = !selected.length || props.actionPending || props.loading || props.error;
  return <div className={styles.root}>
    <nav aria-label={zh ? "工作台功能分组" : "Workspace groups"} className={styles.rail}>
      {FINANCE_WORKSPACE_GROUPS.map(group => { const Icon = groupIcons[group.id]; return <VButton key={group.id} variant="ghost" className={[styles.groupButton, activeGroup.id === group.id ? styles.groupSelected : styles.quiet].join(" ")} icon={<Icon size={17} />} aria-label={zh ? group.zh : group.en} title={zh ? group.zh : group.en} aria-pressed={activeGroup.id === group.id} onPress={() => props.onNavigate(group.areas[0].id)} />; })}
      <VRouteLinkButton className={[styles.quiet, styles.configLink].join(" ")} to={props.configHref} aria-label={zh ? "模型与助手配置" : "Assistant settings"} title={zh ? "模型与助手配置" : "Assistant settings"}><Settings2 size={16} /></VRouteLinkButton>
    </nav>
    <div className={styles.sessions}>
      <div className={styles.heading}><strong className={styles.title}>{zh ? "会话" : "Sessions"}</strong><VButton variant="ghost" className={styles.newResearch} icon={<Plus size={14} />} isPending={props.creating} onPress={props.onNewResearch}>{zh ? "新研究" : "New"}</VButton>{props.onCollapse ? <VIconButton variant="ghost" className={styles.iconButton} label={zh ? "收起会话栏" : "Collapse sessions"} icon={<PanelLeftClose size={16} />} onPress={props.onCollapse} /> : null}</div>
      <div className={styles.controls}><div className={styles.search}><Search className={styles.searchIcon} size={14} aria-hidden="true" /><VInput className={styles.searchInput} value={search} onChange={event => props.onSearchChange(event.target.value)} maxLength={200} aria-label={collection === "archived" ? (zh ? "搜索已加载归档会话" : "Search loaded archived sessions") : (zh ? "搜索研究会话" : "Search research sessions")} placeholder={zh ? "搜索会话" : "Search sessions"} /></div>{props.onBatchAction ? <VButton variant="ghost" className={styles.manage} aria-pressed={managing} isDisabled={props.actionPending} onPress={() => { setManaging(!managing); setSelectedIds([]); }}>{managing ? (zh ? "完成" : "Done") : (zh ? "管理" : "Manage")}</VButton> : null}</div>
      <div className={styles.collection}><VDropdownMenu align="start" aria-label={zh ? "会话范围" : "Session collection"} trigger={<VButton variant="ghost" className={[styles.quiet, styles.collectionButton].join(" ")} icon={collection === "archived" ? <Archive size={13} /> : undefined} trailingIcon={<ChevronDown size={12} />}>{collection === "archived" ? (zh ? "已归档" : "Archived") : (zh ? "最近会话" : "Recent sessions")}</VButton>} items={[{ id: "recent", label: zh ? "最近会话" : "Recent sessions", onSelect: () => props.onCollectionChange("recent") }, { id: "archived", label: zh ? "已归档" : "Archived", icon: <Archive size={14} />, onSelect: () => props.onCollectionChange("archived") }]} /><span className={styles.count}>{records.length}</span></div>
      <div ref={listRef} className={styles.list} data-finance-session-scroll aria-label={zh ? "研究会话列表" : "Research session list"}>
        {props.error ? <VStateSurface density="compact" tone="error" title={zh ? "会话加载失败" : "Sessions unavailable"} actions={<VButton onPress={props.onRetry}>{zh ? "重试" : "Retry"}</VButton>} /> : props.loading ? <div className={styles.loading} aria-busy="true" aria-label={zh ? "正在查找会话" : "Searching sessions"}>{[0, 1, 2, 3, 4, 5].map(index => <VSkeleton key={index} className={styles.skeleton} />)}</div> : !records.length ? <VStateSurface density="compact" tone="empty" title={search ? (zh ? "没有匹配的会话" : "No matching sessions") : (zh ? "暂无会话" : "No sessions")} /> : groups.map(group => group.rows.length ? <section key={group.id} className={styles.section}><div className={styles.sectionLabel}>{group.label}</div><div className={styles.rows}>{group.rows.map(row => <div key={row.id} className={styles.row}>
          {managing ? <VCheckbox aria-label={zh ? `选择研究：${row.title || "研究会话"}` : `Select research: ${row.title || "Research"}`} isSelected={selectedIds.includes(row.id)} isDisabled={props.actionPending} onChange={checked => setSelectedIds(ids => checked ? [...ids, row.id] : ids.filter(id => id !== row.id))} /> : null}
          <div className={styles.history}><FinanceResearchHistory records={[row]} compact selectedId={selectedId} zh={zh} onOpen={props.onOpen} onAction={managing ? undefined : props.onAction} actionPending={props.actionPending} /></div>
          {!managing && row.id === selectedId ? <VIconButton variant="ghost" className={styles.deleteButton} label={zh ? "删除当前研究" : "Delete current research"} icon={<Trash2 size={13} />} isDisabled={props.actionPending || ["Running", "Stopping"].includes(researchRecordStatus(row, false))} onPress={() => props.onAction(row, "delete")} /> : null}
        </div>)}</div></section> : null)}
        {props.hasMore && !props.loading && !props.error ? <VButton variant="ghost" className={[styles.quiet, styles.more].join(" ")} isPending={props.morePending} onPress={props.onMore}>{zh ? "更多会话" : "More sessions"}</VButton> : null}
      </div>
      {props.actionError || props.actionNotice || props.canUndoBatchArchive ? <div className={styles.feedback}>
        {props.actionError ? <div role="alert" className={styles.error} title={props.actionError}>{props.actionError}</div> : null}
        {props.actionNotice || props.canUndoBatchArchive ? <div className={styles.notice}><span role="status" title={props.actionNotice}>{props.actionNotice}</span>{props.canUndoBatchArchive ? <VButton variant="ghost" className={styles.undo} isDisabled={props.actionPending} onPress={props.onUndoBatchArchive}>{zh ? "撤销" : "Undo"}</VButton> : null}</div> : null}
      </div> : null}
      {managing ? <footer className={styles.batch} aria-label={zh ? "批量会话操作" : "Batch session actions"}>
        <VCheckbox aria-label={zh ? "全选当前列表" : "Select all loaded sessions"} isSelected={allSelected} isDisabled={props.actionPending || props.loading || props.error || !records.length} onChange={checked => setSelectedIds(checked ? records.map(row => row.id) : [])}>{zh ? "全选" : "All"}</VCheckbox><span className={styles.selectedCount} title={zh ? `已选择 ${selected.length} 条研究` : `${selected.length} selected`}>{selected.length}</span>
        <VIconButton variant="ghost" className={styles.batchButton} label={collection === "archived" ? (zh ? "恢复所选研究" : "Restore selected research") : (zh ? "归档所选研究" : "Archive selected research")} icon={collection === "archived" ? <ArchiveRestore size={15} /> : <Archive size={15} />} isDisabled={batchDisabled} onPress={() => props.onBatchAction?.(selected, collection === "archived" ? "restore" : "archive")} />
        <VIconButton variant="ghost" className={styles.batchButton} label={zh ? "删除所选研究" : "Delete selected research"} icon={<Trash2 size={15} />} isDisabled={batchDisabled} onPress={() => props.onBatchAction?.(selected, "delete", document.activeElement instanceof HTMLElement ? document.activeElement : null)} />
      </footer> : null}
    </div>
  </div>;
}
