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

export type FinancialTeamRun = {
  schemaVersion: number;
  runId: string;
  assistantAgentId: string;
  teamId: string;
  symbol: string;
  periodDays: 7 | 30 | 90;
  /** Absent only on pre-v2 saved runs. */
  researchDate?: string;
  /** Absent only on pre-v2 saved runs. */
  depth?: "brief" | "basic" | "standard" | "detailed" | "exhaustive";
  createdAt: string;
  stage: FinancialTeamRunStage;
  /** Partial only for compatible pre-v2 runs, which had no bull/bear analysts. */
  analysts: Partial<Record<FinancialTeamRole, FinancialTeamTurnRef>>;
  synthesis: FinancialTeamTurnRef;
};

export type FinancialTeamRunList = {
  assistantAgentId: string;
  runs: FinancialTeamRun[];
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
