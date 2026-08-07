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
  sourceHandleIds?: string[];
};

export type WorkflowLayoutEdge = {
  id: string;
  source: string;
  target: string;
  label: string;
  semanticKind: WorkflowEdgeSemanticKind;
  pathState: WorkflowEdgePathState;
  labelAlwaysVisible: boolean;
  sourceHandle?: string;
  gateKind?: string;
  requiresHumanAccept?: boolean;
};
