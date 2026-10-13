import { useState } from "react";
import type { AgentInstance, SessionSummary, Team } from "../../api/types";
import { VSessionSearchDialog, VStringSelect, VTabs, type VSessionSearchDialogItem } from "../../components/vui";
import { useSessionSearchQuery } from "../useSessionSearchQuery";
import { agentSessionStatusTone } from "../AgentSessionTabStrip";
import { sessionActivityLabel } from "../sessionActivityIndicator";
import { isEligibleDirectoryAgent } from "../agentConversationDirectoryModel";
import { filterOutTombstonedSessions } from "../sessionDeleteTombstone";

export type ChatSessionIndexSearchProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  lang: "zh" | "en";
  agentsById: Map<string, AgentInstance>;
  teams: Team[];
  knownSessions: Map<string, SessionSummary>;
  activeSessionId: string | null;
  approvalSessionIds: readonly string[];
  runningSessionIds: readonly string[];
  onOpenSession: (id: string) => void;
  onOpenAgent: (agent: AgentInstance) => void;
  onOpenTeam: (team: Team) => void;
};

type SearchScope = "all" | "sessions" | "agents" | "teams";

export function ChatSessionIndexSearch({ open, onOpenChange, lang, agentsById, teams, knownSessions, activeSessionId,
  approvalSessionIds, runningSessionIds, onOpenSession, onOpenAgent, onOpenTeam }: ChatSessionIndexSearchProps) {
  const zh = lang === "zh";
  const [scope, setScope] = useState<SearchScope>("all");
  const [query, setQuery] = useState("");
  const [agentId, setAgentId] = useState("");
  const [teamId, setTeamId] = useState("");
  const includesSessions = scope === "all" || scope === "sessions";
  const filters = scope === "sessions" ? { agentId, teamId } : { agentId: "", teamId: "" };
  const search = useSessionSearchQuery({ queryText: query, filters, enabled: open && includesSessions });
  const needle = query.trim().toLocaleLowerCase();
  const matches = (...values: (string | undefined)[]) => !needle || values.some(value => value?.toLocaleLowerCase().includes(needle));
  const agents = [...agentsById.values()].filter(isEligibleDirectoryAgent);
  const directoryItems: VSessionSearchDialogItem[] = [];
  // Directory identity matches stay separate from server-paginated session hits.
  if (scope === "all" || scope === "agents") agents.filter(agent => matches(agent.displayName, agent.agentCode)).forEach(agent => {
    directoryItems.push({ id: `agent:${agent.agentId}`, title: agent.displayName || agent.agentCode || agent.agentId,
      meta: "Agent", highlight: query, onOpen: () => onOpenAgent(agent) });
  });
  if (scope === "all" || scope === "teams") teams.filter(team => matches(team.name, team.teamId)).forEach(team => {
    directoryItems.push({ id: `team:${team.teamId}`, title: team.name || team.teamId,
      meta: zh ? "团队" : "Team", highlight: query, onOpen: () => onOpenTeam(team) });
  });
  const sessionHits = new Map(search.sessions.map(session => [session.id, session]));
  // Preserve the old shortcut's navigation through loaded task/workspace metadata.
  if (needle && includesSessions) knownSessions.forEach(session => {
    if ((!filters.agentId || session.agentId === filters.agentId) && (!filters.teamId || session.teamId === filters.teamId)
      && matches(session.taskTitle, session.title, session.taskSummary, session.resultCard?.summary, session.workspacePath,
        session.agentCode, session.agentDisplayName) && !sessionHits.has(session.id)) sessionHits.set(session.id, session);
  });
  const visibleSessionHits = filterOutTombstonedSessions([...sessionHits.values()]) ?? [];
  const sessionItems: VSessionSearchDialogItem[] = includesSessions ? visibleSessionHits.map(session => {
    const tone = agentSessionStatusTone(session.status || "", { session, isActive: session.id === activeSessionId,
      needsApproval: approvalSessionIds.includes(session.id), isRuntimeRunning: runningSessionIds.includes(session.id) });
    const agent = session.agentId ? agentsById.get(session.agentId) : undefined;
    return { id: `session:${session.id}`, title: session.taskTitle || session.resultCard?.title || session.title || agent?.displayName || session.id,
      detail: session.taskSummary || session.resultCard?.summary || "", highlight: search.debouncedQueryText,
      meta: [zh ? "会话" : "Chat", session.agentDisplayName || agent?.displayName || "", sessionActivityLabel(tone, lang),
        session.updatedAt || session.lastActive || ""].filter(Boolean).join(" · "),
      active: session.id === activeSessionId, onOpen: () => onOpenSession(session.id) };
  }) : [];
  return <VSessionSearchDialog open={open} onOpenChange={onOpenChange} query={query} onQueryChange={setQuery}
    items={!needle && scope === "all" ? [...sessionItems, ...directoryItems] : [...directoryItems, ...sessionItems]} filters={<>
      <VTabs aria-label={zh ? "搜索范围" : "Search scope"} value={scope} onValueChange={value => setScope(value as SearchScope)}
        items={[{ id: "all", label: zh ? "全部" : "All" }, { id: "sessions", label: zh ? "会话" : "Chats" },
          { id: "agents", label: "Agent" }, { id: "teams", label: zh ? "团队" : "Teams" }]} />
      {scope === "sessions" ? <>
        <VStringSelect ariaLabel={zh ? "按 Agent 过滤" : "Filter by Agent"} value={agentId} onValueChange={setAgentId}
          options={[{ value: "", label: zh ? "全部 Agent" : "All Agents" }, ...agents.map(agent => ({ value: agent.agentId, label: agent.displayName || agent.agentCode || agent.agentId }))]} />
        <VStringSelect ariaLabel={zh ? "按团队过滤" : "Filter by team"} value={teamId} onValueChange={setTeamId}
          options={[{ value: "", label: zh ? "全部团队" : "All teams" }, ...teams.map(team => ({ value: team.teamId, label: team.name || team.teamId }))]} />
      </> : null}
    </>} loading={includesSessions && search.isLoading} error={includesSessions ? search.searchError : undefined}
    onRetry={() => void search.retrySearch()} retrying={includesSessions && search.isFetching}
    hasMore={includesSessions && search.hasMore} loadingMore={includesSessions && search.isLoadingMore}
    onLoadMore={() => void search.loadMore()}
    totalEstimate={includesSessions ? search.totalEstimate === undefined ? undefined : search.totalEstimate + directoryItems.length + visibleSessionHits.length - search.sessions.length : directoryItems.length}
    labels={{ searchPlaceholder: zh ? "搜索会话、Agent 或团队" : "Search chats, Agents or teams",
      emptyTitle: zh ? "没有匹配结果" : "No matching results", emptyHint: zh ? "换个关键词，或调整搜索范围" : "Try another keyword or scope",
      loadMore: zh ? "加载更多会话" : "Load more chats", loadingMore: zh ? "加载中…" : "Loading…",
      errorTitle: zh ? "会话搜索请求失败" : "Chat search failed", retry: zh ? "重试" : "Retry",
      resultSummary: (loaded, total) => zh ? `已加载 ${loaded} / ${total} 个结果` : `Loaded ${loaded} of ${total} results`,
      hint: zh ? "↑↓ 选择 · Enter 打开 · Esc 关闭" : "↑↓ navigate · Enter open · Esc close" }} data-vui="chat-left-rail-session-catalog" />;
}
