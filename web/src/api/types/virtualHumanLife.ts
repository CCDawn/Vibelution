import type { AgentPersonaProfile } from "./agents";

export type AgentPluginBinding = {
  agentId: string;
  pluginId: string;
  enabled: boolean;
  configVersion: number;
  bindingRevision: number;
  timezone?: string;
  nightlyPlanningTime?: string;
  heartbeatIntervalSeconds?: number;
  autonomyLevel?: "assisted" | "autonomous" | string;
  proactiveMessagesEnabled?: boolean;
  proactiveDailyLimit?: number;
  proactiveMinimumIntervalMinutes?: number;
  quietHours?: { start?: string; end?: string };
  toolBundleId?: string;
  promptPackId?: string;
};

export type AgentPluginCatalogEntry = {
  pluginId: string;
  displayName: string;
  description: string;
  version: string;
  trustedFirstParty: boolean;
  toolBundleId: string;
  promptPackId: string;
  toolNames: string[];
};

export type AgentPluginEntry = AgentPluginCatalogEntry & {
  binding: AgentPluginBinding | null;
};

export type AgentPluginList = {
  agentId: string;
  plugins: AgentPluginEntry[];
};

export type VirtualHumanMood = {
  label: string;
  valence: number;
  arousal: number;
  stability: number;
  updatedAt: string;
};

export type VirtualHumanLifeState = {
  stateVersion: number;
  localDate: string;
  timezone: string;
  currentLocation: string;
  currentActivityId: string;
  mood: VirtualHumanMood;
  energy: number;
  sleepState: string;
  socialNeed: number;
  relationshipSummary: string;
  lifePaused: boolean;
  lastHeartbeatAt: string;
};

export type VirtualHumanActivity = {
  activityId: string;
  title: string;
  kind: string;
  startAt: string;
  endAt: string;
  status: string;
  origin: string;
};

export type VirtualHumanSchedule = {
  agentId: string;
  localDate: string;
  scheduleVersion: number;
  activities: VirtualHumanActivity[];
  timezone?: string;
  planningMode?: string;
  createdAt?: string;
  updatedAt?: string;
};

export type VirtualHumanScheduleBundle = {
  agentId: string;
  today: VirtualHumanSchedule | null;
  tomorrow: VirtualHumanSchedule | null;
};

export type VirtualHumanLifeEventOutcome = {
  status?: string;
  kind?: string;
  summary?: string;
  recordedAt?: string;
  salienceScore?: number;
  [key: string]: unknown;
};

export type VirtualHumanLifeEvent = {
  eventId: string;
  agentId: string;
  activityId?: string;
  kind: string;
  title?: string;
  occurredAt?: string;
  outcome?: VirtualHumanLifeEventOutcome;
  simulatedAfterRestart?: boolean;
  failureReason?: string;
  [key: string]: unknown;
};

export type VirtualHumanDiaryEntry = {
  diaryEntryId: string;
  agentId: string;
  localDate: string;
  title?: string;
  content?: string;
  sourceEventIds: string[];
  writtenAt?: string;
  projectionKind?: string;
  [key: string]: unknown;
};

export type VirtualHumanRelationship = {
  targetId: string;
  intimacy: number;
  trust: number;
  updatedAt?: string;
  summary?: string;
  [key: string]: unknown;
};

export type VirtualHumanSnapshot = {
  pluginId: string;
  agentId: string;
  installed: boolean;
  bound: boolean;
  binding: AgentPluginBinding | null;
  state: VirtualHumanLifeState | null;
  todaySchedule: VirtualHumanSchedule | null;
  tomorrowSchedule: VirtualHumanSchedule | null;
  proactiveUsage: {
    delivered: number;
    limit: number;
    remaining: number;
  };
};

export type VirtualHumanCompanion = {
  agentId: string;
  agentCode: string;
  displayName: string;
  directSessionId: string;
  avatarImageUrl: string;
  personaProfile: Partial<AgentPersonaProfile>;
  status: string;
  snapshot: VirtualHumanSnapshot;
};

export type AgentPluginBindingUpdate = {
  enabled: boolean;
  expectedVersion: number;
  config: Record<string, unknown>;
};
