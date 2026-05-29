import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Archive, Bot, Link2, Play, Plus, RefreshCw, Save, Send, Trash2, Unlink, Users } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { fetchJson } from "../api/client";
import {
  PROJECT_AGENT_BUS_TEAM_TIMELINE_LIMIT,
  isProjectAgentBusEventRevoked,
  listProjectAgentBusTimeline,
  projectAgentBusEventsForTeam,
  revokeProjectAgentBusMessage,
  sendTeamProjectBusMessage,
} from "../api/projectAgentBus";
import { queryKeys } from "../api/queryKeys";
import { AgentConfigWorkspace, ChatRoomDetail, Team, TeamCanvasNode, TeamListPayload, TeamOrganizationCanvas } from "../api/types";
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
  const [teamTaskTopic, setTeamTaskTopic] = useState("");

  const teamsQuery = useQuery({
    queryKey: queryKeys.teams(),
    queryFn: () => fetchJson<TeamListPayload>("/api/teams"),
  });
  const workspaceQuery = useQuery({
    queryKey: queryKeys.agentConfigWorkspace(),
    queryFn: () => fetchJson<AgentConfigWorkspace>("/api/agents/config-workspace"),
  });
  const projectBusQuery = useQuery({
    queryKey: queryKeys.projectAgentBus(),
    queryFn: () => listProjectAgentBusTimeline(PROJECT_AGENT_BUS_TEAM_TIMELINE_LIMIT),
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
  const teamBusEvents = useMemo(
    () => projectAgentBusEventsForTeam(projectBusQuery.data, selectedTeam?.teamId),
    [projectBusQuery.data, selectedTeam?.teamId],
  );

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
      queryClient.invalidateQueries({ queryKey: queryKeys.projectAgentBus() });
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
      sendTeamProjectBusMessage(payload),
    onSuccess: () => {
      setTeamMessage("");
      queryClient.invalidateQueries({ queryKey: queryKeys.projectAgentBus() });
      queryClient.invalidateQueries({ queryKey: queryKeys.agentConfigWorkspace() });
    },
  });

  const revokeTeamMessageMutation = useMutation({
    mutationFn: (eventId: string) =>
      revokeProjectAgentBusMessage({
        eventId,
        reason: "Revoked from Agent Center team broadcast history.",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.projectAgentBus() });
      queryClient.invalidateQueries({ queryKey: queryKeys.agentConfigWorkspace() });
    },
  });

  const syncTeamChatRoomMutation = useMutation({
    mutationFn: (teamId: string) =>
      fetchJson<Team>(`/api/teams/${encodeURIComponent(teamId)}/chat-room/sync`, {
        method: "POST",
      }),
    onSuccess: (team) => {
      queryClient.setQueryData(queryKeys.team(team.teamId), team);
      queryClient.invalidateQueries({ queryKey: queryKeys.teams() });
      queryClient.invalidateQueries({ queryKey: queryKeys.chatRooms() });
      queryClient.invalidateQueries({ queryKey: queryKeys.conversations() });
      queryClient.invalidateQueries({ queryKey: queryKeys.agentConfigWorkspace() });
    },
  });

  const startTeamRoundMutation = useMutation({
    mutationFn: (payload: { roomId: string; teamId: string; topic: string; mode: string; purpose: string }) =>
      fetchJson<ChatRoomDetail>(`/api/chat-rooms/${payload.roomId}/rounds`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          topic: payload.topic,
          mode: payload.mode,
          purpose: payload.purpose,
          config: {
            source: "team_workspace",
            teamId: payload.teamId,
          },
        }),
      }),
    onSuccess: (room, variables) => {
      setTeamTaskTopic("");
      queryClient.setQueryData(queryKeys.chatRoom(room.roomId), room);
      queryClient.invalidateQueries({ queryKey: queryKeys.chatRooms() });
      queryClient.invalidateQueries({ queryKey: queryKeys.chatRoom(room.roomId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.conversations() });
      queryClient.invalidateQueries({ queryKey: queryKeys.teams() });
      queryClient.invalidateQueries({ queryKey: queryKeys.team(variables.teamId) });
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
  const linkedRoomStatus = String(selectedTeam?.linkedChatRoom?.status || "").toLowerCase();
  const linkedRoomBusy = linkedRoomStatus === "running" || linkedRoomStatus === "stopping";
  const canStartTeamRound = Boolean(selectedTeam?.teamId && selectedTeam.linkedChatRoomId && activeTeamMemberCount > 0 && teamTaskTopic.trim() && !linkedRoomBusy);

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
              {selectedTeam?.linkedChatRoom ? (
                <small className={styles.linkedRoomLine}>
                  {lang === "zh" ? "已衔接群聊" : "Linked room"}
                  {" · "}
                  {selectedTeam.linkedChatRoom.title}
                  {" · "}
                  {selectedTeam.linkedChatRoom.participantCount} agents
                </small>
              ) : selectedTeam ? (
                <small className={styles.linkedRoomLine}>
                  {activeTeamMemberCount > 0
                    ? (lang === "zh" ? "尚未衔接群聊，可同步创建。" : "No linked room yet. Sync to create one.")
                    : (lang === "zh" ? "绑定 active Agent 后可衔接群聊。" : "Bind active agents before linking a room.")}
                </small>
              ) : null}
            </div>
            <div className={styles.toolbarActions}>
              {saveLabel ? <span className={styles.saveState}>{saveLabel}</span> : null}
              {selectedTeam?.linkedChatRoomId ? (
                <Link className={styles.toolbarLink} to={`/chat?room=${encodeURIComponent(selectedTeam.linkedChatRoomId)}`}>
                  {lang === "zh" ? "打开群聊" : "Open room"}
                </Link>
              ) : (
                <button
                  type="button"
                  onClick={() => selectedTeam?.teamId && syncTeamChatRoomMutation.mutate(selectedTeam.teamId)}
                  disabled={!selectedTeam || activeTeamMemberCount === 0 || syncTeamChatRoomMutation.isPending}
                >
                  <Link2 size={14} />
                  {syncTeamChatRoomMutation.isPending
                    ? (lang === "zh" ? "同步中" : "Syncing")
                    : (lang === "zh" ? "同步群聊" : "Sync room")}
                </button>
              )}
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
                className={styles.teamTaskForm}
                onSubmit={(event) => {
                  event.preventDefault();
                  if (!selectedTeam?.teamId || !selectedTeam.linkedChatRoomId || !teamTaskTopic.trim() || linkedRoomBusy) {
                    return;
                  }
                  startTeamRoundMutation.mutate({
                    roomId: selectedTeam.linkedChatRoomId,
                    teamId: selectedTeam.teamId,
                    topic: teamTaskTopic.trim(),
                    mode: selectedTeam.linkedChatRoom?.mode || "round_robin",
                    purpose: selectedTeam.linkedChatRoom?.purpose || "discussion",
                  });
                }}
              >
                <div className={styles.sectionTitle}>
                  <strong>{lang === "zh" ? "团队任务" : "Team task"}</strong>
                  <span>
                    {selectedTeam?.linkedChatRoomId
                      ? linkedRoomBusy
                        ? (lang === "zh" ? "群聊运行中" : "room running")
                        : (lang === "zh" ? "发送到群聊 round" : "starts a room round")
                      : (lang === "zh" ? "需要先同步群聊" : "sync room first")}
                  </span>
                </div>
                <textarea
                  value={teamTaskTopic}
                  onChange={(event) => setTeamTaskTopic(event.target.value)}
                  placeholder={lang === "zh" ? "输入团队要协作处理的议题或任务" : "Enter a topic or task for this team"}
                />
                <button
                  type="submit"
                  disabled={!canStartTeamRound || startTeamRoundMutation.isPending}
                >
                  <Play size={14} />
                  {startTeamRoundMutation.isPending
                    ? (lang === "zh" ? "启动中" : "Starting")
                    : (lang === "zh" ? "启动团队讨论" : "Start team round")}
                </button>
                {startTeamRoundMutation.data ? (
                  <div className={styles.messageResult}>
                    <strong>{startTeamRoundMutation.data.rounds.length}</strong>
                    <span>{lang === "zh" ? "轮讨论已写入关联群聊" : "rounds now recorded in the linked room"}</span>
                    <Link to={`/chat?room=${encodeURIComponent(startTeamRoundMutation.data.roomId)}`}>
                      {lang === "zh" ? "打开群聊" : "Open room"}
                    </Link>
                  </div>
                ) : null}
                {startTeamRoundMutation.error instanceof Error ? (
                  <div className={styles.messageError}>{startTeamRoundMutation.error.message}</div>
                ) : null}
              </form>
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
              <section className={styles.teamHistoryPanel}>
                <div className={styles.sectionTitle}>
                  <strong>{lang === "zh" ? "最近团队广播" : "Recent team broadcasts"}</strong>
                  <span>{teamBusEvents.length} events</span>
                </div>
                {projectBusQuery.isPending ? (
                  <div className={styles.empty}>{lang === "zh" ? "正在读取项目总群..." : "Loading project bus..."}</div>
                ) : teamBusEvents.length ? (
                  <div className={styles.teamHistoryList}>
                    {teamBusEvents.map((event) => {
                      const revoked = isProjectAgentBusEventRevoked(event);
                      return (
                        <article key={event.eventId} className={revoked ? `${styles.teamHistoryItem} ${styles.teamHistoryItemRevoked}` : styles.teamHistoryItem}>
                          <div className={styles.teamHistoryHeader}>
                            <strong>{event.summary || event.content}</strong>
                            <span>{revoked ? (lang === "zh" ? "已撤回" : "revoked") : event.messageType}</span>
                          </div>
                          <p>{revoked ? (lang === "zh" ? "这条团队广播已撤回，目标 Agent 已请求停止。" : "This team broadcast was revoked and target agents were asked to stop.") : event.content}</p>
                          <div className={styles.teamHistoryMeta}>
                            <span>{formatTime(event.createdAt, lang)}</span>
                            <span>{event.deliveries.length} deliveries</span>
                            <span>{event.interruptions.length} interrupts</span>
                          </div>
                          <div className={styles.deliveryList}>
                            {event.deliveries.map((delivery) => (
                              <span key={`${event.eventId}-${delivery.targetAgentId}-${delivery.inboxMessageId}`}>
                                {delivery.targetAgentCode || delivery.targetAgentName || delivery.targetAgentId}: {delivery.revoked ? "revoked" : delivery.wake?.wakeStatus || delivery.status}
                              </span>
                            ))}
                          </div>
                          {event.createdBy === "user" && !revoked ? (
                            <button
                              type="button"
                              className={styles.revokeButton}
                              disabled={revokeTeamMessageMutation.isPending}
                              onClick={() => revokeTeamMessageMutation.mutate(event.eventId)}
                            >
                              {revokeTeamMessageMutation.isPending ? (lang === "zh" ? "撤回中" : "Revoking") : (lang === "zh" ? "撤回" : "Revoke")}
                            </button>
                          ) : null}
                        </article>
                      );
                    })}
                  </div>
                ) : (
                  <div className={styles.empty}>{lang === "zh" ? "当前团队还没有广播记录。" : "No team broadcasts yet."}</div>
                )}
                {revokeTeamMessageMutation.error instanceof Error ? (
                  <div className={styles.messageError}>{revokeTeamMessageMutation.error.message}</div>
                ) : null}
              </section>
            </div>
          ) : (
            <div className={styles.empty}>{lang === "zh" ? "创建或选择一个团队节点。" : "Create or select a team node."}</div>
          )}
        </aside>
      </div>
    </section>
  );
}
