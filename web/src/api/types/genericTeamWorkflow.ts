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
  kind: "input" | "agent" | "human" | "output";
  owner: string;
  instruction: string;
};

export type TeamFlow = {
  id: string;
  name: string;
  description: string;
  fields: WorkflowInput[];
  steps: WorkflowStep[];
  revision: number;
  updatedAt: string;
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
  attempts?: { nodeId: string; number: number; agentId: string; sessionId: string; turnId: string; status: string; key: string }[];
};

export type TeamFlowArtifact = {
  nodeId: string;
  label: string;
  sessionId: string;
  turnId: string;
  content: string;
  chatUrl?: string;
};

export type TeamFlowCommand = "confirm" | "revise" | "retry" | "stop";
