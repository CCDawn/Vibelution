export type PersonalAssistant = {
  agentId: string;
  displayName: string;
  directSessionId: string;
  status: "active";
  setupStatus: "ready" | "session_missing" | "setup_required";
  profile: "personal_assistant_v1";
  renderer: "whale";
};

export type PersonalAssistantResponse = { assistant: PersonalAssistant | null };
export type PersonalAssistantOverview = {
  generatedAt: string;
  counts: { agents: number; sessions: number; running: number; waiting: number; failed: number };
  agents: Array<{ id: string; displayName: string; status: string }>;
  sessions: Array<{ id: string; agentId: string; title: string; status: string; currentPhase: string }>;
  attention: Array<{ id: string; kind: string; title: string; sessionId?: string }>;
};
