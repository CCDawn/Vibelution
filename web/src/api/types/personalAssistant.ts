/** Renderer whitelist: the whale rig (dafeiyu) and Xiao Luo Live2D (xiaoluo). */
export type PersonalAssistantRenderer = "whale" | "xiaoluo";
export type PersonalAssistantAppearance = "dafeiyu" | "xiaoluo";

export type PersonalAssistant = {
  agentId: string;
  displayName: string;
  directSessionId: string;
  status: "active";
  setupStatus: "ready" | "session_missing" | "setup_required";
  profile: "personal_assistant_v1";
  renderer: PersonalAssistantRenderer;
};

export type PersonalAssistantPreferences = {
  characterId: PersonalAssistantAppearance;
  showStatus: boolean;
  showTitles: boolean;
  showCompletion: boolean;
  idleMessage: string;
};

export type PersonalAssistantModelChoice = {
  modelId: string;
  label: string;
  providerLabel: string;
  isDefault: boolean;
  providerHealthy: boolean;
  missingApiKey: boolean;
  availability: string;
};

export type PersonalAssistantModelSettings = {
  currentModelId: string;
  choices: PersonalAssistantModelChoice[];
};

export type PersonalAssistantSettings = {
  displayName: string;
  preferences: PersonalAssistantPreferences;
  /** False until the backend persisted preferences at least once. */
  preferencesConfigured: boolean;
  model: PersonalAssistantModelSettings;
};

export type PersonalAssistantResponse = { assistant: PersonalAssistant | null };
export type PersonalAssistantSettingsResponse = { settings: PersonalAssistantSettings | null };
export type PersonalAssistantModelResponse = { model: PersonalAssistantModelSettings };
export type PersonalAssistantOverview = {
  generatedAt: string;
  counts: { agents: number; sessions: number; running: number; waiting: number; failed: number };
  agents: Array<{ id: string; displayName: string; status: string }>;
  sessions: Array<{ id: string; agentId: string; title: string; status: string; currentPhase: string; turnId?: string }>;
  attention: Array<{ id: string; kind: string; title: string; sessionId?: string }>;
  pagination?: { offset: number; limit: number; nextOffset: number | null; revision?: string };
};
