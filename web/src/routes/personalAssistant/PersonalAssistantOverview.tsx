import { resolveSessionActivity, sessionActivityGroup, sessionActivityStatusLabel, type SessionActivitySource } from "../sessionActivityState";
import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRight, Bot, CheckCircle2, ChevronDown, CircleAlert, ListTodo, MessageSquare, RefreshCw, Search, Settings2, Wrench } from "lucide-react";
import { fetchPersonalAssistantOverview } from "../../api/personalAssistant";
import { queryKeys } from "../../api/queryKeys";
import { VButton, VDropdownMenu, VIconButton, VInput, VRouteLinkButton, VStateSurface, VTabs } from "../../components/vui";
import { useShellI18n } from "../../i18n/useShellI18n";
import { PERSONAL_ASSISTANT_COPY } from "./personalAssistantCopy";
import { assistantStatusLabel } from "./personalAssistantModel";
import styles from "./PersonalAssistantOverview.styles";

type Tab = "attention" | "sessions" | "agents";
const PAGE_SIZE = 8;

export function PersonalAssistantOverview({ onOpenSession, desktop = false, showTitles = true, headerAction }: {
  onOpenSession: (sessionId: string) => void; desktop?: boolean; showTitles?: boolean; headerAction?: ReactNode;
}) {
  const navigate = useNavigate();
  const { lang } = useShellI18n();
  const copy = PERSONAL_ASSISTANT_COPY[lang];
  const shortcuts = [{ label: copy.agents, to: "/agents", icon: Bot }, { label: copy.backgroundTasks, to: "/aux", icon: ListTodo },
    { label: copy.config, to: "/config", icon: Settings2 }, { label: copy.diagnostics, to: "/logs", icon: Wrench }];
  const more = [{ label: copy.teams, to: "/teams" }, { label: copy.tools, to: "/agents/tools" },
    { label: copy.memory, to: "/memory" }, { label: copy.knowledge, to: "/memory/knowledge" }];
  const [tab, setTab] = useState<Tab>("attention");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [page, setPage] = useState(1);
  const overview = useQuery({ queryKey: queryKeys.personalAssistantOverview(), queryFn: ({ signal }) => fetchPersonalAssistantOverview({ signal }),
    refetchInterval: 5000, refetchIntervalInBackground: false, retry: 1 });
  const data = overview.data;
  function choose(id: string) { setTab(id as Tab); setSearch(""); setFilter("all"); setPage(1); }
  function selectStatus(value: string) { choose("sessions"); setFilter(value); }
  function sessionGroup(row: SessionActivitySource & { id: string }) {
    return sessionActivityGroup(row, Boolean(data?.attention.some(item => item.sessionId === row.id && item.kind === "approval")));
  }
  // 会话派生 attention 行 + 独立 humanAttention 通道（复核停靠/异常升级）合并展示。
  const attentionRows = data ? [...data.attention, ...(data.humanAttention ?? [])] : [];
  const rows = !data ? [] : tab === "attention" ? attentionRows.map((row, i) => ({ id: row.id,
    title: showTitles ? row.title : copy.item(i + 1), status: row.kind === "approval" ? copy.waitingConfirmation : copy.needsReview, sessionId: row.sessionId, targetUrl: row.targetUrl }))
    : tab === "agents" ? data.agents.map((row, i) => ({ id: row.id, title: showTitles ? row.displayName || row.id : copy.agent(i + 1),
      status: assistantStatusLabel(row.status, lang), sessionId: undefined, targetUrl: undefined }))
      : data.sessions.filter(row => filter === "all" || sessionGroup(row) === filter).map((row, i) => ({ id: row.id,
        title: showTitles ? row.title || copy.untitledSession : copy.session(i + 1), status: sessionActivityStatusLabel(resolveSessionActivity(row), lang), sessionId: row.id, targetUrl: undefined }));
  const filtered = rows.filter(row => row.title.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, pages);
  const visible = filtered.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);
  return <section className={styles.root} aria-label={copy.overview}>
    <div className={styles.pinned}>
      <header className={styles.header}><div><h2>{copy.overview}</h2><p className={styles.updated}>{overview.isError ? copy.lastUpdated : copy.updated} {data?.generatedAt ? new Date(data.generatedAt).toLocaleTimeString(lang === "zh" ? "zh-CN" : "en-US") : "—"}</p></div>
        <div className={styles.headerActions}><VIconButton variant="ghost" label={copy.refreshOverview} icon={<RefreshCw size={14} />}
          isPending={overview.isFetching} onClick={() => void overview.refetch()} />{headerAction}</div></header>
      {!desktop ? <><nav className={styles.shortcuts} aria-label={copy.shortcuts}>{shortcuts.map(({ label, to, icon: Icon }) => <VRouteLinkButton key={to} to={to}
        variant="secondary" className={styles.shortcut} icon={<Icon size={14} />} trailingIcon={<ArrowRight size={12} />}>{label}</VRouteLinkButton>)}</nav>
        <div className={styles.more}><span>{copy.management}</span><VDropdownMenu aria-label={copy.moreManagement} align="end"
          trigger={<VButton variant="ghost" className={styles.moreButton} icon={<ChevronDown size={12} />}>{copy.moreManagement}</VButton>}
          items={more.map(row => ({ id: row.to, label: row.label, onSelect: () => navigate(row.to) }))} /></div></> : null}
      {data ? <div className={styles.statusStrip} aria-label={copy.platformStatus}>{([
        ["running", copy.running, data.counts.running], ["waiting", copy.waiting, data.counts.waiting], ["failed", copy.failed, data.counts.failed],
      ] as const).map(([id, label, count]) => <VButton key={id} variant="ghost" contentLayout="plain" className={styles.status}
        onClick={() => selectStatus(id)}><i className={styles.dot} data-status={id} />{label} <strong>{count}</strong></VButton>)}</div> : null}
      <VTabs className={styles.tabs} value={tab} onValueChange={choose} aria-label={copy.overviewContents} items={[
        { id: "attention", label: copy.attentionTab(data ? attentionRows.length : 0) }, { id: "sessions", label: copy.sessionsTab(data?.counts.sessions ?? 0) },
        { id: "agents", label: copy.agentsTab(data?.counts.agents ?? 0) },
      ]} />
      {tab !== "attention" ? <div className={styles.controls}><div className={styles.search}><Search size={13} /><VInput aria-label={tab === "sessions" ? copy.searchSessions : copy.searchAgents}
        placeholder={tab === "sessions" ? copy.searchSessionsPlaceholder : copy.searchAgentsPlaceholder} value={search} onChange={event => { setSearch(event.target.value); setPage(1); }} /></div>
        {tab === "sessions" ? <VDropdownMenu aria-label={copy.filterStatus} align="end" trigger={<VButton variant="ghost" className={styles.moreButton} icon={<ChevronDown size={12} />}>{({ all: copy.all, running: copy.running, waiting: copy.waiting, failed: copy.failed } as Record<string, string>)[filter]}</VButton>}
          items={[{ id: "all", label: copy.allSessions }, { id: "running", label: copy.running }, { id: "waiting", label: copy.waiting }, { id: "failed", label: copy.failed }].map(item => ({ ...item, onSelect: () => { setFilter(item.id); setPage(1); } }))} /> : null}</div> : null}
    </div>
    <div className={styles.content}>
      {overview.isError ? <VStateSurface density="compact" tone="error" title={copy.readFailed}>{overview.error.message}{data ? copy.staleNotice : ""}</VStateSurface> : null}
      {overview.isPending ? <VStateSurface density="compact" tone="loading" busy skeletonLines title={copy.loading} /> : data ? <>
        {tab !== "attention" ? <p className={styles.summary}>{copy.itemCount(filtered.length)}</p> : null}
        {visible.length ? <ul className={styles.list}>{visible.map(row => <li key={row.id}>{row.sessionId ? <VButton variant="ghost" contentLayout="plain" className={styles.row}
          onClick={() => onOpenSession(row.sessionId!)}>{tab === "attention" ? <CircleAlert size={15} /> : <MessageSquare size={14} />}<span className={styles.rowCopy}><strong title={row.title}>{row.title}</strong><span>{row.status}</span></span><ArrowRight size={13} /></VButton>
          : row.targetUrl ? <VButton variant="ghost" contentLayout="plain" className={styles.row}
          onClick={() => navigate(row.targetUrl!)}><CircleAlert size={15} /><span className={styles.rowCopy}><strong title={row.title}>{row.title}</strong><span>{row.status}</span></span><ArrowRight size={13} /></VButton>
          : <div className={styles.agent}><Bot size={14} /><span className={styles.rowCopy}><strong title={row.title}>{row.title}</strong><span>{row.status}</span></span></div>}</li>)}</ul>
          : <div className={styles.empty}><CheckCircle2 size={23} /><strong>{tab === "attention" ? copy.nothingPending : copy.noMatches}</strong></div>}
        {pages > 1 ? <div className={styles.pagination}><span>{copy.page(currentPage, pages)}</span><div><VButton variant="ghost" isDisabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}>{copy.previous}</VButton><VButton variant="ghost" isDisabled={currentPage === pages} onClick={() => setPage(currentPage + 1)}>{copy.next}</VButton></div></div> : null}
      </> : null}
    </div>
  </section>;
}
