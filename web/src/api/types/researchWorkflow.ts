/**
 * Research workflow domain DTOs (Task 1 contract).
 * Mirrors core/research/workflow — server is authority for run state.
 * selectedNodeId is UI-only and must not appear on server projections.
 */

export type ActorKind = "agent" | "system" | "human";

export type WorkflowStageId =
  | "knowledge_collection"
  | "experiment_design"
  | "execution_iteration";

export type WorkflowRunStatus =
  | "queued"
  | "running"
  | "waiting_human"
  | "blocked"
  | "succeeded"
  | "failed"
  | "cancelled";

export type NodeRunStatus =
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

export type HandoffStatus =
  | "pending"
  | "ready"
  | "waiting_human"
  | "accepted"
  | "rejected"
  | "superseded"
  | "failed";

export type GateKind =
  | "auto"
  | "human"
  | "knowledge_package"
  | "frozen_protocol"
  | "smoke"
  | "promotion";

/** Five structured iteration decisions only — never free-form routing strings. */
export type IterationDecisionKind =
  | "rerun_same_protocol"
  | "revise_protocol"
  | "promote_candidate"
  | "rollback_candidate"
  | "stop";

export type CompletionKind =
  | ""
  | "branched_revision"
  | "stopped"
  | "promoted"
  | "rolled_back"
  | "failed";

export type PromotionOperation = "promote" | "rollback";

export type IterationDecisionRecord = {
  decisionId: string;
  decisionKind: IterationDecisionKind;
  runId: string;
  nodeRunId: string;
  iterationAttempt: number;
  selectedCandidateRef?: string;
  baselineRef?: string;
  frozenProtocolRef?: string;
  evaluationReportRef?: string;
  reason?: string;
  decidedBy?: string;
  decidedAt?: string;
  idempotencyKey?: string;
  parentDecisionId?: string;
  supersedesDecisionId?: string;
  terminalReason?: string;
  promotionOperation?: PromotionOperation | "";
  budgetMax?: number;
};

export type PromotionProposalRef = {
  proposalId: string;
  runId: string;
  operation: PromotionOperation;
  decisionId?: string;
  targetCandidateRef?: string;
  selectedCandidateRef?: string;
  baselineRef?: string;
  status: string;
  reason?: string;
  createdAt?: string;
};

export type ArtifactRef = {
  artifactId: string;
  kind: string;
  version: string;
  contentHash: string;
  uri?: string;
  summary?: string;
};

export type WorkflowNodeSpec = {
  nodeId: string;
  stageId: WorkflowStageId;
  label: string;
  actorKind: ActorKind;
  primaryRoleKey: string;
  description?: string;
  collaboratorRoleKeys?: string[];
  acceptsGateKinds?: GateKind[];
  producesArtifactKinds?: string[];
};

export type WorkflowStageSpec = {
  stageId: WorkflowStageId;
  index: number;
  label: string;
  nodeIds: string[];
};

export type WorkflowEdgeSpec = {
  edgeId: string;
  fromNodeId: string;
  toNodeId: string;
  label: string;
  gateKind: GateKind;
  requiredArtifactKinds?: string[];
  requiresHumanAccept?: boolean;
};

export type WorkflowDefinition = {
  workflowId: string;
  schemaVersion: string;
  label: string;
  structureHash: string;
  stages: WorkflowStageSpec[];
  nodes: WorkflowNodeSpec[];
  edges: WorkflowEdgeSpec[];
};

export type WorkflowNodeRunProjection = {
  nodeId: string;
  status: NodeRunStatus;
  nodeRunId?: string | null;
  attempt?: number;
  primaryAgentId?: string;
  actorKind?: ActorKind | "";
};

export type HumanTaskSummary = {
  taskId: string;
  nodeId: string;
  status: string;
  prompt?: string;
};

