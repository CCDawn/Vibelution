import { useEffect, useMemo, useRef, useState, type PointerEvent } from "react";
import type { TeamCanvasNode, TeamOrganizationCanvas } from "../../src/api/types";
import { VButton, VWorkflowCanvas, type WorkflowLayoutInput } from "../../src/components/vui";
import { TeamOrganizationCanvasSurface } from "../../src/routes/teams/TeamOrganizationCanvasSurface";
import { canvasStyleScale, canvasViewStyle } from "../../src/routes/teams/canvasGeometry";
import canvasStyles from "../../src/routes/TeamsRoute.styles";

type PreviewMember = { name: string; role: string; note: string };
const noAction = () => {};

export function OrganizationCanvasPreview({ teamId, members, selectedMember, onSelectMember, onNotice }: {
  teamId: string; members: PreviewMember[]; selectedMember: number;
  onSelectMember: (index: number) => void; onNotice: (text: string) => void;
}) {
  const initialNodes = useMemo(() => members.map((member, index): TeamCanvasNode => ({
    id: `member-${index}`, label: member.name, type: "agent", status: "bound",
    x: index === 0 ? 260 : index === 1 ? 100 : 420, y: index === 0 ? 80 : 320,
    agentId: `${teamId}-${index}`, agentCode: `member-${index}`, agentName: member.name,
    role: member.role, purpose: "", responsibilities: [member.note],
  })), [members, teamId]);
  const [nodes, setNodes] = useState(initialNodes);
  const [showCommunication, setShowCommunication] = useState(true);
  const frameRef = useRef<HTMLDivElement>(null);
  const [frameSize, setFrameSize] = useState({ width: 800, height: 600 });
  const drag = useRef<{ id: string; x: number; y: number; startX: number; startY: number } | null>(null);
  useEffect(() => { setNodes(initialNodes); }, [initialNodes]);
  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    const observer = new ResizeObserver(([entry]) => setFrameSize({ width: entry.contentRect.width, height: entry.contentRect.height }));
    observer.observe(frame);
    return () => observer.disconnect();
  }, []);
  const viewport = canvasViewStyle(initialNodes, frameSize);
  const edges = [
    { id: "delegate-1", source: "member-0", target: "member-1", label: "资料核验", type: "delegates_to" },
    { id: "delegate-2", source: "member-0", target: "member-2", label: "实现验证", type: "delegates_to" },
    { id: "communication", source: "member-1", target: "member-2", label: "协作沟通", type: "communication" },
  ];
  const canvas: TeamOrganizationCanvas = {
    schemaVersion: 1, canvasKind: "team_organization_canvas", teamId,
    updatedAt: "", path: "", viewport: { x: 0, y: 0, zoom: 1 }, nodes, edges,
  };
  function beginDrag(event: PointerEvent<HTMLButtonElement>, node: TeamCanvasNode) {
    if (event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    onSelectMember(Number(node.id.split("-")[1]));
    drag.current = { id: node.id, x: node.x, y: node.y, startX: event.clientX, startY: event.clientY };
  }
  function moveDrag(event: PointerEvent<HTMLButtonElement>) {
    const current = drag.current;
    if (!current) return;
    const scale = canvasStyleScale(viewport);
    setNodes((previous) => previous.map((node) => node.id === current.id ? {
      ...node, x: Math.max(0, current.x + (event.clientX - current.startX) / scale),
      y: Math.max(0, current.y + (event.clientY - current.startY) / scale),
    } : node));
  }
  return <div className="flex h-full min-h-0 flex-col gap-2" data-testid="preview-organization-canvas">
    <div className="flex shrink-0 items-center gap-2 px-1 pb-2 text-[12px] text-[var(--fg-tertiary)]">
      <span className="mr-auto">拖动成员调整位置 · 点击查看职责</span>
      <VButton variant="secondary" density="compact" aria-pressed={showCommunication} onClick={() => setShowCommunication((value) => !value)}>通信连线</VButton>
      <VButton variant="secondary" density="compact" onClick={() => { setNodes(initialNodes); onNotice("组织画布已恢复示例布局。"); }}>自动整理</VButton>
    </div>
    <TeamOrganizationCanvasSurface
      lang="zh" selectedTeam={null} effectiveTeamId={teamId} teamDetailLoadMode="preview"
      researchTeamId="" canvas={canvas} displayCanvasNodes={nodes}
      visibleEdges={showCommunication ? edges : edges.filter((edge) => edge.type !== "communication")}
      selectedNodeId={`member-${selectedMember}`} activeAgents={[]}
      agentDisplay={() => ({ name: "示例成员" })}
      researchCanvasReadOnly={false} hideToolbar researchCanvasAutoLayoutActive={false}
      showCommunicationEdges={showCommunication} organizationEdgeCount={2} communicationEdgeCount={1}
      communicationEdgeHint="示例成员之间的协作沟通" communicationEdgeButtonLabel="通信连线"
      saveLabel="示例布局" hasWritableCanvas={false} linkedChatRoomId="" activeTeamMemberCount={members.length}
      teamSyncPending={false} teamArchivePending={false} teamArchiveDisabledReason=""
      showTeamLoadingSurface={false} teamWorkspaceLoadingTitle="" teamWorkspaceLoadingMessage=""
      teamDetailPending={false} teamCanvasPending={false} teamDetailError={false} teamCanvasError={false}
      canvasViewportStyle={viewport} canvasFrameRef={frameRef} nodeToneClass={() => ""} roleBadgeToneClass={() => ""}
      nodeActiveClassName="ring-2 ring-[var(--accent-cool)]" nodeReadOnlyClassName="" styles={canvasStyles}
      teamWorkspaceRoute={() => ""} teamChatRoomRoute={() => ""}
      onSelectNode={(id) => onSelectMember(Number(id.split("-")[1]))}
      onLayoutModeChange={noAction} onToggleCommunicationEdges={() => setShowCommunication((value) => !value)}
      onAddNode={noAction} onArchiveTeam={noAction} onSyncRoom={noAction}
      onNodePointerDown={beginDrag} onNodePointerMove={moveDrag}
      onNodePointerUp={() => { drag.current = null; }} onNodePointerCancel={() => { drag.current = null; }}
    />
  </div>;
}

