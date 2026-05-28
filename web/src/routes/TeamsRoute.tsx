import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Archive, Bot, Link2, Plus, RefreshCw, Save, Send, Trash2, Unlink, Users } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { AgentConfigWorkspace, ProjectAgentBusEvent, Team, TeamCanvasNode, TeamListPayload, TeamOrganizationCanvas } from "../api/types";
import { useAppI18n } from "../i18n/useAppI18n";
import { AgentManagementNav } from "./AgentManagementNav";
import { agentDisplayInfo } from "./agentDisplay";
import styles from "./TeamsRoute.module.css";

const NODE_WIDTH = 172;
const NODE_HEIGHT = 92;
const TEAM_ORGANIZATION_CANVAS_KIND = "team_organization_canvas";

type TeamDraft = {
  name: string;
  purpose: string;
};

type NodeDraft = {
  label: string;
  role: string;
  purpose: string;
  agentId: string;
};

function formatTime(value: string, lang: "zh" | "en") {
  const parsed = new Date(String(value || ""));
  if (Number.isNaN(parsed.getTime())) {
    return value || "-";
  }
  return new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

function canvasFromTeam(team: Team | null): TeamOrganizationCanvas | null {
  if (!team || !team.canvas || !("nodes" in team.canvas)) {
    return null;
  }
  return team.canvas as TeamOrganizationCanvas;
}

function edgeLine(edge: { source: string; target: string }, nodes: TeamCanvasNode[]) {
  const source = nodes.find((node) => node.id === edge.source);
  const target = nodes.find((node) => node.id === edge.target);
  if (!source || !target) {
    return null;
  }
  const x1 = source.x + NODE_WIDTH;
  const y1 = source.y + NODE_HEIGHT / 2;
  const x2 = target.x;
  const y2 = target.y + NODE_HEIGHT / 2;
  return { x1, y1, x2, y2 };
}

function nextNodeId(nodes: TeamCanvasNode[]) {
  const ids = new Set(nodes.map((node) => node.id));
  let index = nodes.length + 1;
  let candidate = `node-${index}`;
  while (ids.has(candidate)) {
    index += 1;
    candidate = `node-${index}`;
  }
  return candidate;
}

function nodeTone(node: TeamCanvasNode) {
  if (node.status === "stale") {
    return styles.nodeStale;
  }
  if (node.agentId) {
    return styles.nodeBound;
  }
  return styles.nodeOpen;
}

export function TeamsRoute() {
  const { lang } = useAppI18n();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedTeamId, setSelectedTeamId] = useState("");
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [teamDraft, setTeamDraft] = useState<TeamDraft>({ name: "", purpose: "" });
  const [nodeDraft, setNodeDraft] = useState<NodeDraft>({ label: "", role: "", purpose: "", agentId: "" });
  const [teamMessage, setTeamMessage] = useState("");
  const [teamInterrupt, setTeamInterrupt] = useState(false);

  const teamsQuery = useQuery({
    queryKey: queryKeys.teams(),
    queryFn: () => fetchJson<TeamListPayload>("/api/teams"),
  });
  const workspaceQuery = useQuery({
    queryKey: queryKeys.agentConfigWorkspace(),
    queryFn: () => fetchJson<AgentConfigWorkspace>("/api/agents/config-workspace"),
  });
  const activeAgents = useMemo(
    () => (workspaceQuery.data?.agents ?? []).filter((agent) => agent.status !== "archived"),
    [workspaceQuery.data],
  );
  const teams = teamsQuery.data?.teams ?? [];
  const requestedTeamId = searchParams.get("team") ?? "";
  const effectiveTeamId = selectedTeamId || teams[0]?.teamId || "";
  const teamDetailQuery = useQuery({
    queryKey: queryKeys.team(effectiveTeamId),
    queryFn: () => fetchJson<Team>(`/api/teams/${encodeURIComponent(effectiveTeamId)}`),
    enabled: Boolean(effectiveTeamId),
  });
  const selectedTeam = teamDetailQuery.data ?? teams.find((team) => team.teamId === effectiveTeamId) ?? null;
  const canvas = canvasFromTeam(selectedTeam);
  const selectedNode = canvas?.nodes.find((node) => node.id === selectedNodeId) ?? canvas?.nodes[0] ?? null;

  useEffect(() => {
    if (requestedTeamId && teams.some((team) => team.teamId === requestedTeamId)) {
      setSelectedTeamId(requestedTeamId);
      return;
    }
    if (!selectedTeamId && teams[0]) {
      setSelectedTeamId(teams[0].teamId);
    }
  }, [requestedTeamId, selectedTeamId, teams]);

  useEffect(() => {
    if (selectedNode) {
      setNodeDraft({
        label: selectedNode.label,
        role: selectedNode.role,
        purpose: selectedNode.purpose,
        agentId: selectedNode.agentId,
      });
    }
  }, [selectedNode?.id]);

  const createTeamMutation = useMutation({
    mutationFn: (draft: TeamDraft) =>
      fetchJson<Team>("/api/teams", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(draft),
      }),
    onSuccess: (team) => {
      setSelectedTeamId(team.teamId);
      setSearchParams({ team: team.teamId });
      setTeamDraft({ name: "", purpose: "" });
      queryClient.invalidateQueries({ queryKey: queryKeys.teams() });
      queryClient.invalidateQueries({ queryKey: queryKeys.agentConfigWorkspace() });
    },
  });

  const archiveTeamMutation = useMutation({
    mutationFn: (teamId: string) =>
      fetchJson<Team>(`/api/teams/${encodeURIComponent(teamId)}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      setSelectedTeamId("");
      setSelectedNodeId("");
      setSearchParams({});
      queryClient.invalidateQueries({ queryKey: queryKeys.teams() });
      queryClient.invalidateQueries({ queryKey: queryKeys.agentConfigWorkspace() });
    },
  });

  const saveCanvasMutation = useMutation({
    mutationFn: (nextCanvas: TeamOrganizationCanvas) =>
      fetchJson<TeamOrganizationCanvas>(`/api/teams/${encodeURIComponent(nextCanvas.teamId)}/canvas`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(nextCanvas),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.teams() });
      if (selectedTeamId) {
        queryClient.invalidateQueries({ queryKey: queryKeys.team(selectedTeamId) });
      }
      queryClient.invalidateQueries({ queryKey: queryKeys.agentConfigWorkspace() });
    },
  });

  const sendTeamMessageMutation = useMutation({
    mutationFn: (payload: { teamId: string; content: string; interruptMode: string }) =>
      fetchJson<ProjectAgentBusEvent>(`/api/teams/${encodeURIComponent(payload.teamId)}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content: payload.content,
          interruptMode: payload.interruptMode,
          wakeTarget: true,
        }),
      }),
    onSuccess: () => {
      setTeamMessage("");
    },
  });

  function saveCanvas(nextCanvas: TeamOrganizationCanvas | null) {
    if (!nextCanvas || saveCanvasMutation.isPending) {
      return;
    }
    saveCanvasMutation.mutate(nextCanvas);
  }

  function addNode() {
    if (!canvas) {
      return;
    }
    const id = nextNodeId(canvas.nodes);
    saveCanvas({
      ...canvas,
      nodes: [
        ...canvas.nodes,
        {
          id,
          label: lang === "zh" ? "新角色" : "New role",
          type: "role",
          status: "unbound",
          x: 140 + canvas.nodes.length * 54,
          y: 150 + canvas.nodes.length * 36,
          agentId: "",
          agentCode: "",
          agentName: "",
          role: "",
          purpose: "",
        },
      ],
    });
    setSelectedNodeId(id);
  }

  function applyNodeDraft() {
    if (!canvas || !selectedNode) {
      return;
    }
    const agent = activeAgents.find((item) => item.agentId === nodeDraft.agentId);
    saveCanvas({
      ...canvas,
      nodes: canvas.nodes.map((node) =>
        node.id === selectedNode.id
          ? {
              ...node,
              label: nodeDraft.label.trim() || agent?.displayName || node.label,
              role: nodeDraft.role.trim(),
              purpose: nodeDraft.purpose.trim(),
              agentId: nodeDraft.agentId,
              agentCode: agent?.agentCode ?? "",
              agentName: agent?.displayName ?? "",
              type: nodeDraft.agentId ? "agent" : "role",
              status: nodeDraft.agentId ? "bound" : "unbound",
            }
          : node,
      ),
    });
  }

  function unbindSelectedNode() {
    if (!canvas || !selectedNode) {
      return;
    }
    saveCanvas({
      ...canvas,
      nodes: canvas.nodes.map((node) =>
        node.id === selectedNode.id
          ? {
              ...node,
              agentId: "",
              agentCode: "",
              agentName: "",
              type: "role",
              status: "unbound",
            }
          : node,
      ),
    });
  }

  function deleteSelectedNode() {
    if (!canvas || !selectedNode || canvas.nodes.length <= 1) {
      return;
    }
    const deletedNodeId = selectedNode.id;
    const nextNodes = canvas.nodes.filter((node) => node.id !== deletedNodeId);
    saveCanvas({
      ...canvas,
      nodes: nextNodes,
      edges: canvas.edges.filter((edge) => edge.source !== deletedNodeId && edge.target !== deletedNodeId),
    });
    setSelectedNodeId(nextNodes[0]?.id ?? "");
  }

  function connectFromLead() {
    if (!canvas || !selectedNode || canvas.nodes.length < 2) {
      return;
    }
    const source = canvas.nodes[0];
    if (source.id === selectedNode.id || canvas.edges.some((edge) => edge.source === source.id && edge.target === selectedNode.id)) {
      return;
    }
    saveCanvas({
      ...canvas,
      edges: [
        ...canvas.edges,
        {
          id: `${source.id}-${selectedNode.id}`,
          source: source.id,
          target: selectedNode.id,
          label: "",
          type: "supports",
        },
      ],
    });
  }

  const validation = canvas?.validation;
  const saveLabel = saveCanvasMutation.isPending ? (lang === "zh" ? "保存中" : "Saving") : saveCanvasMutation.isSuccess ? (lang === "zh" ? "已保存" : "Saved") : "";
  const activeTeamMemberCount = selectedTeam?.members.filter((member) => member.agentStatus === "active").length ?? 0;

  return (
    <section className={styles.route}>
      <header className={styles.header}>
        <div>
          <p>{lang === "zh" ? "Agent Center / Teams" : "Agent Center / Teams"}</p>
          <h1>{lang === "zh" ? "团队组织画布" : "Team Organization Canvas"}</h1>
        </div>
        <button type="button" className={styles.iconButton} onClick={() => teamsQuery.refetch()} title={lang === "zh" ? "刷新" : "Refresh"}>
          <RefreshCw size={15} />
        </button>
      </header>
      <AgentManagementNav active="teams" className={styles.managementNav} />

      <div className={styles.summaryBar}>
        <span>{lang === "zh" ? "团队" : "Teams"} <strong>{teamsQuery.data?.summary.activeTeamCount ?? 0}</strong></span>
        <span>{lang === "zh" ? "成员引用" : "Members"} <strong>{teamsQuery.data?.summary.memberCount ?? 0}</strong></span>
        <span>{lang === "zh" ? "失效引用" : "Stale"} <strong>{teamsQuery.data?.summary.staleMemberCount ?? 0}</strong></span>
        <span>{lang === "zh" ? "Agent 源" : "Agent source"} <strong>Agent Center</strong></span>
      </div>

      <div className={styles.workspace}>
        <aside className={styles.teamPanel}>
          <form
            className={styles.createForm}
            onSubmit={(event) => {
              event.preventDefault();
              createTeamMutation.mutate(teamDraft);
            }}
          >
            <input
              value={teamDraft.name}
              onChange={(event) => setTeamDraft((current) => ({ ...current, name: event.target.value }))}
              placeholder={lang === "zh" ? "新团队名称" : "New team name"}
            />
            <input
              value={teamDraft.purpose}
              onChange={(event) => setTeamDraft((current) => ({ ...current, purpose: event.target.value }))}
              placeholder={lang === "zh" ? "团队目的" : "Team purpose"}
            />
            <button type="submit" disabled={!teamDraft.name.trim() || createTeamMutation.isPending}>
              <Plus size={14} />
              {lang === "zh" ? "创建" : "Create"}
            </button>
          </form>
          <div className={styles.teamList}>
            {teams.map((team) => (
              <button
                key={team.teamId}
                type="button"
                className={team.teamId === selectedTeam?.teamId ? `${styles.teamRow} ${styles.teamRowActive}` : styles.teamRow}
                onClick={() => {
                  setSelectedTeamId(team.teamId);
                  setSearchParams({ team: team.teamId });
                  setSelectedNodeId("");
                }}
              >
                <strong>{team.name}</strong>
                <span>{team.purpose || team.teamId}</span>
                <small>{team.memberCount} agents · {formatTime(team.updatedAt, lang)}</small>
              </button>
            ))}
          </div>
        </aside>

        <main className={styles.canvasPanel}>
          <div className={styles.canvasToolbar}>
            <div>
              <strong>{selectedTeam?.name ?? (lang === "zh" ? "暂无团队" : "No team")}</strong>
              <span>{canvas ? `${canvas.path} · ${TEAM_ORGANIZATION_CANVAS_KIND}` : "workspace/teams"}</span>
            </div>
            <div className={styles.toolbarActions}>
              {saveLabel ? <span className={styles.saveState}>{saveLabel}</span> : null}
              <button type="button" onClick={addNode} disabled={!canvas}>
                <Plus size={14} />
                {lang === "zh" ? "节点" : "Node"}
              </button>
              <button
                type="button"
                className={styles.dangerButton}
                onClick={() => selectedTeam?.teamId && archiveTeamMutation.mutate(selectedTeam.teamId)}
                disabled={!selectedTeam || archiveTeamMutation.isPending}
              >
                <Archive size={14} />
                {lang === "zh" ? "归档" : "Archive"}
              </button>
            </div>
          </div>
          <div className={styles.canvas}>
            <svg className={styles.edges} width="100%" height="100%">
              {canvas?.edges.map((edge) => {
                const line = edgeLine(edge, canvas.nodes);
                return line ? (
                  <line key={edge.id} x1={line.x1} y1={line.y1} x2={line.x2} y2={line.y2} />
                ) : null;
              })}
            </svg>
            {canvas?.nodes.map((node) => {
              const agent = activeAgents.find((item) => item.agentId === node.agentId);
              const display = agent ? agentDisplayInfo(agent, lang) : null;
              return (
                <button
                  key={node.id}
                  type="button"
                  className={`${styles.node} ${nodeTone(node)} ${selectedNode?.id === node.id ? styles.nodeActive : ""}`}
                  style={{ transform: `translate(${node.x}px, ${node.y}px)` }}
                  onClick={() => setSelectedNodeId(node.id)}
                >
                  <span className={styles.nodeIcon}>{node.agentId ? <Bot size={15} /> : <Users size={15} />}</span>
                  <strong>{node.label}</strong>
                  <span>{display?.functionLabel || node.role || (lang === "zh" ? "未绑定" : "Unbound")}</span>
                  <small>{node.agentCode || node.status}</small>
                </button>
              );
            })}
          </div>
        </main>

        <aside className={styles.inspector}>
          <div className={styles.inspectorHeader}>
            <strong>{lang === "zh" ? "节点绑定" : "Node binding"}</strong>
            {validation && !validation.valid ? <AlertTriangle size={16} /> : <Link2 size={16} />}
          </div>
          {selectedNode ? (
            <div className={styles.inspectorBody}>
              <label>
                <span>{lang === "zh" ? "节点名称" : "Node label"}</span>
                <input value={nodeDraft.label} onChange={(event) => setNodeDraft((current) => ({ ...current, label: event.target.value }))} />
              </label>
              <label>
                <span>{lang === "zh" ? "组织角色" : "Role"}</span>
                <input value={nodeDraft.role} onChange={(event) => setNodeDraft((current) => ({ ...current, role: event.target.value }))} />
              </label>
              <label>
                <span>{lang === "zh" ? "绑定 Agent" : "Bound Agent"}</span>
                <select value={nodeDraft.agentId} onChange={(event) => setNodeDraft((current) => ({ ...current, agentId: event.target.value }))}>
                  <option value="">{lang === "zh" ? "不绑定" : "Unbound"}</option>
                  {activeAgents.map((agent) => {
                    const display = agentDisplayInfo(agent, lang);
                    return (
                      <option key={agent.agentId} value={agent.agentId}>
                        {display.name} · {agent.agentCode}
                      </option>
                    );
                  })}
                </select>
              </label>
              <label>
                <span>{lang === "zh" ? "目的" : "Purpose"}</span>
                <textarea value={nodeDraft.purpose} onChange={(event) => setNodeDraft((current) => ({ ...current, purpose: event.target.value }))} />
              </label>
              <div className={styles.actionRow}>
                <button type="button" onClick={applyNodeDraft} disabled={!canvas || saveCanvasMutation.isPending}>
                  <Save size={14} />
                  {lang === "zh" ? "保存节点" : "Save node"}
                </button>
                <button type="button" onClick={connectFromLead} disabled={!canvas || !selectedNode || canvas.nodes[0]?.id === selectedNode.id}>
                  <Link2 size={14} />
                  {lang === "zh" ? "接入主干" : "Connect"}
                </button>
                <button type="button" onClick={unbindSelectedNode} disabled={!canvas || !selectedNode?.agentId || saveCanvasMutation.isPending}>
                  <Unlink size={14} />
                  {lang === "zh" ? "解绑节点" : "Unbind"}
                </button>
                <button
                  type="button"
                  className={styles.dangerButton}
                  onClick={deleteSelectedNode}
                  disabled={!canvas || !selectedNode || canvas.nodes.length <= 1 || saveCanvasMutation.isPending}
                >
                  <Trash2 size={14} />
                  {lang === "zh" ? "删除节点" : "Delete"}
                </button>
              </div>
              <div className={styles.issueList}>
                {(validation?.issues ?? []).length ? (
                  validation?.issues.map((issue) => (
                    <div key={`${issue.code}-${issue.nodeId}-${issue.edgeId}`} className={styles.issue}>
                      <strong>{issue.code}</strong>
                      <span>{issue.message}</span>
                    </div>
                  ))
                ) : (
                  <span>{lang === "zh" ? "画布校验通过" : "Canvas validation passed"}</span>
                )}
              </div>
              <form
                className={styles.teamMessageForm}
                onSubmit={(event) => {
                  event.preventDefault();
                  if (!selectedTeam?.teamId || !teamMessage.trim()) {
                    return;
                  }
                  sendTeamMessageMutation.mutate({
                    teamId: selectedTeam.teamId,
                    content: teamMessage.trim(),
                    interruptMode: teamInterrupt ? "interrupt_targets" : "none",
                  });
                }}
              >
                <div className={styles.sectionTitle}>
                  <strong>{lang === "zh" ? "团队广播" : "Team broadcast"}</strong>
                  <span>{activeTeamMemberCount} active agents</span>
                </div>
                <textarea
                  value={teamMessage}
                  onChange={(event) => setTeamMessage(event.target.value)}
                  placeholder={lang === "zh" ? "发送给当前团队 active 成员" : "Send to active members of this team"}
                />
                <label className={styles.inlineToggle}>
                  <input type="checkbox" checked={teamInterrupt} onChange={(event) => setTeamInterrupt(event.target.checked)} />
                  <span>{lang === "zh" ? "打断正在直聊中的目标 Agent" : "Interrupt targeted running direct sessions"}</span>
                </label>
                <button
                  type="submit"
                  disabled={!selectedTeam || !teamMessage.trim() || activeTeamMemberCount === 0 || sendTeamMessageMutation.isPending}
                >
                  <Send size={14} />
                  {lang === "zh" ? "发送给团队" : "Send to team"}
                </button>
                {sendTeamMessageMutation.data ? (
                  <div className={styles.messageResult}>
                    <strong>{sendTeamMessageMutation.data.deliveries.length}</strong>
                    <span>{lang === "zh" ? "条投递已进入项目总群" : "deliveries recorded in project bus"}</span>
                  </div>
                ) : null}
                {sendTeamMessageMutation.error instanceof Error ? (
                  <div className={styles.messageError}>{sendTeamMessageMutation.error.message}</div>
                ) : null}
              </form>
            </div>
          ) : (
            <div className={styles.empty}>{lang === "zh" ? "创建或选择一个团队节点。" : "Create or select a team node."}</div>
          )}
        </aside>
      </div>
    </section>
  );
}