/** Server canvas projection — never includes selectedNodeId. */
export type WorkflowCanvasProjection = {
  definition: WorkflowDefinition;
  run: {
    runId: string | null;
    teamId: string | null;
    runVersion: number | null;
    status: WorkflowRunStatus | null;
    runtimeCurrentNodeIds: string[];
    nodeRuns: Record<string, WorkflowNodeRunProjection>;
    pendingHumanTasks: HumanTaskSummary[];
    /** Parent/child revision fork links (optional). */
    parentRunId?: string | null;
    childRunIds?: string[];
    completionKind?: CompletionKind | null;
    officialCandidateRef?: string | null;
    blockedReason?: string | null;
    iterationBudgetMax?: number | null;
  };
};

export type RunAgentBindingSnapshot = {
  snapshotId: string;
  workflowId: string;
  workflowVersionId: string;
  runId: string;
  nodeId: string;
  agentId: string;
  roleKey: string;
  actorKind: ActorKind;
  resolvedFrom: string;
  displayName?: string;
  modelProfileId?: string;
  capturedAt?: string;
};

export type NodeAgentSessionBinding = {
  bindingId: string;
  workflowId: string;
  workflowVersionId: string;
  runId: string;
  nodeId: string;
  nodeRunId: string;
  nodeAttempt: number;
  agentId: string;
  roleKey: string;
  sessionId: string;
  sessionAttempt: number;
  taskId: string;
  turnId: string;
  checkpointId: string;
  status: string;
  boundAt: string;
  supersedesBindingId?: string;
};

export type NodeHandoffRecord = {
  handoffId: string;
  workflowId: string;
  workflowVersionId: string;
  runId: string;
  fromNodeId: string;
  fromNodeRunId: string;
  toNodeId: string;
  toNodeRunId?: string;
  gateKind: GateKind;
  outputArtifactRefs: ArtifactRef[];
  inputSnapshotHash: string;
  status: HandoffStatus;
  offeredAt: string;
  acceptedAt?: string;
  acceptedBy?: string;
  rejectionReason?: string;
  supersedesHandoffId?: string;
  humanTaskId?: string;
};

/** Canonical Challenge Cup fixed node ids (v1 topology). */
export const CHALLENGE_CUP_NODE_IDS = [
  "source_finding",
  "source_extraction",
  "evidence_relations",
  "knowledge_ingestion",
  "knowledge_handoff",
  "hypothesis_design",
  "protocol_design",
  "protocol_review",
  "protocol_freeze",
  "smoke_gate",
  "controlled_run",
  "result_evaluation",
  "iteration_decision",
  "candidate_promotion",
  "result_package",
] as const;

export type ChallengeCupNodeId = (typeof CHALLENGE_CUP_NODE_IDS)[number];

export const CHALLENGE_CUP_WORKFLOW_ID = "challenge-cup-research";

/** Effective (current-configuration) agent binding for one node. */
export type EffectiveAgentBinding = {
  nodeId: string;
  roleKey: string;
  agentId: string;
  resolvedFrom: "workflow_default" | "stage_override" | "node_override" | "unbound" | string;
};

export type EffectiveAgentBindingsResponse = {
  workflowId: string;
  workflowVersionId: string;
  teamId: string;
  bindings: EffectiveAgentBinding[];
};

/** Controlled-write binding config payload (whole-layer replacement). */
export type AgentBindingConfigPayload = {
  teamId: string;
  workflowDefaults?: Record<string, string>;
  stageOverrides?: Record<string, Record<string, string>>;
  nodeOverrides?: Record<string, string>;
};

/** Per-node command capability as reported by the backend (drives UI). */
export type NodeCommandCapability = {
  command: string;
  available: boolean;
  reason: string;
};

/** Extended node detail payload (Task: binding + session + commands). */
export type ResearchWorkflowNodeDetail = {
  runId: string;
  teamId: string;
  runVersion: number;
  nodeId: string;
  actorKind: ActorKind;
  primaryRoleKey: string;
  label: string;
  bindingSnapshot: Record<string, unknown>;
  sessionBinding: NodeAgentSessionBinding | null;
  chatDeepLink: string | null;
  sessionAnchorDegraded: boolean;
  runtimeCurrent: boolean;
  status: string | null;
  nodeAttempt: number;
  blockedReason: string;
  artifacts: Record<string, unknown>;
  commands: NodeCommandCapability[];
};

