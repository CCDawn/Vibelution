import { useEffect, useRef } from "react";
import styles from "./FinanceWorkspaceSidebar.styles";
import { Archive, ChevronDown, FileText, MessageSquare, Plus, Search, Settings2, TrendingUp, Wallet } from "lucide-react";
import type { SessionSummary } from "../../api/types";
import { VButton, VDropdownMenu, VInput, VRouteLinkButton, VSkeleton, VStateSurface } from "../../components/vui";
import { FinanceResearchHistory } from "./FinanceResearchHistory";
import type { FinanceSessionAction } from "./FinanceSessionMenu";
import { FINANCE_WORKSPACE_GROUPS, financeWorkspaceGroup } from "./financeWorkspaceNavigation";

export type FinanceSessionCollection = "recent" | "archived";
type Props = {
  records: SessionSummary[]; selectedId: string; zh: boolean; area: string;
  collection: FinanceSessionCollection; onCollectionChange: (value: FinanceSessionCollection) => void;
  search: string; onSearchChange: (value: string) => void;
  loading: boolean; error: boolean; hasMore: boolean; morePending: boolean;
  onRetry: () => void; onMore: () => void;
  creating: boolean; onNewResearch: () => void; configHref: string;
  onNavigate: (area: string) => void; onOpen: (record: SessionSummary) => void;
  onAction: (record: SessionSummary, action: FinanceSessionAction) => void; actionPending: boolean;
};
const groupIcons = { research: MessageSquare, market: TrendingUp, assets: Wallet, library: FileText };

export function FinanceWorkspaceSidebar(props: Props) {
  const { records, selectedId, zh, collection, search } = props;
  const listRef = useRef<HTMLDivElement>(null), lastSelection = useRef("");
  useEffect(() => {
    const key = `${collection}:${search}:${selectedId}`;
    const active = listRef.current?.querySelector<HTMLElement>('button[aria-pressed="true"]');
    if (active && lastSelection.current !== key) { active.scrollIntoView?.({ block: "nearest" }); lastSelection.current = key; }
  }, [collection, search, selectedId, records]);
  const now = new Date();
  const today = now.toDateString(), yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1).toDateString();
  const groups = [
    { id: "today", label: zh ? "今天" : "Today" },
    { id: "yesterday", label: zh ? "昨天" : "Yesterday" },
    { id: "earlier", label: zh ? "更早" : "Earlier" },
  ].map(group => ({ ...group, rows: records.filter(row => { const date = new Date(row.updatedAt).toDateString(); return (date === today ? "today" : date === yesterday ? "yesterday" : "earlier") === group.id; }) }));
  const activeGroup = financeWorkspaceGroup(props.area);
  return <div className={styles.root}>
    <div className={styles.controls}><VButton variant="secondary" className={styles.newResearch} icon={<Plus size={16} />} isPending={props.creating} onPress={props.onNewResearch}>{zh ? "新研究" : "New research"}</VButton><div className={styles.search}><Search className={styles.searchIcon} size={14} aria-hidden="true" /><VInput className={styles.searchInput} value={search} onChange={event => props.onSearchChange(event.target.value)} maxLength={200} aria-label={collection === "archived" ? (zh ? "搜索已加载归档会话" : "Search loaded archived sessions") : (zh ? "搜索研究会话" : "Search research sessions")} placeholder={zh ? "搜索会话" : "Search sessions"} /></div></div>
    <div className={styles.collection}><VDropdownMenu align="start" aria-label={zh ? "会话范围" : "Session collection"} trigger={<VButton variant="ghost" className={[styles.quiet, styles.collectionButton].join(" ")} icon={collection === "archived" ? <Archive size={13} /> : undefined} trailingIcon={<ChevronDown size={12} />}>{collection === "archived" ? (zh ? "已归档" : "Archived") : (zh ? "最近会话" : "Recent sessions")}</VButton>} items={[{ id: "recent", label: zh ? "最近会话" : "Recent sessions", onSelect: () => props.onCollectionChange("recent") }, { id: "archived", label: zh ? "已归档" : "Archived", icon: <Archive size={14} />, onSelect: () => props.onCollectionChange("archived") }]} /><span className={styles.count}>{records.length}</span></div>
    <div ref={listRef} className={styles.list} data-finance-session-scroll aria-label={zh ? "研究会话列表" : "Research session list"}>
      {props.error ? <VStateSurface density="compact" tone="error" title={zh ? "会话加载失败" : "Sessions unavailable"} actions={<VButton onPress={props.onRetry}>{zh ? "重试" : "Retry"}</VButton>} /> : props.loading ? <div className={styles.loading} aria-busy="true" aria-label={zh ? "正在查找会话" : "Searching sessions"}>{[0, 1, 2, 3, 4, 5].map(index => <VSkeleton key={index} className={styles.skeleton} />)}</div> : !records.length ? <VStateSurface density="compact" tone="empty" title={search ? (zh ? "没有匹配的会话" : "No matching sessions") : (zh ? "暂无会话" : "No sessions")} /> : groups.map(group => group.rows.length ? <section key={group.id} className={styles.section}><div className={styles.sectionLabel}>{group.label}</div><FinanceResearchHistory records={group.rows} compact selectedId={selectedId} zh={zh} onOpen={props.onOpen} onAction={props.onAction} actionPending={props.actionPending} /></section> : null)}
      {props.hasMore && !props.loading && !props.error ? <VButton variant="ghost" className={[styles.quiet, styles.more].join(" ")} isPending={props.morePending} onPress={props.onMore}>{zh ? "更多会话" : "More sessions"}</VButton> : null}
    </div>
    <footer className={styles.footer}><div className={styles.footerLabel}>{zh ? "工作台" : "Workspace"}</div><nav aria-label={zh ? "工作台功能分组" : "Workspace groups"} className={styles.groups}>{FINANCE_WORKSPACE_GROUPS.map(group => { const Icon = groupIcons[group.id]; return <VButton key={group.id} variant="ghost" className={[styles.groupButton, activeGroup.id === group.id ? styles.groupSelected : styles.quiet].join(" ")} icon={<Icon size={16} />} aria-pressed={activeGroup.id === group.id} onPress={() => props.onNavigate(group.areas[0].id)}>{zh ? group.zh : group.en}</VButton>; })}</nav><div className={styles.config}><VRouteLinkButton className={[styles.quiet, styles.configLink].join(" ")} to={props.configHref} aria-label={zh ? "模型与助手配置" : "Assistant settings"} title={zh ? "模型与助手配置" : "Assistant settings"}><Settings2 size={15} /></VRouteLinkButton></div></footer>
  </div>;
}