export const workflowGraph: WorkflowLayoutInput = {
  stages: [
    { stageId: "research", label: "资料与假设", nodeIds: ["question", "sources", "hypothesis"], index: 0 },
    { stageId: "experiment", label: "实验验证", nodeIds: ["design", "execute", "review"], index: 1 },
    { stageId: "result", label: "结论与归档", nodeIds: ["conclusion", "archive"], index: 2 },
  ],
  nodes: [
    { nodeId: "question", stageId: "research", label: "明确研究问题", description: "确认任务边界与验收目标", actorKind: "human", visualKind: "human_gate", status: "succeeded" },
    { nodeId: "sources", stageId: "research", label: "资料收集与核验", description: "整理来源并核对证据", actorKind: "agent", visualKind: "agent_task", status: "succeeded" },
    { nodeId: "hypothesis", stageId: "research", label: "形成可验证假设", description: "从证据中提炼本轮假设", actorKind: "agent", visualKind: "agent_task", status: "succeeded" },
    { nodeId: "design", stageId: "experiment", label: "设计验证实验", description: "确定对照、输入和通过条件", actorKind: "agent", visualKind: "agent_task", status: "succeeded" },
    { nodeId: "execute", stageId: "experiment", label: "执行实验", description: "运行本轮验证并记录结果", actorKind: "agent", visualKind: "agent_task", status: "running", isRuntimeCurrent: true },
    { nodeId: "review", stageId: "experiment", label: "人工验收", description: "检查结果与证据是否充分", actorKind: "human", visualKind: "human_gate", status: "pending" },
    { nodeId: "conclusion", stageId: "result", label: "汇总结论", description: "归纳结果并保留限制", actorKind: "agent", visualKind: "agent_task", status: "pending" },
    { nodeId: "archive", stageId: "result", label: "归档证据", description: "保存本轮研究与实验记录", actorKind: "system", visualKind: "system_task", status: "pending" },
  ],
  edges: ["question", "sources", "hypothesis", "design", "execute", "review", "conclusion"].map((fromNodeId, index) => ({
    edgeId: `step-${index}`, fromNodeId, toNodeId: ["sources", "hypothesis", "design", "execute", "review", "conclusion", "archive"][index],
    label: index === 4 ? "等待验收" : "继续", gateKind: "auto", semanticKind: index === 4 ? "human_gate" : "main",
    pathState: index < 3 ? "traversed" : index === 3 ? "active" : "idle", labelAlwaysVisible: index === 4,
  })),
};

export function WorkflowCanvasPreview({ selectedNodeId, onSelectNode }: {
  selectedNodeId: string | null; onSelectNode: (id: string | null) => void;
}) {
  const [viewMode, setViewMode] = useState<"canvas" | "stage">("canvas");
  return <div className="flex h-full min-h-0 flex-col gap-2" data-testid="preview-workflow-canvas">
    <div className="flex shrink-0 items-center gap-2 px-1 pb-2">
      <VButton variant={viewMode === "canvas" ? "primary" : "secondary"} density="compact" aria-pressed={viewMode === "canvas"} onClick={() => setViewMode("canvas")}>全流程</VButton>
      <VButton variant={viewMode === "stage" ? "primary" : "secondary"} density="compact" aria-pressed={viewMode === "stage"} onClick={() => setViewMode("stage")}>阶段聚焦</VButton>
      <span className="ml-auto text-[12px] text-[var(--fg-tertiary)]">节点与运行状态为示例</span>
    </div>
    <div className="min-h-0 flex-1 overflow-hidden">
      <VWorkflowCanvas graph={workflowGraph} viewMode={viewMode} selectedNodeId={selectedNodeId}
        runtimeCurrentNodeIds={["execute"]} onSelectNode={onSelectNode} height="100%"
        layoutMode="serpentine" showMiniMap compactControls showLegend={false} />
    </div>
  </div>;
}