export type ResearchWorkflowScopedProjection = {
  runId: string;
  teamId: string;
  runVersion: number;
};

export type ResearchBudgetLedgerSnapshot = {
  budgetLedgerId: string;
  runId: string;
  stageId: string;
  policySnapshotHash: string;
  limits: Record<string, number>;
  reserved: Record<string, number>;
  consumed: Record<string, number>;
  remaining: Record<string, number>;
  stopReason: string;
  updatedAt: string;
};

export type ResearchBudgetProjection = ResearchWorkflowScopedProjection & {
  budgetLedgers: ResearchBudgetLedgerSnapshot[];
  budgetReservations: Array<Record<string, unknown>>;
};

export type HypothesisCandidateSnapshot = {
  candidateId: string;
  claim: string;
  scores: Record<string, number>;
  counterEvidenceRefs: string[];
  derivedFromCandidateIds: string[];
  status: string;
  reviewRef: string;
};

export type HypothesisPortfolioSnapshot = {
  portfolioId: string;
  runId: string;
  maxCandidates: number;
  maxEvolutionRounds: number;
  candidates: HypothesisCandidateSnapshot[];
};

export type ResearchHypothesesProjection = ResearchWorkflowScopedProjection & {
  hypothesisPortfolios: HypothesisPortfolioSnapshot[];
};

export type ExperimentCampaignSnapshot = {
  campaignId: string;
  runId: string;
  hypothesisCandidateId: string;
  protocolHash: string;
  environmentSnapshotHash: string;
  datasetSnapshotRefs: string[];
  baselineRefs: string[];
  metricContractRef: string;
  stage: "feasibility" | "baseline" | "agenda" | "ablation_replication" | string;
  seedSet: number[];
  replicationCount: number;
  budgetLedgerRef: string;
  stopCriteria: Record<string, unknown>;
  experimentRunRefs: string[];
  resultArtifactRefs: string[];
  decision: string;
};

export type ResearchExperimentCampaignsProjection = ResearchWorkflowScopedProjection & {
  experimentCampaigns: ExperimentCampaignSnapshot[];
};

export type CompetitionEvaluationSnapshot = {
  evaluationId: string;
  runId: string;
  rubricVersion: string;
  dimensionScores: Record<string, number>;
  claimCoverage: number;
  evidenceCoverage: number;
  experimentCoverage: number;
  deliverableCoverage: number;
  blockingWarnings: string[];
  reviewerRefs: string[];
  evaluatedAt: string;
};

export type ResearchEvaluationProjection = ResearchWorkflowScopedProjection & {
  competitionEvaluations: CompetitionEvaluationSnapshot[];
  qualityGateEvaluations: Array<Record<string, unknown>>;
};

export type ResearchLedgerProjection = ResearchWorkflowScopedProjection & {
  projectId: string;
  claimEvidence: Array<Record<string, unknown>>;
  teamKnowledge: Array<Record<string, unknown>>;
  experimentPlanning: Record<string, unknown>;
  nodeRuns: Array<Record<string, unknown>>;
  handoffs: Array<Record<string, unknown>>;
  artifactManifests: Array<Record<string, unknown>>;
  resultPackage: Record<string, unknown> | null;
  summary: {
    claimEvidenceCount: number;
    knowledgeBaseCount: number;
    nodeRunCount: number;
    handoffCount: number;
    artifactCount: number;
  };
  boundaries: {
    readOnly: true;
    persistsCanonicalEvidence: false;
    writesTeamKnowledge: false;
    writesExperimentContract: false;
    writesWorkflowRun: false;
  };
};

export type ResearchHandoffsProjection = ResearchWorkflowScopedProjection & {
  handoffs: NodeHandoffRecord[];
};
