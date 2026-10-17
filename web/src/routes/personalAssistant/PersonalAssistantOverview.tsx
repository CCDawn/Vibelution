import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Bot, CheckCircle2, ChevronDown, CircleAlert, ListTodo, MessageSquare, RefreshCw, Search, Settings2, Wrench } from "lucide-react";
import { fetchPersonalAssistantOverview } from "../../api/personalAssistant";
import { queryKeys } from "../../api/queryKeys";
import { VButton, VDropdownMenu, VIconButton, VInput, VRouteLinkButton, VStateSurface, VTabs } from "../../components/vui";
import { assistantStatusLabel } from "./personalAssistantModel";
import styles from "./PersonalAssistantOverview.styles";

const shortcuts = [{ label: "智能体", to: "/agents", icon: Bot }, { label: "后台任务", to: "/aux", icon: ListTodo },
  { label: "配置", to: "/config", icon: Settings2 }, { label: "运行诊断", to: "/logs", icon: Wrench }];
const more = [{ label: "团队管理", to: "/teams" }, { label: "工具管理", to: "/agents/tools" },
  { label: "记忆管理", to: "/memory" }, { label: "知识管理", to: "/memory/knowledge" }];
type Tab = "attention" | "sessions" | "agents";
const PAGE_SIZE = 8;

