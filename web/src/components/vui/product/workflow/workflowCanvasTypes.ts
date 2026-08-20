/**
 * Public VUI types for the runtime workflow canvas.
 * Routes map service DTOs into these models; renderers consume only these.
 * selectedNodeId never appears on the graph model (UI-only selection stays on props).
 */

export type WorkflowNodeRunStatus =
  | "pending"
  | "ready"
  | "running"
  | "waiting_human"
  | "succeeded"
  | "failed"
  | "blocked"
  | "skipped"
  | "stale"
  | "cancelled";

export type WorkflowActorKind = "agent" | "system" | "human";

export type WorkflowNodeVisualKind =
  | "agent_task"
  | "human_gate"
  | "system_task"
  | "decision"
  | "start"
  | "end";

export type WorkflowEdgeSemanticKind =
  | "main"
  | "human_gate"
  | "decision_branch"
  | "rerun"
  | "revise"
  | "promote"
  | "rollback"
  | "stop";

export type WorkflowEdgePathState = "idle" | "traversed" | "active" | "attention" | "danger";

export type WorkflowCanvasNodeInput = {
  nodeId: string;
  stageId: string;
  label: string;
  actorKind: WorkflowActorKind;
  visualKind: WorkflowNodeVisualKind;
  description?: string;
  primaryRoleKey?: string;
  collaboratorRoleKeys?: string[];
  producesArtifactKinds?: string[];
  acceptsGateKinds?: string[];
  /** From projection.run.nodeRuns — never from UI selection. */
  status: WorkflowNodeRunStatus;
  attempt?: number;
  primaryAgentId?: string;
  isRuntimeCurrent?: boolean;
  hasPendingHumanTask?: boolean;
  blockedReason?: string | null;
};

export type WorkflowCanvasEdgeInput = {
  edgeId: string;
  fromNodeId: string;
  toNodeId: string;
  label: string;
  gateKind: string;
  requiresHumanAccept?: boolean;
  requiredArtifactKinds?: string[];
  semanticKind: WorkflowEdgeSemanticKind;
  /** Decision multi-handle id when source is DecisionNode (e.g. "rerun"). */
  sourceHandle?: string;
  pathState: WorkflowEdgePathState;
  /** Critical labels always visible; routine auto labels hide until hover. */
  labelAlwaysVisible: boolean;
};

export type WorkflowCanvasStageInput = {
  stageId: string;
  label: string;
  nodeIds: string[];
  index?: number;
  /** Derived stage tone from member node statuses (not a second write authority). */
  stageTone?: "idle" | "active" | "done" | "attention";
  /**
   * Optional stage-header progress override ("completed / total"). When absent
   * the header counts succeeded member nodes; the hypothesis-first region uses
   * this to show 已闭环轮次/预算 instead of card counts.
   */
  progress?: { completed: number; total: number };
};

export type WorkflowCanvasRunMeta = {
  runId: string | null;
  status: string | null;
  runtimeCurrentNodeIds: string[];
  blockedReason?: string | null;
  completionKind?: string | null;
  parentRunId?: string | null;
  childRunIds?: string[];
  iterationBudgetMax?: number | null;
};

/** Full graph input for VWorkflowCanvas (definition + optional runtime projection). */
export type WorkflowLayoutInput = {
  stages: WorkflowCanvasStageInput[];
  nodes: WorkflowCanvasNodeInput[];
  edges: WorkflowCanvasEdgeInput[];
  run?: WorkflowCanvasRunMeta | null;
};

/** Geometry produced by pure layout (still free of React Flow). */
export type WorkflowLayoutNode = {
  id: string;
  stageId: string;
  label: string;
  actorKind: WorkflowActorKind | "system";
  visualKind: WorkflowNodeVisualKind | "stage_region";
  x: number;
  y: number;
  width: number;
  height: number;
  kind: "stage" | "task";
  parentStageId?: string;
  /** Relative position when parented to stage. */
  relativeX?: number;
  relativeY?: number;
  status?: WorkflowNodeRunStatus;
  attempt?: number;
  primaryAgentId?: string;
  isRuntimeCurrent?: boolean;
  hasPendingHumanTask?: boolean;
  blockedReason?: string | null;
  description?: string;
  primaryRoleKey?: string;
  stageTone?: WorkflowCanvasStageInput["stageTone"];
  /**
   * React Flow source handle ids, derived from the REAL current-run outgoing
   * edges of this node — never a hardcoded capability list.
   */
  sourceHandleIds?: string[];
  /**
   * Decision capability contract: the five outcomes the decision node can
   * expose (rerun / revise / promote / rollback / stop). Distinct from
   * sourceHandleIds: capabilities may exist without a current-run edge
   * (e.g. `revise`, which executes a child run lineage).
   */
  decisionOutcomeIds?: string[];
  /**
   * ELK port sides for this node's handles (source/target), keyed by handle
   * id, so the renderer can place React Flow Handles on the same side the
   * engine routes the edge from/to (P1-4). Absent when the node has no ports.
   * Optional anchors are 0–1 positions along that side (draw.io-style magnets).
   */
  portSides?: WorkflowPortSides;
};

/** Side plus relative snap fraction for each handle id. */
export type WorkflowPortSides = {
  source: Record<string, WorkflowPortSide>;
  target: Record<string, WorkflowPortSide>;
  sourceAnchor?: Record<string, number>;
  targetAnchor?: Record<string, number>;
};

/** Edge-port side used by the layout engine and mirroring on canvas handles. */
export type WorkflowPortSide = "NORTH" | "EAST" | "SOUTH" | "WEST";

/** Plain geometry point produced by the layout engine (not ELK-owned type). */
export type WorkflowLayoutPoint = { x: number; y: number };

/** One routed segment of an edge, from the layout engine. Unique geometry fact. */
export type WorkflowEdgeSection = {
  id: string;
  start: WorkflowLayoutPoint;
  end: WorkflowLayoutPoint;
  bendPoints: WorkflowLayoutPoint[];
  incomingSectionIds: string[];
  outgoingSectionIds: string[];
};

/** Layout-engine-owned edge label anchor; never a 50%-of-path estimate. */
export type WorkflowLabelBounds = { x: number; y: number; width: number; height: number };

export type WorkflowLayoutEdge = {
  id: string;
  source: string;
  target: string;
  label: string;
  semanticKind: WorkflowEdgeSemanticKind;
  pathState: WorkflowEdgePathState;
  labelAlwaysVisible: boolean;
  sourceHandle?: string;
  /** Short-name id of the ELK target port (e.g. "feedback:in"); matches a node target handle. */
  targetHandle?: string;
  gateKind?: string;
  requiresHumanAccept?: boolean;
};

/** Full layout-engine output; edges carry engine-owned geometry only. */
export type WorkflowLayoutResult = {
  nodes: WorkflowLayoutNode[];
  edges: Array<
    WorkflowLayoutEdge & {
      sections: WorkflowEdgeSection[];
      labelBounds?: WorkflowLabelBounds;
    }
  >;
  width: number;
  height: number;
};
