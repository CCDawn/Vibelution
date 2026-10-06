export type FinancialTeamStatus = "ready" | "needs_attention" | "needs_setup";
export type FinancialTeamRole = "market" | "fundamental" | "news" | "bull" | "bear";
export type FinancialTeamRoleStatus = "ready" | "needs_attention" | "not_created";

export type FinancialTeamRoleMember = {
  role: FinancialTeamRole;
  label: string;
  agentId: string;
  sessionId: string;
  status: FinancialTeamRoleStatus;
  allowedTools: string[];
};

export type FinancialTeam = {
  assistantAgentId: string;
  assistantSessionId: string;
  teamId: string;
  status: FinancialTeamStatus;
  roles: FinancialTeamRoleMember[];
  modelBindings: Record<string, unknown>;
  assistantConfigRevision: number;
};

export type FinancialTeamTurnRef = {
  agentId: string;
  sessionId: string;
  clientSubmissionId: string;
  turnId: string;
};

export type FinancialTeamRunStage = "research" | "debate" | "synthesis";
export type FinancialTeamExecutionStatus = "applied" | "adjusted" | "default" | "unknown";
export type FinancialTeamRoleExecution = {
  requestedReasoningEffort: string | null;
  resolvedReasoningEffort: string | null;
  status: FinancialTeamExecutionStatus;
};
export type FinancialTeamExecutionPolicy = {
  requestedDepth: "brief" | "basic" | "standard" | "detailed" | "exhaustive" | null;
  requestedReasoningEffort: string | null;
  roles: Partial<Record<FinancialTeamRole, FinancialTeamRoleExecution>>;
  synthesis: FinancialTeamRoleExecution | null;
};

export type FinancialTeamRun = {
  schemaVersion: number;
  runId: string;
  assistantAgentId: string;
  teamId: string;
  symbol: string;
  marketCode?: "CN" | "HK" | "US" | null;
  periodDays: 7 | 30 | 90;
  /** Absent only on pre-v2 saved runs. */
  researchDate?: string;
  /** Absent only on pre-v2 saved runs. */
  depth?: "brief" | "basic" | "standard" | "detailed" | "exhaustive";
  /** Absent on runs created before per-session effort resolution was saved. */
  executionPolicy?: FinancialTeamExecutionPolicy;
  createdAt: string;
  stage: FinancialTeamRunStage;
  /** Optional for saved runs created before server coordination was available. */
  coordinationStatus?: "waiting" | "running" | "blocked" | "completed" | null;
  coordinationError?: string | null;
  /** Partial only for compatible pre-v2 runs, which had no bull/bear analysts. */
  analysts: Partial<Record<FinancialTeamRole, FinancialTeamTurnRef>>;
  synthesis: FinancialTeamTurnRef;
};

export type FinancialTeamRunList = {
  assistantAgentId: string;
  runs: FinancialTeamRun[];
};

export type FinancialTeamSynthesisRecoveryStatus = {
  available: boolean;
  reason: string;
};

export type FinancialTeamRunCreateRequest = {
  symbol: string;
  periodDays: 7 | 30 | 90;
  researchDate: string;
  depth: "brief" | "basic" | "standard" | "detailed" | "exhaustive";
};

export type FinancialTeamTurnAttachRequest = {
  sessionId: string;
  clientSubmissionId: string;
  turnId: string;
};