export function PersonalAssistantOverview({ onOpenSession, desktop = false, showTitles = true, headerAction }: {
  onOpenSession: (sessionId: string) => void; desktop?: boolean; showTitles?: boolean; headerAction?: ReactNode;
}) {
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("attention");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [page, setPage] = useState(1);
  const overview = useQuery({ queryKey: queryKeys.personalAssistantOverview(), queryFn: ({ signal }) => fetchPersonalAssistantOverview({ signal }),
    refetchInterval: 5000, refetchIntervalInBackground: false, retry: 1 });
  const data = overview.data;
  function choose(id: string) { setTab(id as Tab); setSearch(""); setFilter("all"); setPage(1); }
  function selectStatus(value: string) { choose("sessions"); setFilter(value); }
  function sessionGroup(id: string, status: string) {
    if (data?.attention.some(row => row.sessionId === id && row.kind === "approval")) return "waiting";
    if (/approval|waiting/.test(status)) return "waiting";
    if (/failed|error|timeout/.test(status)) return "failed";
    if (["running", "thinking", "reading", "tooling", "answering", "verifying", "queued", "planning", "editing", "stopping"].includes(status)) return "running";
    return "idle";
  }
  const rows = !data ? [] : tab === "attention" ? data.attention.map((row, i) => ({ id: row.id,
    title: showTitles ? row.title : `事项 ${i + 1}`, status: row.kind === "approval" ? "等待确认" : "需要查看", sessionId: row.sessionId }))
    : tab === "agents" ? data.agents.map((row, i) => ({ id: row.id, title: showTitles ? row.displayName || row.id : `智能体 ${i + 1}`,
      status: assistantStatusLabel(row.status), sessionId: undefined }))
      : data.sessions.filter(row => filter === "all" || sessionGroup(row.id, row.currentPhase || row.status) === filter).map((row, i) => ({ id: row.id,
        title: showTitles ? row.title || "未命名会话" : `会话 ${i + 1}`, status: assistantStatusLabel(row.currentPhase || row.status), sessionId: row.id }));
  const filtered = rows.filter(row => row.title.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, pages);
  const visible = filtered.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);
  return <section className={styles.root} aria-label="平台概览">
    <div className={styles.pinned}>
      <header className={styles.header}><div><h2>平台概览</h2><p className={styles.updated}>{overview.isError ? "上次成功更新" : "更新于"} {data?.generatedAt ? new Date(data.generatedAt).toLocaleTimeString() : "—"}</p></div>
        <div className={styles.headerActions}><VIconButton variant="ghost" label="刷新平台概览" icon={<RefreshCw size={14} />}
          isPending={overview.isFetching} onClick={() => void overview.refetch()} />{headerAction}</div></header>
      {!desktop ? <><nav className={styles.shortcuts} aria-label="常用管理入口">{shortcuts.map(({ label, to, icon: Icon }) => <VRouteLinkButton key={to} to={to}
        variant="secondary" className={styles.shortcut}><Icon size={14} /><span>{label}</span><ArrowRight size={12} /></VRouteLinkButton>)}</nav>
        <div className={styles.more}><span>常用管理</span><VDropdownMenu aria-label="更多管理入口" align="end"
          trigger={<VButton variant="ghost" className={styles.moreButton} icon={<ChevronDown size={12} />}>更多管理</VButton>}
          items={more.map(row => ({ id: row.to, label: row.label, onSelect: () => navigate(row.to) }))} /></div></> : null}
      {data ? <div className={styles.statusStrip} aria-label="平台运行状态">{([
        ["running", "运行中", data.counts.running], ["waiting", "待确认", data.counts.waiting], ["failed", "异常", data.counts.failed],
      ] as const).map(([id, label, count]) => <VButton key={id} variant="ghost" contentLayout="plain" className={styles.status}
        onClick={() => selectStatus(id)}><i className={styles.dot} data-status={id} />{label} <strong>{count}</strong></VButton>)}</div> : null}
      <VTabs className={styles.tabs} value={tab} onValueChange={choose} aria-label="概览内容" items={[
        { id: "attention", label: `需关注 ${data?.attention.length ?? 0}` }, { id: "sessions", label: `会话 ${data?.counts.sessions ?? 0}` },
        { id: "agents", label: `智能体 ${data?.counts.agents ?? 0}` },
      ]} />
      {tab !== "attention" ? <div className={styles.controls}><div className={styles.search}><Search size={13} /><VInput aria-label={tab === "sessions" ? "搜索会话" : "搜索智能体"}
        placeholder={tab === "sessions" ? "搜索会话…" : "搜索智能体…"} value={search} onChange={event => { setSearch(event.target.value); setPage(1); }} /></div>
        {tab === "sessions" ? <VDropdownMenu aria-label="筛选会话状态" align="end" trigger={<VButton variant="ghost" className={styles.moreButton} icon={<ChevronDown size={12} />}>{({ all: "全部", running: "运行中", waiting: "待确认", failed: "异常" } as Record<string, string>)[filter]}</VButton>}
          items={[{ id: "all", label: "全部会话" }, { id: "running", label: "运行中" }, { id: "waiting", label: "待确认" }, { id: "failed", label: "异常" }].map(item => ({ ...item, onSelect: () => { setFilter(item.id); setPage(1); } }))} /> : null}</div> : null}
    </div>
    <div className={styles.content}>
      {overview.isError ? <VStateSurface density="compact" tone="error" title="平台状态读取失败">{overview.error.message}{data ? "；以下为上次成功读取的状态。" : ""}</VStateSurface> : null}
      {overview.isPending ? <VStateSurface density="compact" tone="loading" busy skeletonLines title="正在读取平台状态" /> : data ? <>
        {tab !== "attention" ? <p className={styles.summary}>{filtered.length} 项</p> : null}
        {visible.length ? <ul className={styles.list}>{visible.map(row => <li key={row.id}>{row.sessionId ? <VButton variant="ghost" contentLayout="plain" className={styles.row}
          onClick={() => onOpenSession(row.sessionId!)}>{tab === "attention" ? <CircleAlert size={15} /> : <MessageSquare size={14} />}<span className={styles.rowCopy}><strong title={row.title}>{row.title}</strong><span>{row.status}</span></span><ArrowRight size={13} /></VButton>
          : <div className={styles.agent}><Bot size={14} /><span className={styles.rowCopy}><strong title={row.title}>{row.title}</strong><span>{row.status}</span></span></div>}</li>)}</ul>
          : <div className={styles.empty}><CheckCircle2 size={23} /><strong>{tab === "attention" ? "当前没有待处理事项" : "没有匹配的结果"}</strong></div>}
        {pages > 1 ? <div className={styles.pagination}><span>第 {currentPage} / {pages} 页</span><div><VButton variant="ghost" isDisabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}>上一页</VButton><VButton variant="ghost" isDisabled={currentPage === pages} onClick={() => setPage(currentPage + 1)}>下一页</VButton></div></div> : null}
      </> : null}
    </div>
  </section>;
}
