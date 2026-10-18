export type WorkflowInput = {
  id: string;
  label: string;
  kind: "text" | "paragraph" | "select";
  required: boolean;
  options: string[];
};

export type WorkflowStep = {
  id: string;
  label: string;
  kind: "input" | "agent" | "human" | "output" | "research";
  owner: string;
  instruction: string;
  resultContract?: "text" | "outcome_v1";
  researchSource?: { runId: string; nodeId: string } | null;
};

export type TeamFlowFailureRecoveryPolicy = {
  repairFlowId: string;
  directorAgentId: string;
  reviewerAgentId: string;
  replaySafety?: "read_only" | "idempotent" | "unknown";
  maxAttempts?: number;
  maxRepairAttempts?: number;
  repairTimeoutSeconds?: number;
  assistantAgentId?: string;
  developerAgentId?: string;
  bindingId?: string;
  expiresAt?: string;
  repairFlowRevision?: number;
  agentPolicyFingerprints?: Record<string, string>;
};

export type TeamFlowRecoveryState = {
  issueId: string;
  nodeId: string;
  status: "tracking" | "retrying" | "repairing" | "awaiting_deployment" | "awaiting_replay_decision" | "replaying" | "resolved" | "blocked" | "cancelled";
  failureCount?: number;
  repairAttempts?: number;
  repairRunId?: string;
  reason?: string;
  evidenceRefs?: string[];
  reviewerSessionId?: string;
  reviewerTurnId?: string;
  sourceAttemptKey?: string;
  replayedAttemptKey?: string;
};

export type TeamFlow = {
  id: string;
  name: string;
  description: string;
  fields: WorkflowInput[];
  steps: WorkflowStep[];
  revision: number;
  updatedAt: string;
  failureRecovery?: TeamFlowFailureRecoveryPolicy | null;
};

export type TeamFlowRun = {
  id: string;
  teamId: string;
  flow: TeamFlow;
  values: Record<string, string>;
  status: "running" | "waiting" | "completed" | "failed" | "stopped";
  current: number;
  revision: number;
  messages: string[];
  error?: string;
  stopRequested?: boolean;
  attempts?: {
    nodeId: string;
    number: number;
    agentId: string;
    sessionId: string;
    turnId: string;
    status: string;
    key: string;
    failureCode?: string;
    failureOrigin?: "native" | "result_contract";
  }[];
  recovery?: TeamFlowRecoveryState | null;
};

export type TeamFlowArtifact = {
  nodeId: string;
  label: string;
  sessionId: string;
  turnId: string;
  content: string;
  chatUrl?: string;
};

export type TeamFlowCommand = "confirm" | "revise" | "retry" | "stop" | "confirm_deployment";

export type TeamFlowRecoveryBindingRequest = {
  expectedRevision: number;
  repairFlowId: string;
  assistantAgentId: string;
  directorAgentId: string;
  developerAgentId: string;
  reviewerAgentId: string;
  acknowledgeAutomaticRecovery: boolean;
  replaySafety?: "read_only" | "idempotent" | "unknown";
  maxAttempts?: number;
  maxRepairAttempts?: number;
  repairTimeoutSeconds?: number;
  validForSeconds?: number;
};

export type TeamFlowRecoveryBindingRevokeRequest = {
  expectedRevision: number;
};

export type TeamFlowRecoveryBindingStatus = {
  schemaVersion: 1;
  teamId: string;
  flowId: string;
  sourceRevision: number;
  status: "unbound" | "legacy" | "ready" | "unavailable" | "expired";
  reason: string;
  bindingId: string;
  expiresAt: string;
  assistantAgentId: string;
  directorAgentId: string;
  developerAgentId: string;
  reviewerAgentId: string;
  repairFlowId: string;
  automaticLocalIntegration: false;
  automaticDeployment: false;
};
